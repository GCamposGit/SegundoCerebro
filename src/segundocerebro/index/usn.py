"""USN change journal catch-up for the watcher (`R5.1` / `F4-W`).

Watchdog only sees the tree while this process is alive. The NTFS change
journal remembers what happened while it was off — that is the class this
module exists to close.

Windows 8.1+ exposes `FSCTL_READ_UNPRIVILEGED_USN_JOURNAL`, so a leigo does
not need to elevate. The records that ioctl returns are V3 with an empty
`FileName`; the path is reconstructed with `OpenFileById` +
`GetFinalPathNameByHandleW`. That only works while the file still exists.
Deletes (and renames away) while the watcher was off stay the third layer:
one `indexar` pass, which already reconciles.

The live loop stays watchdog. This module is catch-up on start and a
periodic poll that also covers a `ReadDirectoryChangesW` buffer overflow.

No `pywin32`. The rest of the Windows probes in this repo are ctypes.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..census import caminho_estendido, caminho_normal
from ..logger import get_logger

log = get_logger("index.usn")

NOME_DO_CURSOR = "usn.json"
FILE_ATTRIBUTE_DIRECTORY = 0x10
ERROR_JOURNAL_NOT_ACTIVE = 1179
ERROR_JOURNAL_ENTRY_DELETED = 1181
FSCTL_QUERY_USN_JOURNAL = 0x000900F4
FSCTL_READ_UNPRIVILEGED_USN_JOURNAL = 0x000903AB
GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x80
FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE = 0xFFFFFFFFFFFFFFFF
TAMANHO_BUFFER = 64 * 1024


class JournalExpirado(RuntimeError):
    """StartUsn is gone: the journal wrapped or was recreated."""


@dataclass(frozen=True)
class Journal:
    journal_id: int
    first_usn: int
    next_usn: int


@dataclass(frozen=True)
class Registro:
    frn: int
    reason: int
    attrs: int
    name: str = ""


@dataclass
class EstadoVolume:
    journal_id: int
    next_usn: int


@dataclass
class Cursor:
    """Last USN consumed, per volume, persisted next to `watcher.lock`.

    `journal_id` does not fit in a JSON number (it exceeds 2^53). Stored as a
    decimal string; parsed back to int. A silent float round-trip would skip
    or replay the wrong records and look like success.
    """

    volumes: dict[str, EstadoVolume] = field(default_factory=dict)

    @classmethod
    def carregar(cls, diretorio: Path) -> Cursor:
        alvo = Path(diretorio) / NOME_DO_CURSOR
        try:
            bruto = json.loads(alvo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return cls()
        volumes: dict[str, EstadoVolume] = {}
        for chave, item in (bruto.get("volumes") or {}).items():
            try:
                volumes[chave] = EstadoVolume(
                    journal_id=int(item["journal_id"]),
                    next_usn=int(item["next_usn"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return cls(volumes=volumes)

    def gravar(self, diretorio: Path) -> None:
        alvo = Path(diretorio) / NOME_DO_CURSOR
        payload = {
            "volumes": {
                chave: {
                    "journal_id": str(estado.journal_id),
                    "next_usn": str(estado.next_usn),
                }
                for chave, estado in self.volumes.items()
            }
        }
        texto = json.dumps(payload, ensure_ascii=False, indent=1)
        temporario = alvo.with_suffix(".json.tmp")
        try:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(texto, encoding="utf-8")
            temporario.replace(alvo)
        except OSError as erro:
            log.warning("não consegui gravar cursor USN: %s", erro)
            temporario.unlink(missing_ok=True)


class Fonte(Protocol):
    """What the catch-up needs from a journal. Tests inject a fake."""

    def volume_de(self, path: Path) -> str | None: ...
    def consultar(self, volume: str) -> Journal | None: ...
    def ler(self, volume: str, journal_id: int, start_usn: int) -> tuple[list[Registro], int]: ...
    def caminho_de(self, volume: str, frn: int) -> Path | None: ...


def parse_registros(bruto: bytes) -> tuple[list[Registro], int]:
    """Walk one `FSCTL_READ_*_USN_JOURNAL` output buffer.

    First 8 bytes are the next USN; the rest are V2/V3 records. Unknown
    major versions are skipped, not fatal — a V4 ranged record must not
    abort catch-up of the V3 records around it.
    """
    if len(bruto) < 8:
        return [], 0
    next_usn = struct.unpack_from("<q", bruto, 0)[0]
    out: list[Registro] = []
    off = 8
    while off + 8 <= len(bruto):
        rec_len, major, _minor = struct.unpack_from("<IHH", bruto, off)
        if rec_len < 60 or off + rec_len > len(bruto):
            break
        if major == 2:
            frn = struct.unpack_from("<Q", bruto, off + 8)[0]
            reason = struct.unpack_from("<I", bruto, off + 40)[0]
            attrs = struct.unpack_from("<I", bruto, off + 52)[0]
            name_len, name_off = struct.unpack_from("<HH", bruto, off + 56)
        elif major == 3:
            frn = struct.unpack_from("<Q", bruto, off + 8)[0]
            reason = struct.unpack_from("<I", bruto, off + 56)[0]
            attrs = struct.unpack_from("<I", bruto, off + 68)[0]
            name_len, name_off = struct.unpack_from("<HH", bruto, off + 72)
        else:
            off += rec_len
            continue
        nome = ""
        if name_len and name_off and off + name_off + name_len <= off + rec_len:
            nome = bruto[off + name_off : off + name_off + name_len].decode(
                "utf-16-le", "replace"
            )
        out.append(Registro(frn=frn, reason=reason, attrs=attrs, name=nome))
        off += rec_len
    return out, next_usn


def _invalido(handle: object) -> bool:
    if not handle:
        return True
    try:
        valor = int(handle)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True
    return valor in (0, -1, 0xFFFFFFFF, INVALID_HANDLE)


class FonteWin32:
    """Real journal. Open `C:\\` with backup semantics — not `\\\\.\\C:`.

    Opening the volume device needs elevation and, on this desktop, failed
    with a bad path. The root directory handle is enough for the unprivileged
    ioctl and for `OpenFileById`.
    """

    def __init__(self) -> None:
        self._handles: dict[str, object] = {}
        self._cache: dict[tuple[str, int], Path | None] = {}
        self._k32: object | None = None

    def _kernel32(self):  # noqa: ANN202 — ctypes WinDLL, imported lazily
        if self._k32 is None:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateFileW.restype = wintypes.HANDLE
            k32.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            k32.DeviceIoControl.restype = wintypes.BOOL
            k32.CloseHandle.restype = wintypes.BOOL
            k32.GetVolumePathNameW.restype = wintypes.BOOL
            k32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
            k32.OpenFileById.restype = wintypes.HANDLE
            self._k32 = k32
        return self._k32

    def fechar(self) -> None:
        k32 = self._k32
        if k32 is None:
            return
        for handle in self._handles.values():
            try:
                k32.CloseHandle(handle)
            except Exception:  # noqa: BLE001 — fechar handle do volume não pode vazar
                pass
        self._handles.clear()
        self._cache.clear()

    def volume_de(self, path: Path) -> str | None:
        import ctypes

        k32 = self._kernel32()
        buf = ctypes.create_unicode_buffer(512)
        ok = k32.GetVolumePathNameW(caminho_estendido(str(path)), buf, len(buf))
        if not ok:
            return None
        volume = buf.value
        return volume if volume else None

    def _handle(self, volume: str) -> object | None:
        if volume in self._handles:
            return self._handles[volume]
        k32 = self._kernel32()
        handle = k32.CreateFileW(
            volume,
            GENERIC_READ,
            FILE_SHARE_ALL,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if _invalido(handle):
            log.info("não abri o volume %s para USN (err %s)", volume, _last_error())
            return None
        self._handles[volume] = handle
        return handle

    def consultar(self, volume: str) -> Journal | None:
        import ctypes
        from ctypes import wintypes

        handle = self._handle(volume)
        if handle is None:
            return None
        k32 = self._kernel32()

        class USN_JOURNAL_DATA_V0(ctypes.Structure):
            _fields_ = [
                ("UsnJournalID", ctypes.c_uint64),
                ("FirstUsn", ctypes.c_int64),
                ("NextUsn", ctypes.c_int64),
                ("LowestValidUsn", ctypes.c_int64),
                ("MaxUsn", ctypes.c_int64),
                ("MaximumSize", ctypes.c_uint64),
                ("AllocationDelta", ctypes.c_uint64),
            ]

        data = USN_JOURNAL_DATA_V0()
        ret = wintypes.DWORD()
        ok = k32.DeviceIoControl(
            handle,
            FSCTL_QUERY_USN_JOURNAL,
            None,
            0,
            ctypes.byref(data),
            ctypes.sizeof(data),
            ctypes.byref(ret),
            None,
        )
        if not ok:
            err = _last_error()
            if err == ERROR_JOURNAL_NOT_ACTIVE:
                log.info("volume %s sem journal USN, observador só no vivo", volume)
            else:
                log.info("query USN em %s recusou (err %s)", volume, err)
            return None
        return Journal(
            journal_id=int(data.UsnJournalID),
            first_usn=int(data.FirstUsn),
            next_usn=int(data.NextUsn),
        )

    def ler(
        self, volume: str, journal_id: int, start_usn: int
    ) -> tuple[list[Registro], int]:
        import ctypes
        from ctypes import wintypes

        handle = self._handle(volume)
        if handle is None:
            return [], start_usn
        k32 = self._kernel32()

        class READ_USN_JOURNAL_DATA_V1(ctypes.Structure):
            _fields_ = [
                ("StartUsn", ctypes.c_int64),
                ("ReasonMask", wintypes.DWORD),
                ("ReturnOnlyOnClose", wintypes.DWORD),
                ("Timeout", ctypes.c_uint64),
                ("BytesToWaitFor", ctypes.c_uint64),
                ("UsnJournalID", ctypes.c_uint64),
                ("MinMajorVersion", wintypes.WORD),
                ("MaxMajorVersion", wintypes.WORD),
            ]

        usn = start_usn
        todos: list[Registro] = []
        while True:
            read = READ_USN_JOURNAL_DATA_V1()
            read.StartUsn = usn
            read.ReasonMask = 0xFFFFFFFF
            read.ReturnOnlyOnClose = 0
            read.Timeout = 0
            read.BytesToWaitFor = 0
            read.UsnJournalID = journal_id
            read.MinMajorVersion = 2
            read.MaxMajorVersion = 3
            buf = ctypes.create_string_buffer(TAMANHO_BUFFER)
            ret = wintypes.DWORD()
            ok = k32.DeviceIoControl(
                handle,
                FSCTL_READ_UNPRIVILEGED_USN_JOURNAL,
                ctypes.byref(read),
                ctypes.sizeof(read),
                buf,
                TAMANHO_BUFFER,
                ctypes.byref(ret),
                None,
            )
            if not ok:
                err = _last_error()
                if err == ERROR_JOURNAL_ENTRY_DELETED:
                    raise JournalExpirado(
                        f"journal USN de {volume} recuou (err {err})"
                    )
                log.warning("leitura USN em %s falhou (err %s)", volume, err)
                return todos, usn
            recs, next_usn = parse_registros(buf.raw[: ret.value])
            todos.extend(recs)
            if next_usn <= usn or not recs:
                return todos, next_usn if next_usn else usn
            usn = next_usn

    def caminho_de(self, volume: str, frn: int) -> Path | None:
        chave = (volume, frn)
        if chave in self._cache:
            return self._cache[chave]
        caminho = self._abrir_por_id(volume, frn)
        self._cache[chave] = caminho
        return caminho

    def _abrir_por_id(self, volume: str, frn: int) -> Path | None:
        import ctypes
        from ctypes import wintypes

        handle = self._handle(volume)
        if handle is None:
            return None
        k32 = self._kernel32()

        class FILE_ID_DESCRIPTOR(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("FileId", ctypes.c_uint64),
                ("_pad", ctypes.c_uint64),
            ]

        desc = FILE_ID_DESCRIPTOR()
        desc.dwSize = 24
        desc.Type = 0
        desc.FileId = frn
        aberto = k32.OpenFileById(
            handle,
            ctypes.byref(desc),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_ALL,
            None,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        )
        if _invalido(aberto):
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            n = k32.GetFinalPathNameByHandleW(aberto, buf, len(buf), 0)
            if not n:
                return None
            bruto = buf.value
            if bruto.startswith("\\\\?\\Volume{"):
                return None
            return Path(caminho_normal(bruto))
        finally:
            k32.CloseHandle(aberto)


def _last_error() -> int:
    import ctypes

    return int(ctypes.get_last_error())


def disponivel(path: Path) -> bool:
    """True when this path's volume has a journal we can read without elevation."""
    if os.name != "nt":
        return False
    fonte = FonteWin32()
    try:
        volume = fonte.volume_de(path)
        return bool(volume) and fonte.consultar(volume) is not None
    except Exception:  # noqa: BLE001 — probe de hardware: volume sem journal não derruba o observador
        return False
    finally:
        fonte.fechar()


