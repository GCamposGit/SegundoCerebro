"""A documentação versionada não promete arquivo que o clone não tem.

Pacote `Q19`, 30/08/2026. **47 dos 104 arquivos de `docs/` estão versionados.**
Os outros ficam de fora por regra, porque citam nome de arquivo do acervo real —
isso é correto e documentado. A consequência não é: um link em arquivo versionado
apontando para um deles resolve em 404 num clone. É a `F6` aplicada à
documentação — quem clona não vê o que nós vemos, e descobre isso clicando.

A regra que o `Q19` fixou, e que este arquivo passa a conferir sozinho:

> Link para arquivo que o Git não tem vira **menção em texto**, não link.

A distinção importa. Menção em backticks (`` `docs/metricas-f0.md` ``) é honesta:
diz que o documento existe do nosso lado e não promete abri-lo. Link é promessa.
Há 76 menções assim hoje, e nenhuma é defeito.

Este teste não tem nada a ver com `test_saneamento.py`, que confere o **conteúdo**
(nome real do acervo em arquivo versionado). Aqui é a **fronteira**: o que o
clone alcança.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
"""Link markdown com destino relativo. Âncora (`#secao`) descartada de propósito:
o alvo é o arquivo, e conferir âncora exigiria um parser de cabeçalho."""

EXTERNOS = ("http://", "https://", "mailto:", "tel:")


def _versionados() -> set[str]:
    saida = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout
    return {linha for linha in saida.split("\n") if linha}


def _resolver(origem: str, alvo: str) -> str:
    """Destino do link, relativo à raiz do repositório, com `..` colapsado."""
    partes: list[str] = []
    bruto = (Path(origem).parent / alvo).as_posix()
    for parte in bruto.split("/"):
        if parte == "..":
            if partes:
                partes.pop()
        elif parte not in (".", ""):
            partes.append(parte)
    return "/".join(partes)


def _links_de(arquivo: str) -> list[str]:
    texto = (RAIZ / arquivo).read_text(encoding="utf-8")
    return [a for a in LINK.findall(texto) if not a.startswith(EXTERNOS)]


MARKDOWNS = sorted(a for a in _versionados() if a.endswith(".md"))


def test_ha_markdown_versionado_para_conferir():
    """Contra a varredura que passa por não achar arquivo nenhum."""
    assert len(MARKDOWNS) >= 40, f"só {len(MARKDOWNS)} arquivos .md versionados — a lista murchou"


@pytest.mark.parametrize("arquivo", MARKDOWNS, ids=MARKDOWNS)
def test_todo_link_de_arquivo_versionado_existe_no_clone(arquivo):
    """Link para arquivo que o Git não tem é 404 para quem clonou."""
    versionados = _versionados()
    quebrados = []
    for alvo in _links_de(arquivo):
        destino = _resolver(arquivo, alvo)
        if destino in versionados:
            continue
        if any(v == destino or v.startswith(destino + "/") for v in versionados):
            continue  # pasta que o clone tem, porque tem ao menos um arquivo dela
        # `is_dir()` consultava o disco local, não o Git: uma pasta que existe
        # aqui e tem zero arquivos versionados passava verde e dava 404 no clone
        # — a classe do próprio `Q19`, dentro da guarda dele (30/08/2026).
        local = "existe nesta máquina e não no Git" if (RAIZ / destino).exists() else "não existe"
        quebrados.append(f"{alvo} → {destino} ({local})")
    assert not quebrados, (
        f"{arquivo} promete arquivo que o clone não tem:\n  " + "\n  ".join(quebrados) + "\n\n"
        "Link para arquivo local vira menção em texto (`docs/x.md` em backticks), não link — Q19."
    )


def test_a_varredura_de_links_enxerga_algo():
    """Se o regex parar de casar, o teste acima vira teatro verde."""
    total = sum(len(_links_de(a)) for a in MARKDOWNS)
    assert total >= 100, f"a varredura achou só {total} links relativos — ela parou de ver"
