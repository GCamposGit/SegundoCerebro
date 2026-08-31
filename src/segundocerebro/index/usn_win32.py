"""O volume NTFS: o ioctl do journal USN, e nada de politica.

Saiu de `index/usn.py` em 30/08/2026, na fusao da `F4-W` com o teto de tamanho
que o `Q16` passou a conferir (`tests/test_tamanho_dos_modulos.py`). O modulo
nascia com 534 linhas, e a regra e que **modulo novo nao nasce grande**.

A costura nao foi escolhida pelo numero: e a que o proprio docstring da `F4-W`
ja descrevia. O que esta aqui so roda no Windows e so se prova contra um volume
de verdade — mock do ioctl seria o modo de falha da `F3.5-D` outra vez. O que
ficou em `usn.py` e o contrato `Fonte`, o cursor e a varredura, e prova-se com
um journal falso em qualquer sistema.
"""

from __future__ import annotations

from pathlib import Path

from ..census import caminho_estendido, caminho_normal
from ..logger import get_logger
from .usn import Journal, JournalExpirado, Registro, parse_registros

log = get_logger("index.usn_win32")

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