def _sob_raiz(path: Path, raizes: list[Path]) -> bool:
    try:
        alvo = path.resolve()
    except OSError:
        return False
    for raiz in raizes:
        try:
            alvo.relative_to(raiz.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def varrer(
    raizes: list[Path],
    diretorio_indice: Path,
    *,
    fonte: Fonte | None = None,
) -> list[Path]:
    """Paths that changed since the last cursor. Empty when catch-up cannot run.

    First visit of a volume pins `NextUsn` and returns nothing: replaying the
    whole journal would restat days of noise that is already in the index.
    A wrapped or recreated journal does the same, with a warning — claiming
    catch-up after a gap would be the silent failure.
    """
    if not raizes:
        return []
    propria = fonte is None
    if fonte is None:
        if os.name != "nt":
            return []
        fonte = FonteWin32()
    cursor = Cursor.carregar(diretorio_indice)
    vistos: list[Path] = []
    try:
        por_volume: dict[str, list[Path]] = {}
        for raiz in raizes:
            volume = fonte.volume_de(Path(raiz))
            if not volume:
                continue
            por_volume.setdefault(volume, []).append(Path(raiz))
        for volume, _grupo in por_volume.items():
            journal = fonte.consultar(volume)
            if journal is None:
                continue
            estado = cursor.volumes.get(volume)
            if estado is None:
                cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
                log.info(
                    "cursor USN de %s gravado em %s; catch-up começa na próxima subida",
                    volume,
                    journal.next_usn,
                )
                continue
            if (
                estado.journal_id != journal.journal_id
                or estado.next_usn < journal.first_usn
            ):
                log.warning(
                    "journal USN de %s recuou ou foi recriado; o que mudou com o "
                    "observador desligado não entra agora — rode Indexar",
                    volume,
                )
                cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
                continue
            try:
                registros, next_usn = fonte.ler(volume, journal.journal_id, estado.next_usn)
            except JournalExpirado as erro:
                log.warning("%s; rode Indexar", erro)
                cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
                continue
            achados: dict[str, Path] = {}
            for rec in registros:
                if rec.attrs & FILE_ATTRIBUTE_DIRECTORY:
                    continue
                caminho = fonte.caminho_de(volume, rec.frn)
                if caminho is None:
                    continue
                if not _sob_raiz(caminho, raizes):
                    continue
                achados[str(caminho)] = caminho
            vistos.extend(achados.values())
            cursor.volumes[volume] = EstadoVolume(journal.journal_id, next_usn)
            if achados:
                log.info("USN recuperou %s arquivo(s) em %s", len(achados), volume)
        cursor.gravar(diretorio_indice)
    finally:
        if propria:
            fechar = getattr(fonte, "fechar", None)
            if fechar is not None:
                fechar()
    return vistos
