"""Plain text and Markdown — the simplest parser, and the one PDF reuses.

Markdown gives us real structure for free: `#` levels are exactly the heading
trail every other parser has to reconstruct. PyMuPDF converts PDF to Markdown,
so this module ends up doing the structural work for the largest format in the
corpus too.
"""

from __future__ import annotations

import re

from ..document import Block, BlockKind, ParsedDoc
from . import register

CODIFICACOES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

CABECALHO = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
CERCA = re.compile(r"^\s*(```|~~~)")
# Markdown "setext": título sublinhado por === ou ---
SUBLINHADO = re.compile(r"^\s*(=+|-{3,})\s*$")


def decode(dados: bytes) -> str:
    """Decode with the encodings a Windows corpus actually contains."""
    for codec in CODIFICACOES:
        try:
            return dados.decode(codec)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", errors="replace")


def _trilha(pilha: list[tuple[int, str]]) -> tuple[str, ...]:
    return tuple(titulo for _, titulo in pilha)


def blocos_de_markdown(
    texto: str,
    locator: str = "",
    pilha: list[tuple[int, str]] | None = None,
    fallback_titulo: bool = True,
) -> list[Block]:
    """Split Markdown by heading, keeping the heading trail for each section.

    `pilha` is mutated in place when given, so a caller can thread the heading
    trail across several calls — which is how the PDF parser keeps the section
    title from page 3 attached to the text that continues on page 4.
    """
    blocos: list[Block] = []
    if pilha is None:
        pilha = []
    corpo: list[str] = []
    dentro_de_cerca = False

    def fechar() -> None:
        conteudo = "\n".join(corpo).strip()
        if conteudo:
            blocos.append(Block(heading_path=_trilha(pilha), text=conteudo, locator=locator))
        corpo.clear()

    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if CERCA.match(linha):
            dentro_de_cerca = not dentro_de_cerca
            corpo.append(linha)
            continue
        if dentro_de_cerca:
            corpo.append(linha)
            continue

        m = CABECALHO.match(linha)
        if not m and corpo and SUBLINHADO.match(linha) and corpo[-1].strip():
            # setext: o título é a linha anterior, que já entrou no corpo
            titulo = corpo.pop().strip()
            nivel = 1 if linha.strip().startswith("=") else 2
            fechar()
            while pilha and pilha[-1][0] >= nivel:
                pilha.pop()
            pilha.append((nivel, titulo))
            continue

        if m:
            fechar()
            nivel = len(m.group(1))
            titulo = m.group(2).strip()
            while pilha and pilha[-1][0] >= nivel:
                pilha.pop()
            pilha.append((nivel, titulo))
            continue

        corpo.append(linha)

    fechar()

    # Um documento só de títulos ainda carrega informação: o próprio título.
    # Não vale quando a pilha vem de fora (página seguinte de um PDF), senão o
    # título da página anterior seria emitido de novo como se fosse conteúdo.
    if fallback_titulo and not blocos and pilha:
        blocos.append(Block(heading_path=_trilha(pilha[:-1]), text=pilha[-1][1], locator=locator))
    return blocos


@register(".md", ".markdown")
def parse_markdown(dados: bytes, nome: str) -> ParsedDoc:
    return ParsedDoc(name=nome, blocks=tuple(blocos_de_markdown(decode(dados))), meta={"formato": "markdown"})


@register(".txt", ".csv")
def parse_texto(dados: bytes, nome: str) -> ParsedDoc:
    conteudo = decode(dados).strip()
    if not conteudo:
        return ParsedDoc(name=nome, meta={"formato": "texto"})
    bloco = Block(heading_path=(), text=conteudo, kind=BlockKind.TEXT)
    return ParsedDoc(name=nome, blocks=(bloco,), meta={"formato": "texto"})
