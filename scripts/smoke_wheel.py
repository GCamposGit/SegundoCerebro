"""Smoke of a wheel installed outside the checkout (FND-09a).

The helper talks to an already-installed interpreter. CI builds the wheel,
creates a venv in $RUNNER_TEMP, installs that wheel, then calls this file
with the venv Python. PYTHONPATH is stripped only in the child.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

TIMEOUT_IMPORT_S = 60
TIMEOUT_HELP_S = 30
TIMEOUT_MCP_S = 90


class SmokeFalhou(RuntimeError):
    """A step of the wheel smoke did not hold."""


def env_sem_pythonpath(base: dict[str, str] | None = None) -> dict[str, str]:
    origem = os.environ if base is None else base
    return {chave: valor for chave, valor in origem.items() if chave.upper() != "PYTHONPATH"}


def _rodar(
    python: Path,
    codigo: str,
    *,
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — python da venv e código literal deste helper
        [str(python), "-c", codigo],
        cwd=str(cwd),
        env=env_sem_pythonpath(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _exigir(proc: subprocess.CompletedProcess[str], contexto: str) -> str:
    if proc.returncode != 0:
        detalhe = (proc.stderr or proc.stdout or "").strip()
        raise SmokeFalhou(f"{contexto}: código {proc.returncode}. {detalhe}")
    return proc.stdout


def conferir_import(python: Path, cwd: Path, pacote: str) -> None:
    saida = _exigir(
        _rodar(python, f"import {pacote}; print({pacote}.__file__)", cwd=cwd, timeout=TIMEOUT_IMPORT_S),
        f"import {pacote}",
    )
    origem = saida.strip()
    if "site-packages" not in origem.replace("\\", "/").lower() and "dist-packages" not in origem.lower():
        raise SmokeFalhou(
            f"{pacote} não veio de site-packages ({origem}). O smoke exige wheel, não checkout."
        )


def conferir_html(python: Path, cwd: Path, modulo: str, arquivo: str) -> None:
    codigo = (
        "from importlib.metadata import distribution\n"
        f"dist = distribution({modulo.split('.')[0]!r})\n"
        f"alvo = dist.locate_file({(modulo.replace('.', '/') + '/' + arquivo)!r})\n"
        "print(alvo)\n"
        "raise SystemExit(0 if alvo.is_file() else 2)\n"
    )
    proc = _rodar(python, codigo, cwd=cwd, timeout=TIMEOUT_IMPORT_S)
    if proc.returncode != 0:
        raise SmokeFalhou(
            f"asset {modulo}/{arquivo} ausente no wheel. {proc.stderr or proc.stdout}".strip()
        )


def listar_scripts(python: Path, cwd: Path, pacote: str) -> list[str]:
    codigo = (
        "from importlib.metadata import distribution\n"
        f"dist = distribution({pacote!r})\n"
        "nomes = sorted(ep.name for ep in dist.entry_points if ep.group == 'console_scripts')\n"
        "print('\\n'.join(nomes))\n"
    )
    saida = _exigir(_rodar(python, codigo, cwd=cwd, timeout=TIMEOUT_IMPORT_S), "entry_points")
    return [linha.strip() for linha in saida.splitlines() if linha.strip()]


def conferir_entry_points(python: Path, scripts: Sequence[str]) -> None:
    if not scripts:
        raise SmokeFalhou("nenhum console script no metadata do wheel")
    scripts_dir = python.parent
    sufixo = ".exe" if os.name == "nt" else ""
    for nome in scripts:
        if not (scripts_dir / f"{nome}{sufixo}").is_file():
            raise SmokeFalhou(f"console script {nome} declarado e não instalado")


def conferir_helps(python: Path, cwd: Path, scripts: Sequence[str]) -> None:
    if not scripts:
        raise SmokeFalhou("nenhum console script no metadata do wheel")
    scripts_dir = python.parent
    sufixo = ".exe" if os.name == "nt" else ""
    for nome in scripts:
        alvo = scripts_dir / f"{nome}{sufixo}"
        if not alvo.is_file():
            raise SmokeFalhou(f"console script {nome} declarado e {alvo} não existe")
        proc = subprocess.run(  # noqa: S603 — console script do wheel, argv fixo --help
            [str(alvo), "--help"],
            cwd=str(cwd),
            env=env_sem_pythonpath(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_HELP_S,
            check=False,
        )
        if proc.returncode != 0:
            raise SmokeFalhou(f"{nome} --help falhou ({proc.returncode}): {proc.stderr or proc.stdout}")


def conferir_eval_ausente(python: Path, cwd: Path) -> None:
    proc = _rodar(python, "import eval", cwd=cwd, timeout=TIMEOUT_IMPORT_S)
    if proc.returncode == 0:
        raise SmokeFalhou("import eval funcionou na instalação. eval/ não vai no wheel.")


def conferir_mcp_tools(python: Path, cwd: Path) -> None:
    codigo = (
        "import asyncio, tempfile\n"
        "from pathlib import Path\n"
        "from segundocerebro.mcp.server import Recursos, construir\n"
        "indice = Path(tempfile.mkdtemp())\n"
        "servidor = construir(Recursos(indice=indice, modelo='minilm', threads=1))\n"
        "ferramentas = asyncio.run(servidor.list_tools())\n"
        "print('\\n'.join(sorted(t.name for t in ferramentas)))\n"
    )
    saida = _exigir(_rodar(python, codigo, cwd=cwd, timeout=TIMEOUT_MCP_S), "mcp list_tools")
    nomes = {linha.strip() for linha in saida.splitlines() if linha.strip()}
    exigidas = {"search", "read_note", "neighbors", "overview"}
    faltando = sorted(exigidas - nomes)
    if faltando:
        raise SmokeFalhou(f"list_tools sem {faltando}. Obtidas: {sorted(nomes)}")
    proibidas = {"answer", "summarize", "explain"}
    achadas = sorted(nomes & proibidas)
    if achadas:
        raise SmokeFalhou(f"list_tools expôs ferramenta geradora: {achadas}")


def executar(
    python: Path,
    cwd: Path,
    *,
    pacote: str = "segundocerebro",
    html_modulo: str = "segundocerebro.painel",
    html_arquivo: str = "index.html",
    mcp: bool = True,
    runtime: bool = True,
) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    passos: list[tuple[str, object]] = [
        ("import", lambda: conferir_import(python, cwd, pacote)),
        ("html", lambda: conferir_html(python, cwd, html_modulo, html_arquivo)),
        ("eval_ausente", lambda: conferir_eval_ausente(python, cwd)),
    ]
    scripts = listar_scripts(python, cwd, pacote)
    if runtime:
        passos.append(("helps", lambda: conferir_helps(python, cwd, scripts)))
    else:
        passos.append(("entry_points", lambda: conferir_entry_points(python, scripts)))
    if mcp and runtime:
        passos.append(("mcp_tools", lambda: conferir_mcp_tools(python, cwd)))
    for nome, fn in passos:
        print(f"== {nome}", flush=True)
        fn()
        print(f"ok {nome}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke de wheel fora do checkout (FND-09a).")
    parser.add_argument("--python", type=Path, required=True, help="Python da venv que recebeu o wheel.")
    parser.add_argument("--cwd", type=Path, required=True, help="Diretório de trabalho do processo filho.")
    parser.add_argument("--pacote", default="segundocerebro")
    parser.add_argument("--html-modulo", default="segundocerebro.painel")
    parser.add_argument("--html-arquivo", default="index.html")
    parser.add_argument("--sem-mcp", action="store_true")
    parser.add_argument(
        "--sem-runtime",
        action="store_true",
        help="valida o conteúdo do wheel sem executar entry points que exigem dependências",
    )
    args = parser.parse_args(argv)
    python = args.python.resolve()
    if not python.is_file():
        print(f"python não encontrado: {python}", file=sys.stderr)
        return 2
    try:
        executar(
            python,
            args.cwd.resolve(),
            pacote=args.pacote,
            html_modulo=args.html_modulo,
            html_arquivo=args.html_arquivo,
            mcp=not args.sem_mcp,
            runtime=not args.sem_runtime,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"TIMEOUT: {exc}", file=sys.stderr)
        return 3
    except SmokeFalhou as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return 1
    print("ok smoke_wheel", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
