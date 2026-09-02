"""Wikilinks derivados das menções e do glossário — rendering da view `J.e`.

Não inventa aresta: materializa no Markdown o que a tabela `mencoes` e o
glossário da base já sabem. O grafo do Obsidian sai de graça; nada disso
volta para o acervo nem para o índice.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from ..retrieve.grafo import MAX_DOCUMENTOS_POR_ID
from ..retrieve.identificadores import FIM, INICIO
from ..retrieve.glossario import Glossario

PASTA_GRAFO = "_grafo"
NOTA_GLOSSARIO = "glossario.md"

_PROTEGIDO = re.compile(r"(```.*?```|`[^`]*`|\[\[[^\]]+\]\])", re.DOTALL)
_RESERVADOS = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
})


def nome_de_arquivo(valor: str) -> str:
    """Nome de nota Obsidian estável a partir de um identificador ou sigla."""
    proibidos = '<>:"/\\|?*'
    nome = "".join("_" if c in proibidos else c for c in valor.strip())
    nome = nome.strip(" .") or "identificador"
    if nome.upper() in _RESERVADOS:
        nome = f"_{nome}"
    return nome


def caminho_do_hub(valor: str) -> str:
    return f"{PASTA_GRAFO}/{nome_de_arquivo(valor)}.md"


def wikilink(alvo: str, texto: str) -> str:
    """`[[alvo]]` só quando o texto já é o destino; senão `[[alvo|texto]]`."""
    destino = alvo.removesuffix(".md")
    if texto == destino:
        return f"[[{destino}]]"
    return f"[[{destino}|{texto}]]"


def por_identificador(
    mencoes: Mapping[str, Sequence[tuple[str, str]]],
    teto: int = MAX_DOCUMENTOS_POR_ID,
) -> dict[tuple[str, str], list[str]]:
    """Identificador → caminhos do vault que o citam, só os que formam aresta."""
    agrupado: dict[tuple[str, str], list[str]] = {}
    for caminho, pares in mencoes.items():
        for tipo, valor in pares:
            agrupado.setdefault((tipo, valor), []).append(caminho)
    return {
        chave: sorted(set(caminhos))
        for chave, caminhos in agrupado.items()
        if 2 <= len(set(caminhos)) <= teto
    }


def nota_do_hub(tipo: str, valor: str, alvos: Sequence[str]) -> str:
    """Nota-índice do identificador: só lista as notas do vault, sem síntese."""
    linhas = [
        "---",
        f"tipo: {tipo}",
        f"valor: {_yaml_simples(valor)}",
        "view: one-way",
        "---",
        "",
        f"# {valor}",
        "",
        "Notas deste vault que citam o identificador:",
        "",
    ]
    for alvo in alvos:
        linhas.append(f"- {wikilink(alvo, alvo.rsplit('/', 1)[-1].removesuffix('.md'))}")
    linhas.append("")
    return "\n".join(linhas)


def aplicar(
    markdown: str,
    caminho: str,
    mapa: Mapping[tuple[str, str], Sequence[str]],
    mencoes_do_doc: Sequence[tuple[str, str]],
    siglas: Sequence[tuple[str, str]] = (),
) -> str:
    """Envolve no corpo só o que tem aresta no vault; não toca code fence."""
    pares: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for tipo, valor in mencoes_do_doc:
        membros = mapa.get((tipo, valor)) or ()
        if caminho not in membros or valor in vistos:
            continue
        vistos.add(valor)
        pares.append((valor, wikilink(caminho_do_hub(valor), valor)))
    pares.extend(siglas)
    pares.sort(key=lambda p: len(p[0]), reverse=True)
    return _proteger_e_trocar(markdown, pares)


def markup_de_siglas(markdown: str, glossario: Glossario) -> list[tuple[str, str]]:
    """Siglas do glossário que de fato aparecem neste Markdown, com o wikilink."""
    if not glossario:
        return []
    saida: list[tuple[str, str]] = []
    for sigla in glossario.termos:
        if len(sigla) < 2:
            continue
        padrao = re.compile(INICIO + re.escape(sigla) + FIM)
        if padrao.search(markdown):
            ancora = nome_de_arquivo(sigla)
            saida.append((sigla, f"[[glossario#{ancora}|{sigla}]]"))
    return saida


def nota_do_glossario(
    glossario: Glossario,
    ocorrencias: Mapping[str, Sequence[str]],
) -> str | None:
    """Uma nota com as siglas da base e as notas do vault que as citam."""
    if not glossario:
        return None
    linhas = ["---", "view: one-way", "---", "", "# Glossário", ""]
    for sigla, formas in sorted(glossario.termos.items(), key=lambda kv: kv[0].lower()):
        linhas.append(f"## {nome_de_arquivo(sigla)}")
        linhas.append("")
        linhas.append(f"{sigla}: {'; '.join(formas)}")
        linhas.append("")
        for alvo in ocorrencias.get(sigla, ()):
            linhas.append(f"- {wikilink(alvo, alvo.rsplit('/', 1)[-1].removesuffix('.md'))}")
        if ocorrencias.get(sigla):
            linhas.append("")
    linhas.append("")
    return "\n".join(linhas)


def _proteger_e_trocar(texto: str, pares: Sequence[tuple[str, str]]) -> str:
    """Uma substituição por vez, para o wikilink recém-inserido não ser recasado."""
    if not texto or not pares:
        return texto
    for valor, markup in pares:
        if valor:
            texto = _uma_passada(texto, valor, markup)
    return texto


def _uma_passada(texto: str, valor: str, markup: str) -> str:
    partes: list[str] = []
    pos = 0
    padrao = re.compile(INICIO + re.escape(valor) + FIM)
    for bloco in _PROTEGIDO.finditer(texto):
        partes.append(padrao.sub(markup, texto[pos:bloco.start()]))
        partes.append(bloco.group(0))
        pos = bloco.end()
    partes.append(padrao.sub(markup, texto[pos:]))
    return "".join(partes)


def _yaml_simples(valor: str) -> str:
    if any(c in valor for c in ":#\n") or not valor:
        import json
        return json.dumps(valor, ensure_ascii=False)
    return valor
