"""A config de lint/types está no Git. Sem isso o Q1 reabre sozinho.

Dois agentes, duas máquinas: ruff usado localmente sem config commitada é
drift garantido, e os `noqa` viram carga de culto. Este teste não roda o
linter — o CI faz isso. Ele só recusa o arquivo sumir.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def bloco_do_job(yml: str, nome: str) -> str:
    """Body of one GitHub Actions job, without the next job.

    Partitioning on the job title used to swallow every job below it. A new
    job after install-smoke would then inherit that job's assertions.
    """
    padrao = re.compile(
        rf"(?ms)^  {re.escape(nome)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
    )
    achado = padrao.search(yml)
    assert achado, f"job {nome} sumiu do workflow"
    return achado.group(0)


def pin_do_extra_dev(pacote: str) -> str:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    extra = pyproject["project"]["optional-dependencies"]["dev"]
    prefixo = pacote.lower() + "=="
    for spec in extra:
        bruto = spec.split("#", 1)[0].strip()
        if bruto.lower().startswith(prefixo):
            return bruto.split("==", 1)[1].strip()
    raise AssertionError(f"{pacote} sem pin == no extra [dev]")


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
    """Q2/FND-09b: the pytest job must not resolve floating ranges on a Tuesday."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    pytest_job = bloco_do_job(yml, "pytest")
    assert "pip install -r requirements-dev.txt" in pytest_job, (
        "job pytest deixou o lock de runtime+dev — um release de terceiro muda a suíte"
    )
    assert "pip install -e . --no-deps" in pytest_job, (
        "job pytest tem de instalar o pacote sem resolver de novo por cima do lock"
    )
    assert "pip install pytest-cov" not in pytest_job, (
        "pytest-cov solto por cima do lock — o pin mora no extra [dev] e no lock"
    )


def test_ci_types_instala_do_lock() -> None:
    """FND-09b: types used to `pip install -e .` and resolve ranges."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    types = bloco_do_job(yml, "types")
    assert "pip install -r requirements.txt" in types
    assert "pip install -e . --no-deps" in types
    assert f"pyright=={pin_do_extra_dev('pyright')}" in types
    assert re.search(r"pip install -e \.(?!\s*--no-deps)", types) is None, (
        "job types voltou a resolver pyproject por cima do lock"
    )


def test_ci_pins_de_toolchain_batem_com_o_extra() -> None:
    """A pin in the workflow that drifts from the extra is two sources again."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    lint = bloco_do_job(yml, "lint")
    assert f"ruff=={pin_do_extra_dev('ruff')}" in lint


def test_ci_resolve_open_nao_usa_lock() -> None:
    """Layperson path: pyproject ranges, no lock, no GPU extra."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    aberto = bloco_do_job(yml, "resolve-open")
    assert "pip install -e ." in aberto
    assert "--no-deps" not in aberto
    assert "requirements.txt" not in aberto
    assert "requirements-dev.txt" not in aberto
    assert "[gpu]" not in aberto
    assert "onnxruntime-gpu" not in aberto


def test_ci_install_smoke_usa_wheel_fora_do_checkout() -> None:
    """FND-09a: install-smoke is the wheel, not an editable checkout."""
    yml = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    fumo = bloco_do_job(yml, "install-smoke")
    assert "scripts/smoke_wheel.py" in fumo
    assert "pip wheel --no-deps" in fumo
    assert "pip install -e ." not in fumo
    assert "runner.temp" in fumo


def test_bloco_do_job_nao_engole_o_proximo() -> None:
    """Isolated case: the extractor must stop at the next job title."""
    yml = (
        "jobs:\n"
        "  primeiro:\n"
        "    run: pip install -e .\n"
        "  segundo:\n"
        "    run: echo ok\n"
    )
    primeiro = bloco_do_job(yml, "primeiro")
    assert "pip install -e ." in primeiro
    assert "echo ok" not in primeiro
    assert "segundo:" not in primeiro
