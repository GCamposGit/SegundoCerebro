"""A config de lint/types está no Git. Sem isso o Q1 reabre sozinho.

Dois agentes, duas máquinas: ruff usado localmente sem config commitada é
drift garantido, e os `noqa` viram carga de culto. Este teste não roda o
linter — o CI faz isso. Ele só recusa o arquivo sumir.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_ruff_e_pyright_estao_no_pyproject() -> None:
    texto = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in texto, "config do ruff saiu do pyproject.toml — o Q1 reabre"
    assert "[tool.ruff.lint]" in texto
    assert "[tool.pyright]" in texto, "config do pyright saiu do pyproject.toml — o Q1 reabre"
    assert "typeCheckingMode" in texto


def test_ci_roda_lint_types_e_coverage() -> None:
    """O job de pytest sozinho era o defeito. Sem estas três linhas ele volta."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "ruff check" in yml, "CI perdeu ruff check"
    assert "pyright" in yml, "CI perdeu pyright"
    assert "--cov=" in yml, "CI perdeu coverage"
    assert "--cov-fail-under=80" in yml, "piso de coverage saiu do medido−2 p.p. (82% → 80%)"


def test_ci_pytest_instala_do_lock() -> None:
    """Q2: the pytest job must not resolve floating ranges on a Tuesday.

    install-smoke keeps `pip install -e .` — that job proves the package
    installs from pyproject on three OSes. The Windows suite is the one that
    has to be the same set next month.
    """
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in yml, (
        "job pytest deixou de instalar o lock — um release de terceiro muda a suíte"
    )
    assert "pip install -e . --no-deps" in yml, (
        "job pytest tem de instalar o pacote sem resolver de novo por cima do lock"
    )
