r"""The package installs with `pip install -e .` and imports without PYTHONPATH.

The failure mode this exists to catch is the one Claude Desktop shows as
"servidor não conecta": `ModuleNotFoundError` because the client starts in
`C:\Windows\System32` and `PYTHONPATH=src` points at nothing.

**A guarda cobria metade da superfície até 29/08/2026**, e é a mesma classe que
`f82b2f3` nomeou ("guarda cobria só `registrar`, não `aplicar`"). Os dois testes
de subprocesso importam `segundocerebro` e `mcp.server.main` — nenhum dos dois
toca `BuscaHibrida.search`, que fazia `from eval.harness import Hit` **dentro do
corpo da função**. `eval/` é o único diretório do projeto que o `pyproject.toml`
não empacota, então o caminho onde a série histórica inteira foi medida levantava
`ModuleNotFoundError` para quem instalou com `pip` — e nada aqui via.

Import dentro de função é invisível para teste de import de módulo, por
construção. Por isso a guarda nova não é outro subprocesso: é uma varredura de
AST sobre `src/`, que enxerga o import onde quer que ele esteja.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
PACOTE = REPO / "src" / "segundocerebro"

DEPENDE_DE_EVAL = {"painel/medir.py"}
"""Os módulos do produto autorizados a alcançar `eval/`, e o motivo de cada um.

`painel/medir.py` é o botão "Medir": ele roda o conjunto dourado da base, que é
exatamente o que `eval/harness.py` faz. Não há como medir sem a régua, e a régua
não vai no pacote porque carrega o acervo de quem mediu.

