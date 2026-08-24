"""The package installs with `pip install -e .` and imports without PYTHONPATH.

The failure mode this exists to catch is the one Claude Desktop shows as
"servidor não conecta": `ModuleNotFoundError` because the client starts in
`C:\\Windows\\System32` and `PYTHONPATH=src` points at nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def _env_sem_pythonpath() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}


def _script(nome: str) -> Path:
    ext = ".exe" if os.name == "nt" else ""
    return Path(sys.executable).resolve().parent / f"{nome}{ext}"


def test_pyproject_le_dependencias_do_requirements() -> None:
    """Uma lista só. Copiar requirements.txt para o toml envelhece na próxima pin."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dynamic = pyproject["tool"]["setuptools"]["dynamic"]
    assert dynamic["dependencies"]["file"] == ["requirements.txt"]
    scripts = pyproject["project"]["scripts"]
    assert scripts["segundocerebro-mcp"].endswith("mcp.server:main")
    assert scripts["segundocerebro-painel"].endswith("painel.__main__:main")
    assert scripts["segundocerebro-indexar"].endswith("index.indexer:main")
    extras = pyproject["project"]["optional-dependencies"]
    assert "gpu" in extras
    assert "ocr" in extras


def test_import_sem_pythonpath_de_system32() -> None:
    cwd = SYSTEM32 if SYSTEM32.is_dir() else Path(sys.executable).anchor
    proc = subprocess.run(
        [sys.executable, "-c", "import segundocerebro; from segundocerebro.mcp.server import main"],
        cwd=str(cwd),
        env=_env_sem_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_script_mcp_help_sem_pythonpath() -> None:
    alvo = _script("segundocerebro-mcp")
    assert alvo.is_file(), (
        f"{alvo} ausente — `pip install -e .` não rodou neste ambiente. "
        "É o degrau que o leigo precisa; a suíte do CI instala o pacote."
    )
    cwd = SYSTEM32 if SYSTEM32.is_dir() else Path(sys.executable).anchor
    proc = subprocess.run(
        [str(alvo), "--help"],
        cwd=str(cwd),
        env=_env_sem_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "segundocerebro" in proc.stdout.lower() or "--base" in proc.stdout


def test_scripts_painel_e_indexar_existem() -> None:
    assert _script("segundocerebro-painel").is_file()
    assert _script("segundocerebro-indexar").is_file()
