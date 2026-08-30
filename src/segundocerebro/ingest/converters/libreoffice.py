"""LibreOffice headless — one binary for formula recalc (C7.a) and legacy convert (R1.1).

Called from `reader.py`, never from a parser. The standard suite must pass
without LibreOffice installed: missing binary is `None`, not an error.

Per file, not a batch of 50: R1.4 already isolates the parse in a subprocess,
and a leftover desktop instance swallowing a shared convert was the C7.a
failure mode. A unique UserInstallation per call keeps that class closed.
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

# origem → (argumento --convert-to, extensão de saída)
# The xlsx filter is the same C7.a used: Calc recalculates on load.
_ALVO: dict[str, tuple[str, str]] = {
    ".doc": ("docx", ".docx"),
    ".ppt": ("pptx", ".pptx"),
    ".xls": ("xlsx:Calc MS Excel 2007 XML", ".xlsx"),
    ".xlsx": ("xlsx:Calc MS Excel 2007 XML", ".xlsx"),
}

EXTENSOES_LEGADO: dict[str, str] = {
    origem: destino for origem, (_filtro, destino) in _ALVO.items() if destino != origem
}
"""OLE legado → OOXML: quais extensões passam pelo LibreOffice antes do parser.

Derivada de `_ALVO`, e não escrita de novo, porque estava declarada em **três**
módulos que não se importam entre si: aqui, `ingest/reader.py` (`EXTENSOES_LEGADO`)
e `index/isolamento.py` (`EXTENSOES_CONVERT`, que só precisa do conjunto de
chaves, para dar o timeout maior ao filho de parse). Acrescentar um quarto formato
legado exigia lembrar dos três, e o esquecimento não falha: o formato novo
simplesmente não ganha o timeout, ou não é convertido, sem uma linha de erro.

É a forma do defeito de `docs/fatia-reuniao-invisivel.md` — régua declarada num
lugar e consumida em outro, divergindo em silêncio.

`.xlsx` fica de fora porque não é conversão de legado: é o recálculo de fórmula
do `C7.a`, mesma extensão na entrada e na saída."""


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


def converter(
    dados: bytes,
    origem: str,
    *,
    timeout: float = TIMEOUT_PADRAO_S,
) -> bytes | None:
    """Convert one file through soffice. `None` if the binary is missing or the convert fails.

    `origem` is an extension (`.doc`, `.ppt`, `.xls`, `.xlsx`). The original
    path never leaves `reader.py` — this function only sees bytes.
    """
    ext = origem.lower()
    if not ext.startswith("."):
        ext = "." + ext
    alvo = _ALVO.get(ext)
    if alvo is None:
        return None
    filtro, saida_ext = alvo
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
        entrada = origem_dir / f"entrada{ext}"
        entrada.write_bytes(dados)
        cmd = [
            binario,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nologo",
            "--nodefault",
            f"-env:UserInstallation={perfil.resolve().as_uri()}",
            "--convert-to",
            filtro,
            "--outdir",
            str(saida_dir),
            str(entrada),
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
            log.warning("LibreOffice estourou %.0fs no convert %s", timeout, ext)
            return None
        except OSError as exc:
            log.warning("LibreOffice não arrancou: %s", exc)
            return None
        if proc.returncode not in (0, None):
            log.warning("LibreOffice saiu com código %s no convert %s", proc.returncode, ext)
            return None
        gerados = list(saida_dir.glob(f"*{saida_ext}"))
        if not gerados:
            log.warning("LibreOffice não escreveu %s no convert %s", saida_ext, ext)
            return None
        convertido = gerados[0].read_bytes()
        if not convertido:
            return None
        return convertido


def recalcular_xlsx(dados: bytes, *, timeout: float = TIMEOUT_PADRAO_S) -> bytes | None:
    """Open in Calc and save so formula cells get a cached value. `None` if unavailable.

    `--convert-to xlsx` loads the workbook; Calc recalculates on load by default
    and the saved file is what `data_only=True` can read. A unique UserInstallation
    profile keeps a leftover desktop instance from swallowing the convert.
    """
    return converter(dados, ".xlsx", timeout=timeout)