O que a autorização exige em troca está em `test_a_dependencia_de_eval_e_guardada`:
o import mora dentro de um `try` e a ausência vira `MedicaoIndisponivel`, com
texto em português. Instalação sem `eval/` perde a medição, não o painel."""


def _env_sem_pythonpath() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}


def _script(nome: str) -> Path:
    r"""Onde o console script realmente mora — `sysconfig`, não `sys.executable`.

    É o `R8.1.b`, e ele reprovava dois testes desta suíte no notebook desde o
    PR #14. Numa instalação de usuário do Python (não em venv) o interpretador
    fica em `…\Python312\python.exe` e os pontos de entrada em
    `…\Python312\Scripts\`, que **não é** o diretório do interpretador. Em
    venv os dois coincidem, e é por isso que passou despercebido: o CI usa venv.

    `sysconfig.get_path("scripts")` é a resposta do próprio instalador à
    pergunta "onde o `pip` pôs isso", e vale nos dois layouts.
    """
    ext = ".exe" if os.name == "nt" else ""
    return Path(sysconfig.get_path("scripts")) / f"{nome}{ext}"


def test_pyproject_le_dependencias_do_requirements() -> None:
    """Uma lista só. Copiar requirements.txt para o toml envelhece na próxima pin."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dynamic = pyproject["tool"]["setuptools"]["dynamic"]
    assert dynamic["dependencies"]["file"] == ["requirements.txt"]
    scripts = pyproject["project"]["scripts"]
    assert scripts["segundocerebro-mcp"].endswith("mcp.server:main")
    assert scripts["segundocerebro-painel"].endswith("painel.__main__:main")
    assert scripts["segundocerebro-indexar"].endswith("index.indexer:main")
    assert scripts["segundocerebro-observar"].endswith("index.watcher:main")
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
    proc = subprocess.run(  # noqa: S603 — console script instalado, argv fixo
        [str(alvo), "--help"],
        cwd=str(cwd),
        env=_env_sem_pythonpath(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "segundocerebro" in proc.stdout.lower() or "--base" in proc.stdout


def _pontos_de_entrada() -> dict[str, str]:
    """Os console scripts que o `pyproject.toml` declara, lidos dele."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["scripts"]


@pytest.mark.parametrize("nome", sorted(_pontos_de_entrada()), ids=sorted(_pontos_de_entrada()))
def test_todo_ponto_de_entrada_declarado_foi_instalado(nome: str) -> None:
    """A lista sai do `pyproject.toml`, e não de três nomes escritos aqui.

    Achado em 30/08/2026: o `pyproject.toml` declarava **cinco** console
    scripts e esta suíte conferia **dois** — `painel` e `indexar`. O
    `segundocerebro-observar` estava declarado e o `.exe` não existia neste
    ambiente, e nada reprovava. É a classe que este repositório já nomeou depois
    de um merge paralelo: *a guarda cobria metade da superfície*.

    Derivar a lista fecha a classe inteira: ponto de entrada novo no
    `pyproject.toml` nasce conferido, sem ninguém lembrar de acrescentá-lo.
    """
    alvo = _script(nome)
    assert alvo.is_file(), (
        f"{alvo} ausente. O `pyproject.toml` declara `{nome}` e o instalador não o "
        "produziu neste ambiente — rode `pip install -e .` na raiz do repositório. "
        "É o degrau que o leigo precisa, e é o que o CI instala."
    )


def _imports_de(arquivo: Path) -> set[str]:
    """Todo módulo de topo importado no arquivo — inclusive dentro de função."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            nomes.add(no.module.split(".")[0])
    return nomes


def _guardado(no: ast.AST) -> bool:
    """O `import eval` está dentro de um `try` que trata `ModuleNotFoundError`?"""
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Try):
            continue
        alcanca = any(
            isinstance(x, ast.ImportFrom) and (x.module or "").split(".")[0] == "eval"
            for corpo in filho.body
            for x in ast.walk(corpo)
        )
        trata = any(
            isinstance(h.type, ast.Name) and h.type.id in {"ModuleNotFoundError", "ImportError"}
            for h in filho.handlers
        )
        if alcanca and trata:
            return True
    return False


def test_o_produto_nao_importa_o_repositorio() -> None:
    """`src/` não alcança `eval/`, exceto onde está declarado e guardado.

    `eval` fica fora de `[tool.setuptools.packages.find]`, então todo import dele
    a partir do produto é um `ModuleNotFoundError` esperando o primeiro usuário
    que instalou com `pip`. A varredura é de AST porque o caso real —
    `BuscaHibrida.search` — escondia o import no corpo de um método.
    """
    intrusos = sorted(
        arquivo.relative_to(PACOTE).as_posix()
        for arquivo in PACOTE.rglob("*.py")
        if "eval" in _imports_de(arquivo)
        and arquivo.relative_to(PACOTE).as_posix() not in DEPENDE_DE_EVAL
    )
    assert not intrusos, (
        f"módulo do produto importando `eval/`: {intrusos}. `eval` não vai no pacote — "
        "mova o que for contrato para `src/`, ou declare em DEPENDE_DE_EVAL e guarde o import."
    )


def test_a_dependencia_de_eval_e_guardada() -> None:
    """Quem depende de `eval/` tem de sobreviver à ausência dela, com texto legível."""
    for relativo in sorted(DEPENDE_DE_EVAL):
        arquivo = PACOTE / relativo
        assert arquivo.is_file(), f"{relativo} está em DEPENDE_DE_EVAL e não existe"
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        assert _guardado(arvore), (
            f"{relativo} importa `eval/` sem guarda: sem o repositório isso vira "
            "ModuleNotFoundError cru na cara do usuário."
        )


def test_a_lista_de_quem_depende_de_eval_nao_cresce_de_graca() -> None:
    """Autorização que não é usada é autorização que ninguém revisa."""
    ociosos = sorted(
        relativo
        for relativo in DEPENDE_DE_EVAL
        if "eval" not in _imports_de(PACOTE / relativo)
    )
    assert not ociosos, f"{ociosos} não importa mais `eval/` — tirar de DEPENDE_DE_EVAL"


def test_a_raiz_do_repositorio_tem_um_nome_so() -> None:
    r"""Ninguém volta a escrever `Path(__file__).resolve().parent` quatro vezes.

    A expressão está certa dentro de um clone e silenciosamente errada dentro de
    um `site-packages`: os mesmos quatro saltos caem na raiz do ambiente. Estava
    copiada em quatro módulos (`mcp/server.py`, `mcp/registrar.py`,
    `index/retomada.py`, `painel/medir.py`); hoje é `repositorio.raiz()`, e
    `repositorio.em_checkout()` é a pergunta que separa os dois casos.
    """
    from segundocerebro import repositorio

    assert repositorio.raiz() == REPO
    assert repositorio.em_checkout(), "a suíte roda de dentro do clone"

    copias = sorted(
        arquivo.relative_to(PACOTE).as_posix()
        for arquivo in PACOTE.rglob("*.py")
        if arquivo.name != "repositorio.py"
        and "parent.parent.parent" in arquivo.read_text(encoding="utf-8")
    )
    assert not copias, f"raiz do repositório deduzida à mão em {copias} — usar `repositorio.raiz()`"
