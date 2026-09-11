"""FND-10: the type checker rejects a real contract break outside src."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyright")

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "tipos"
TIMEOUT_S = 60
COMENTARIO = "# pyright: reportReturnType=error, reportArgumentType=error"
FRONTEIRAS = (
    REPO / "src" / "segundocerebro" / "mcp" / "respostas.py",
    REPO / "src" / "segundocerebro" / "index" / "trava.py",
)


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


@pytest.mark.parametrize("alvo", FRONTEIRAS, ids=lambda p: p.name)
def test_comentario_focal_esta_no_modulo(alvo: Path) -> None:
    """Without this comment, global reportReturnType=none makes the frontier a no-op."""
    texto = alvo.read_text(encoding="utf-8")
    assert texto.splitlines()[0] == COMENTARIO


@pytest.mark.parametrize("alvo", FRONTEIRAS, ids=lambda p: p.name)
def test_modulo_fronteira_fica_limpo(alvo: Path) -> None:
    proc = _pyright(alvo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "arquivo",
    ["positivo.py", "positivo_trava.py"],
)
def test_fixture_positiva_passa(arquivo: str) -> None:
    proc = _pyright(FIXTURE / arquivo, project=FIXTURE)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("arquivo", "simbolo"),
    [("negativo.py", "sucesso"), ("negativo_trava.py", "diretorio")],
)
def test_fixture_negativa_reprova_quebra_de_contrato(arquivo: str, simbolo: str) -> None:
    """The delivery: a wrong argument/return against the real envelope fails."""
    proc = _pyright(FIXTURE / arquivo, project=FIXTURE)
    saida = proc.stdout + proc.stderr
    assert proc.returncode != 0, saida
    assert "reportArgumentType" in saida or "reportReturnType" in saida
    assert simbolo in saida
