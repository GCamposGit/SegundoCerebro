"""FND-10: the type checker rejects a real contract break outside src."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyright")

REPO = Path(__file__).resolve().parents[1]
FRONTEIRA = REPO / "src" / "segundocerebro" / "mcp" / "respostas.py"
FIXTURE = REPO / "tests" / "fixtures" / "tipos"
TIMEOUT_S = 60


def _pyright(*alvos: Path, project: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "pyright"]
    if project is not None:
        cmd.extend(["--project", str(project)])
    cmd.extend(str(p) for p in alvos)
    return subprocess.run(  # noqa: S603 — pyright pinned, argv from fixtures
        cmd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
        cwd=str(REPO),
    )


def test_comentario_focal_esta_no_modulo() -> None:
    """Without this comment, global reportReturnType=none makes the frontier a no-op."""
    texto = FRONTEIRA.read_text(encoding="utf-8")
    assert texto.splitlines()[0] == "# pyright: reportReturnType=error, reportArgumentType=error"


def test_modulo_fronteira_fica_limpo() -> None:
    proc = _pyright(FRONTEIRA)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fixture_positiva_passa() -> None:
    proc = _pyright(FIXTURE / "positivo.py", project=FIXTURE)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fixture_negativa_reprova_quebra_de_contrato() -> None:
    """The delivery: a wrong argument/return against the real envelope fails."""
    proc = _pyright(FIXTURE / "negativo.py", project=FIXTURE)
    saida = proc.stdout + proc.stderr
    assert proc.returncode != 0, saida
    assert "reportArgumentType" in saida or "reportReturnType" in saida
    assert "sucesso" in saida or "erro_operacional" in saida
