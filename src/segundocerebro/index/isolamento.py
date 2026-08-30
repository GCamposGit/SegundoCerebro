"""Parse binary formats in a subprocess — a poisonous file must not kill the wave.

Native PDF/OLE parsers can hang, leak, or abort. In-process that takes the
indexer with them; a 300k-file run cannot die on file 180 412. The child has a
timeout (60 s + 10 s/MB) and a RAM cap (Job Object on Windows, `setrlimit` on
POSIX). The parent logs one line; the detail goes to `quarentena.log`.

Text formats stay in-process: they do not load a native library that can
`abort()`, and spawning Python for every `.md` would be the cost without the
class of failure.
"""

from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from ..ingest.converters.libreoffice import EXTENSOES_LEGADO
from ..ingest.document import ParseResult, ParseStatus
from ..ingest.natureza import FAMILIA_POR_EXTENSAO, FAMILIAS_BINARIAS
from ..ingest.reader import parse_file
from ..logger import get_logger

log = get_logger("index.isolamento")

TIMEOUT_BASE_S = 60.0
TIMEOUT_POR_MB_S = 10.0
TIMEOUT_CONVERT_S = 90.0
"""R1.1: .doc/.ppt/.xls may spawn LibreOffice inside the parse child."""

EXTENSOES_CONVERT = frozenset(EXTENSOES_LEGADO)
"""Derivado da tabela do conversor: o timeout maior vale para o que de fato
passa pelo LibreOffice, e não para uma lista paralela que envelhece sozinha."""
TIMEOUT_OCR_S = 120.0
"""R1.2: a scan may rasterise and OCR every page inside the parse child."""
LOG_QUARENTENA = "quarentena.log"

EXTENSOES_ISOLADAS = frozenset(
    ext for ext, familia in FAMILIA_POR_EXTENSAO.items() if familia in FAMILIAS_BINARIAS
)
"""PDF, Office, OLE, RTF — the formats whose parser is a native library."""


def timeout_para(
    tamanho_bytes: int, path: str | None = None, *, ocr: bool = False
) -> float:
    mb = max(0.0, float(tamanho_bytes) / 1_000_000)
    teto = TIMEOUT_BASE_S + TIMEOUT_POR_MB_S * mb
    if path and os.path.splitext(path)[1].lower() in EXTENSOES_CONVERT:
        teto += TIMEOUT_CONVERT_S
    if ocr:
        teto += TIMEOUT_OCR_S
    return teto


