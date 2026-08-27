"""LibreOffice headless — one binary for formula recalc (C7.a) and legacy convert (R1.1).

Called from `reader.py`, never from a parser. The standard suite must pass
without LibreOffice installed: missing binary is `None`, not an error.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ...logger import get_logger

log = get_logger("ingest.converters.libreoffice")

TIMEOUT_PADRAO_S = 90.0

_CANDIDATOS = (
    Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    Path("/usr/bin/soffice"),
    Path("/usr/lib/libreoffice/program/soffice"),
    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
)


def encontrar_soffice() -> str | None:
    """`soffice.com` on Windows waits; `.exe` may return before the convert finishes."""
    for nome in ("soffice.com", "soffice", "soffice.exe"):
        achado = shutil.which(nome)
        if achado:
            return achado
    for candidato in _CANDIDATOS:
        if candidato.is_file():
            return str(candidato)
    return None


def _matar(proc: subprocess.Popen) -> None:
    """Kill the process tree so a timed-out convert cannot leave `soffice.bin` behind."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def recalcular_xlsx(dados: bytes, *, timeout: float = TIMEOUT_PADRAO_S) -> bytes | None:
    """Open in Calc and save so formula cells get a cached value. `None` if unavailable.

    `--convert-to xlsx` loads the workbook; Calc recalculates on load by default
    and the saved file is what `data_only=True` can read. A unique UserInstallation
    profile keeps a leftover desktop instance from swallowing the convert.
    """
    binario = encontrar_soffice()
    if binario is None:
        return None
    with tempfile.TemporaryDirectory(prefix="sc-lo-") as tmp:
        raiz = Path(tmp)
        origem_dir = raiz / "in"
        saida_dir = raiz / "out"
        perfil = raiz / "profile"
        origem_dir.mkdir()
        saida_dir.mkdir()
        origem = origem_dir / "entrada.xlsx"
        origem.write_bytes(dados)
        cmd = [
            binario,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nologo",
            "--nodefault",
            f"-env:UserInstallation={perfil.resolve().as_uri()}",
            "--convert-to",
            "xlsx:Calc MS Excel 2007 XML",
            "--outdir",
            str(saida_dir),
            str(origem),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _matar(proc)
            log.warning("LibreOffice estourou %.0fs no recálculo", timeout)
            return None
        except OSError as exc:
            log.warning("LibreOffice não arrancou: %s", exc)
            return None
        if proc.returncode not in (0, None):
            log.warning("LibreOffice saiu com código %s no recálculo", proc.returncode)
            return None
        gerados = list(saida_dir.glob("*.xlsx"))
        if not gerados:
            log.warning("LibreOffice não escreveu xlsx no recálculo")
            return None
        convertido = gerados[0].read_bytes()
        if not convertido:
            return None
        return convertido
