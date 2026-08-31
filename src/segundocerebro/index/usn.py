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

from ..logger import get_logger

log = get_logger("index.usn")

NOME_DO_CURSOR = "usn.json"
FILE_ATTRIBUTE_DIRECTORY = 0x10


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







def disponivel(path: Path) -> bool:
    """True when this path's volume has a journal we can read without elevation."""
    if os.name != "nt":
        return False
    # Importado aqui, e nao no topo: `usn_win32` importa deste modulo.
    from .usn_win32 import FonteWin32

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


def _varrer_volume(
    fonte: Fonte, volume: str, cursor: Cursor, raizes: list[Path]
) -> list[Path]:
    """O que mudou num volume desde o cursor. Grava o cursor novo em `cursor`.

    Extraida de `varrer` em 30/08/2026 pelo teto de 60 linhas por funcao. As
    tres saidas que devolvem lista vazia nao sao a mesma coisa, e por isso
    nenhuma delas e um `except` largo: volume sem journal e ausencia, primeira
    visita e fixacao do ponto de partida, e journal recuado e lacuna declarada.
    """
    journal = fonte.consultar(volume)
    if journal is None:
        return []
    estado = cursor.volumes.get(volume)
    if estado is None:
        cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
        log.info(
            "cursor USN de %s gravado em %s; catch-up começa na próxima subida",
            volume,
            journal.next_usn,
        )
        return []
    if estado.journal_id != journal.journal_id or estado.next_usn < journal.first_usn:
        log.warning(
            "journal USN de %s recuou ou foi recriado; o que mudou com o "
            "observador desligado não entra agora — rode Indexar",
            volume,
        )
        cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
        return []
    try:
        registros, next_usn = fonte.ler(volume, journal.journal_id, estado.next_usn)
    except JournalExpirado as erro:
        log.warning("%s; rode Indexar", erro)
        cursor.volumes[volume] = EstadoVolume(journal.journal_id, journal.next_usn)
        return []
    achados: dict[str, Path] = {}
    for rec in registros:
        if rec.attrs & FILE_ATTRIBUTE_DIRECTORY:
            continue
        caminho = fonte.caminho_de(volume, rec.frn)
        if caminho is None or not _sob_raiz(caminho, raizes):
            continue
        achados[str(caminho)] = caminho
    cursor.volumes[volume] = EstadoVolume(journal.journal_id, next_usn)
    if achados:
        log.info("USN recuperou %s arquivo(s) em %s", len(achados), volume)
    return list(achados.values())


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

        from .usn_win32 import FonteWin32  # ver `disponivel`

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
        for volume in por_volume:
            vistos.extend(_varrer_volume(fonte, volume, cursor, raizes))
        cursor.gravar(diretorio_indice)
    finally:
        if propria:
            fechar = getattr(fonte, "fechar", None)
            if fechar is not None:
                fechar()
    return vistos
