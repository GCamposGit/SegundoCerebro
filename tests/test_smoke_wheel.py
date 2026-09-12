"""FND-09a: wheel smoke outside the checkout, against a toy package.

The product wheel stays in CI. This file proves the helper's class of
defects: missing HTML, PYTHONPATH leak, eval present, console script --help.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "smoke_wheel.py"
TIMEOUT_VENV_S = 120
TIMEOUT_SMOKE_S = 60


def _carregar_helper():
    spec = importlib.util.spec_from_file_location("smoke_wheel", HELPER)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _escrever_toy(raiz: Path, *, com_html: bool) -> None:
    src = raiz / "src" / "toy_smoke"
    (src / "painel").mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "painel" / "__init__.py").write_text("", encoding="utf-8")
    (src / "cli.py").write_text(
        "import argparse\n\ndef main() -> None:\n    argparse.ArgumentParser(prog='toy-help').parse_args()\n",
        encoding="utf-8",
    )
    if com_html:
        (src / "painel" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    dados = 'toy_smoke = ["painel/index.html"]' if com_html else "toy_smoke = []"
    (raiz / "pyproject.toml").write_text(
        f"""[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "toy_smoke"
version = "0.0.1"
[project.scripts]
toy-help = "toy_smoke.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
{dados}
""",
        encoding="utf-8",
    )


def _python_venv(diretorio: Path) -> Path:
    if os.name == "nt":
        return diretorio / "Scripts" / "python.exe"
    return diretorio / "bin" / "python"


def _montar_venv_com_wheel(tmp: Path, *, com_html: bool, com_eval: bool = False) -> Path:
    pkg = tmp / "pkg"
    dist = tmp / "dist"
    env = tmp / "venv"
    pkg.mkdir(parents=True)
    dist.mkdir(parents=True)
    _escrever_toy(pkg, com_html=com_html)
    wheel = subprocess.run(  # noqa: S603 — pip wheel do fixture sintético, argv fixo
        [
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "-w", str(dist), str(pkg),
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_VENV_S,
        check=False,
    )
    assert wheel.returncode == 0, wheel.stderr
    rodas = list(dist.glob("*.whl"))
    assert len(rodas) == 1, rodas
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(env)
    py = _python_venv(env)
    inst = subprocess.run(  # noqa: S603 — pip install do wheel sintético, argv fixo
        [str(py), "-m", "pip", "install", str(rodas[0])],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_VENV_S,
        check=False,
    )
    assert inst.returncode == 0, inst.stderr
    if com_eval:
        site = subprocess.run(  # noqa: S603 — python da venv, código literal
            [str(py), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        destino = Path(site.stdout.strip()) / "eval.py"
        destino.write_text("PRESENTE = True\n", encoding="utf-8")
    return py


def _smoke(py: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — helper versionado, argv fixo
        [
            sys.executable,
            str(HELPER),
            "--python",
            str(py),
            "--cwd",
            str(cwd),
            "--pacote",
            "toy_smoke",
            "--html-modulo",
            "toy_smoke.painel",
            "--html-arquivo",
            "index.html",
            "--sem-mcp",
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SMOKE_S,
        check=False,
    )


def test_env_sem_pythonpath_nao_vaza() -> None:
    helper = _carregar_helper()
    limpo = helper.env_sem_pythonpath({"PYTHONPATH": "src", "Path": "C:\\Windows", "FOO": "1"})
    assert "PYTHONPATH" not in limpo
    assert limpo["FOO"] == "1"


def test_wheel_toy_passa_fora_do_checkout(tmp_path: Path) -> None:
    py = _montar_venv_com_wheel(tmp_path / "ok", com_html=True)
    cwd = tmp_path / "cwd"
    proc = _smoke(py, cwd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "ok smoke_wheel" in proc.stdout
    assert "ok html" in proc.stdout
    assert "ok helps" in proc.stdout


def test_wheel_sem_html_reprova(tmp_path: Path) -> None:
    py = _montar_venv_com_wheel(tmp_path / "semhtml", com_html=False)
    proc = _smoke(py, tmp_path / "cwd")
    assert proc.returncode == 1, proc.stdout
    assert "index.html" in proc.stderr


def test_eval_no_site_packages_reprova(tmp_path: Path) -> None:
    py = _montar_venv_com_wheel(tmp_path / "comeval", com_html=True, com_eval=True)
    proc = _smoke(py, tmp_path / "cwd")
    assert proc.returncode == 1, proc.stdout
    assert "import eval" in proc.stderr
