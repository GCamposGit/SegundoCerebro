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
    assert "reportReturnType = \"none\"" in texto
    assert "reportArgumentType = \"none\"" in texto


def test_fronteira_fnd10_tem_config_focal() -> None:
    """FND-10: the first frontier is on, globally the rest stays off."""
    respostas = (REPO / "src" / "segundocerebro" / "mcp" / "respostas.py").read_text(
        encoding="utf-8"
    )
    assert respostas.startswith(
        "# pyright: reportReturnType=error, reportArgumentType=error"
    )
    fixture = REPO / "tests" / "fixtures" / "tipos" / "pyrightconfig.json"
    assert fixture.is_file(), "config focal da fixture de tipos sumiu"
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    _, _, tipos = yml.partition("types:")
    assert "test_tipos_fronteira.py" in tipos.split("pytest:")[0]


def test_ci_roda_lint_types_e_coverage() -> None:
    """O job de pytest sozinho era o defeito. Sem estas três linhas ele volta."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "ruff check" in yml, "CI perdeu ruff check"
    assert "pyright" in yml, "CI perdeu pyright"
    assert "--cov=" in yml, "CI perdeu coverage"
    assert "--cov-fail-under=80" in yml, "piso de coverage saiu do medido−2 p.p. (82% → 80%)"


def test_ci_pytest_instala_do_lock() -> None:
    """Q2: the pytest job must not resolve floating ranges on a Tuesday.

    install-smoke is the wheel path (FND-09a). The Windows suite is the one
    that has to be the same set next month, and that job still uses the lock.
    """
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in yml, (
        "job pytest deixou de instalar o lock — um release de terceiro muda a suíte"
    )
    assert "pip install -e . --no-deps" in yml, (
        "job pytest tem de instalar o pacote sem resolver de novo por cima do lock"
    )


def test_ci_install_smoke_usa_wheel_fora_do_checkout() -> None:
    """FND-09a: install-smoke is the wheel, not an editable checkout."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    _, _, fumo = yml.partition("install-smoke:")
    assert fumo, "job install-smoke sumiu"
    assert "scripts/smoke_wheel.py" in fumo
    assert "pip wheel --no-deps" in fumo
    assert "pip install -e ." not in fumo
    assert "runner.temp" in fumo