def deve_isolar(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in EXTENSOES_ISOLADAS


def _anotar_log(indice: Path | None, linha: str) -> None:
    """One extra line in the dedicated log. Never raises."""
    if indice is None:
        return
    alvo = Path(indice) / LOG_QUARENTENA
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with alvo.open("a", encoding="utf-8") as fh:
            fh.write(linha.rstrip() + "\n")
    except OSError:
        return


def _worker_parse(conn, path: str, kwargs: dict) -> None:  # noqa: ANN001
    ram_bytes = int(kwargs.pop("ram_bytes", 0) or 0)
    if ram_bytes > 0 and os.name != "nt":
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (ram_bytes, ram_bytes))
        except Exception:  # noqa: BLE001 — a missing rlimit is not a reason to skip the file
            pass
    try:
        resultado = parse_file(path, **kwargs)
        conn.send(resultado)
    except Exception as exc:  # noqa: BLE001 — the parent turns this into a recorded status
        conn.send(
            ParseResult(
                path=path,
                status=ParseStatus.ERROR,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
    finally:
        conn.close()


def _worker_abort(conn, path: str, kwargs: dict) -> None:  # noqa: ANN001, ARG001
    """Test helper: the child dies the way a native parser abort dies."""
    os.abort()


def _worker_abort_stderr(conn, path: str, kwargs: dict) -> None:  # noqa: ANN001, ARG001
    """Same death, after writing to fd 2 — OpenBLAS dies like this."""
    os.write(2, b"OpenBLAS error: Memory allocation still failed after 10 retries\n")
    os.abort()


def _worker_hang(conn, path: str, kwargs: dict) -> None:  # noqa: ANN001, ARG001
    """Test helper: the child never returns — the timeout has to kill it."""
    time.sleep(3600)


WORKERS = {
    "parse": _worker_parse,
    "abort": _worker_abort,
    "abort_stderr": _worker_abort_stderr,
    "hang": _worker_hang,
}


def _redirigir_stderr(caminho: str) -> None:
    """Point fd 2 at `caminho`. OpenBLAS writes to the fd, not to sys.stderr."""
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    try:
        os.dup2(fd, 2)
    finally:
        os.close(fd)


def _cauda_stderr(caminho: str) -> str:
    try:
        bruto = Path(caminho).read_bytes()
    except OSError:
        return ""
    texto = bruto.decode("utf-8", errors="replace").strip()
    return texto[-400:]


def _despachar(nome: str, conn, path: str, kwargs: dict, stderr_path: str = "") -> None:  # noqa: ANN001
    if stderr_path:
        try:
            _redirigir_stderr(stderr_path)
        except OSError:
            pass
    WORKERS[nome](conn, path, kwargs)


_jobs_vivos: list[object] = []
"""Job Object handles must outlive the child. Closing them early lifts the cap."""


def _limitar_ram_windows(pid: int, ram_bytes: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
    PROCESS_ALL_ACCESS = 0x1F0FFF

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = int(ram_bytes)
    ok = kernel32.SetInformationJobObject(
        handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(handle)
        raise OSError(ctypes.get_last_error())
    proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not proc:
        kernel32.CloseHandle(handle)
        raise OSError(ctypes.get_last_error())
    try:
        if not kernel32.AssignProcessToJobObject(handle, proc):
            raise OSError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(proc)
    _jobs_vivos.append(handle)


def _matar(proc: multiprocessing.Process) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=2)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=2)


def parse_isolado(
    path: str,
    *,
    allow_hydration: bool = False,
    retries: int = 1,
    espera: float = 0.5,
    limite_planilha_mb: float | None = None,
    limites_mb: Mapping[str, float] | None = None,
    timeout: float | None = None,
    ram_mb: int | None = None,
    worker: str = "parse",
    indice: Path | None = None,
    ocr: bool = False,
) -> ParseResult:
    """Parse one file, in a child when the format can abort the process.

    `worker` is a name in `WORKERS`, looked up *in the child* so tests of
    abort/hang survive Windows `spawn` (a monkeypatch in the parent does not).
    """
    kwargs = {
        "allow_hydration": allow_hydration,
        "retries": retries,
        "espera": espera,
        "limite_planilha_mb": limite_planilha_mb,
        "limites_mb": dict(limites_mb) if limites_mb else None,
        "ocr": ocr,
    }
    try:
        tamanho = os.stat(path).st_size
    except OSError as exc:
        return ParseResult(
            path=path,
            status=ParseStatus.ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        )

    if tamanho == 0 and deve_isolar(path):
        return ParseResult(
            path=path,
            status=ParseStatus.ERROR,
            detail="arquivo de 0 bytes",
        )

    if worker == "parse" and not deve_isolar(path):
        return parse_file(path, **kwargs)

    teto = timeout if timeout is not None else timeout_para(tamanho, path, ocr=ocr)
    ram_bytes = int(ram_mb * 1024 * 1024) if ram_mb else 0
    if ram_bytes:
        kwargs["ram_bytes"] = ram_bytes

    ctx = multiprocessing.get_context("spawn")
    receptor, emissor = ctx.Pipe(duplex=False)
    stderr_fd, stderr_path = tempfile.mkstemp(prefix="parse-isolado-", suffix=".stderr")
    os.close(stderr_fd)
    proc = ctx.Process(
        target=_despachar,
        args=(worker, emissor, path, kwargs, stderr_path),
        daemon=True,
    )
    proc.start()
    emissor.close()
    if ram_bytes and os.name == "nt" and proc.pid:
        try:
            _limitar_ram_windows(proc.pid, ram_bytes)
        except Exception as exc:  # noqa: BLE001 — cap is best-effort
            log.debug("Job Object recusou o teto de RAM: %s", exc)

    resultado: ParseResult | None = None
    estourou = False
    try:
        if receptor.poll(teto):
            try:
                resultado = receptor.recv()
            except EOFError:
                resultado = None
        else:
            estourou = True
            _matar(proc)
    finally:
        receptor.close()
        if proc.is_alive():
            _matar(proc)
        proc.join(timeout=1)
        cauda = _cauda_stderr(stderr_path)
        _apagar_stderr(stderr_path)

    if estourou:
        detalhe = _detalhe_com_stderr(f"timeout de {teto:.0f}s", cauda)
        _anotar_log(indice, f"{path}\t{detalhe}")
        log.warning("parse isolado estourou %.0fs: %s", teto, path)
        return ParseResult(path=path, status=ParseStatus.ERROR, detail=detalhe)

    if resultado is not None:
        return resultado

    sinal = proc.exitcode
    detalhe = _detalhe_com_stderr(f"subprocesso morreu (código {sinal})", cauda)
    _anotar_log(indice, f"{path}\t{detalhe}")
    log.warning("parse isolado morreu código %s: %s", sinal, path)
    return ParseResult(path=path, status=ParseStatus.ERROR, detail=detalhe)


def _detalhe_com_stderr(base: str, cauda: str) -> str:
    if not cauda:
        return base
    return f"{base}: {cauda}"


def _apagar_stderr(caminho: str) -> None:
    try:
        os.unlink(caminho)
    except OSError:
        return
