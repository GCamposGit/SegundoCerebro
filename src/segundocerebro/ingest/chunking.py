"""Turn parsed blocks into chunks. Deterministic code — no model involved.

Three rules, in this order:

1. A block that fits the limit **is** the chunk. Nothing is cut. The parsers
   already segmented by real structure (Word heading, slide, PDF section), and
   that structure beats any size-based split.
2. A block over the limit is split with overlap, and the heading trail is
   repeated in every piece — a fragment that lost its heading is a fragment
   nobody can rank.
3. Adjacent small blocks under the same heading trail are merged up to the
   limit, so a document does not turn into a hundred one-line chunks.

Determinism is a requirement, not a preference: the ids have to be stable
across runs, or the eval cannot compare a measurement taken before a change
with one taken after. That is also why no LLM decides where to cut.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .document import Block, BlockKind, ParsedDoc

# Bump when the chunking rules change: every id changes with it, on purpose,
# because a chunk produced by different rules is a different chunk.
CHUNKER_VERSION = "2"
"""v2: the document file name joined the embedded text.

Measured cause: the F0 baseline reaches recall@1 = 0,55 reading **only** file
names, while the first content index reached 0,26. The file name is the
strongest single feature in this corpus — folders are organised and names are
descriptive (`Contrato NN-ACME-450.2025 - Acme Holding.docx`) — and the first
version of the chunker threw it away, embedding only heading trail plus text.
"""


@dataclass(frozen=True)
class ChunkConfig:
    max_tokens: int | None = None
    """Hard budget in tokens of the active encoder. When set, no chunk is ever
    handed to the model above it.

    Characters were only ever a proxy: 4,49 chars/token measured in Portuguese
    means 1800 chars is *usually* under 512 tokens, and sometimes not. Worse, a
    spreadsheet or table block is never split by the size rule, so it went to
    the encoder whole — averaging 6.655 characters, far past the window, and was
    truncated in silence. Silent truncation makes the index look complete when
    it is not, so the budget has to be enforced with the real tokenizer."""

    contar_tokens: object | None = None
    """Callable[[str], int] — the active model's tokenizer. Absent in unit tests,
    where the character rule is enough and keeps them fast."""

    max_chars: int = 1800
    """Bounded by the encoder's window, not by taste.

    Measured on the real corpus: 4,49 characters per token in Portuguese, so the
    512-token window of the multilingual e5/MiniLM models is ~2298 characters.
    At the previous limit of 2500 the p90 chunk hit exactly 512 tokens — around
    10% were being **silently truncated**, which is the worst failure mode: the
    index looks complete and isn't. 1800 leaves room for the heading trail that
    gets prefixed before embedding."""

    min_chars: int = 250
    """Below this a chunk is merged with the next sibling under the same trail."""

    overlap_chars: int = 200
    """Repeated tail when a block has to be cut, so a sentence split across the
    boundary still appears whole in one of the pieces."""

    never_split: frozenset[BlockKind] = field(
        default_factory=lambda: frozenset({BlockKind.SHEET, BlockKind.TABLE})
    )
    """A spreadsheet window already carries its header, and a table split in
    half loses the alignment between column and value. Both are kept whole even
    when over the limit."""


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_path: str
    ordinal: int
    heading_path: tuple[str, ...]
    text: str
    locator: str = ""
    kind: BlockKind = BlockKind.TEXT

    @property
    def nome_documento(self) -> str:
        """File name without extension, separators turned into spaces.

        `2025.12.08 - Nimbus Tecnologia - Contrato NN-ACME-450.2025.docx` carries
        the supplier, the date and the contract code. Discarding it loses the
        strongest signal this corpus has.
        """
        base = self.doc_path.rsplit("/", 1)[-1]
        base = base.rsplit(".", 1)[0] if "." in base else base
        return " ".join(base.replace("_", " ").split())

    @property
    def embedding_text(self) -> str:
        """What actually gets embedded: file name + heading trail + text."""
        cabecalho = [p for p in (self.nome_documento, *self.heading_path) if p]
        if not cabecalho:
            return self.text
        return " > ".join(cabecalho) + "\n---\n" + self.text

    @property
    def chars(self) -> int:
        return len(self.text)


def chunk_id(doc_path: str, heading_path: Sequence[str], locator: str, ordinal: int) -> str:
    """Stable id: same document and same rules always give the same id.

    Position within the document is part of the identity, so editing one
    section does not renumber the whole document.
    """
    semente = "\x1f".join(
        (CHUNKER_VERSION, doc_path, " > ".join(heading_path), locator, str(ordinal))
    )
    return hashlib.sha1(semente.encode("utf-8")).hexdigest()[:16]


def _cortar(texto: str, cfg: ChunkConfig) -> list[str]:
    """Split a long text at paragraph, then sentence, then hard boundary."""
    if len(texto) <= cfg.max_chars:
        return [texto]

    pedacos: list[str] = []
    restante = texto
    while len(restante) > cfg.max_chars:
        janela = restante[: cfg.max_chars]
        corte = janela.rfind("\n\n")
        if corte < cfg.max_chars // 3:
            corte = janela.rfind("\n")
        if corte < cfg.max_chars // 3:
            corte = max(janela.rfind(". "), janela.rfind("; "), janela.rfind("? "), janela.rfind("! "))
            corte = corte + 1 if corte > 0 else -1
        if corte < cfg.max_chars // 3:
            corte = janela.rfind(" ")
        if corte <= 0:
            corte = cfg.max_chars

        pedacos.append(restante[:corte].strip())
        # o recuo tem que avançar pelo menos um caractere: com limite reduzido e
        # sobreposição grande, `corte - overlap` chegava a zero e o laço nunca
        # terminava — travou a suíte inteira quando o orçamento por tokens passou
        # a reduzir o limite dinamicamente
        recuo = max(1, corte - cfg.overlap_chars)
        restante = restante[recuo:].lstrip()

    if restante.strip():
        pedacos.append(restante.strip())
    return [p for p in pedacos if p]


def _juntar_pequenos(blocos: Sequence[Block], cfg: ChunkConfig) -> list[Block]:
    """Merge consecutive small blocks that share the heading trail and locator."""
    saida: list[Block] = []
    for bloco in blocos:
        if (
            saida
            and len(saida[-1].text) < cfg.min_chars
            and saida[-1].heading_path == bloco.heading_path
            and saida[-1].kind == bloco.kind
            and len(saida[-1].text) + len(bloco.text) <= cfg.max_chars
        ):
            anterior = saida.pop()
            local = anterior.locator or bloco.locator
            if anterior.locator and bloco.locator and anterior.locator != bloco.locator:
                local = f"{anterior.locator}–{bloco.locator}"
            saida.append(
                Block(
                    heading_path=anterior.heading_path,
                    text=f"{anterior.text}\n{bloco.text}".strip(),
                    locator=local,
                    kind=anterior.kind,
                )
            )
        else:
            saida.append(bloco)
    return saida


def _nome_de(doc_path: str) -> str:
    base = doc_path.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0] if "." in base else base
    return " ".join(base.replace("_", " ").split())


MIN_CHARS_DE_CORTE = 200
"""Piso do aperto progressivo no corte por caractere. Abaixo disso o pedaço deixa
de ser passagem e vira fragmento sem contexto suficiente para responder nada."""


def _prefixo_contextual(doc_path: str, heading_path: Sequence[str]) -> str:
    partes = [p for p in (_nome_de(doc_path), *heading_path) if p]
    return " > ".join(partes) + "\n---\n" if partes else ""


def _cortar_por_caractere(pedaco: str, prefixo: str, cfg: ChunkConfig) -> list[str]:
    """Último recurso: corta por caractere, apertando o limite até caber."""
    contar = cfg.contar_tokens
    limite = cfg.max_chars
    while limite > MIN_CHARS_DE_CORTE and contar(prefixo + pedaco[:limite]) > cfg.max_tokens:
        limite = int(limite * 0.8)
    return _cortar(
        pedaco,
        ChunkConfig(max_chars=limite, overlap_chars=min(cfg.overlap_chars, limite // 4)),
    )


def _cortar_por_linha(texto: str, prefixo: str, cfg: ChunkConfig) -> list[str]:
    """Split a table or sheet block by rows, repeating the header row.

    A table cut in the middle loses the alignment between column and value, so
    the header goes into every piece — the same reason a spreadsheet window
    repeats its header.

    O cabeçalho repetido tem um custo que a versão anterior não pagava: quando
    uma linha sozinha, **com** o cabeçalho, já passa do orçamento, não há
    agrupamento possível. Antes o pedaço era emitido assim mesmo e estourava a
    janela — medido em 13/08/2026, 365 chunks acima do orçamento numa planilha só,
    o maior com 4.386 tokens para um limite de 488. Agora cai para corte por
    caractere, que sempre cabe.
    """
    contar = cfg.contar_tokens
    linhas = texto.split("\n")
    cabecalho = linhas[0] if len(linhas) > 1 else ""
    corpo = linhas[1:] if cabecalho else linhas

    def montar(grupo: list[str]) -> str:
        return "\n".join([cabecalho, *grupo]) if cabecalho else "\n".join(grupo)

    def cabe(pedaco: str) -> bool:
        return contar(prefixo + pedaco) <= cfg.max_tokens

    pedacos: list[str] = []
    atual: list[str] = []
    for linha in corpo:
        if atual and not cabe(montar([*atual, linha])):
            pedacos.append(montar(atual))
            atual = [linha]
        else:
            atual.append(linha)

        if len(atual) == 1 and not cabe(montar(atual)):
            pedacos.extend(_cortar_por_caractere(montar(atual), prefixo, cfg))
            atual = []

    if atual:
        pedacos.append(montar(atual))
    return [p for p in pedacos if p.strip()]


def _respeitar_orcamento(pedacos: list[str], prefixo: str, kind: BlockKind, cfg: ChunkConfig) -> list[str]:
    """Guarantee no piece exceeds the encoder window. Never truncates."""
    contar = cfg.contar_tokens
    if cfg.max_tokens is None or contar is None:
        return pedacos

    saida: list[str] = []
    for pedaco in pedacos:
        if contar(prefixo + pedaco) <= cfg.max_tokens:
            saida.append(pedaco)
            continue
        if kind in cfg.never_split or "\n" in pedaco:
            saida.extend(_cortar_por_linha(pedaco, prefixo, cfg))
        else:
            saida.extend(_cortar_por_caractere(pedaco, prefixo, cfg))
    return saida


def chunk_document(doc: ParsedDoc, doc_path: str, cfg: ChunkConfig | None = None) -> list[Chunk]:
    """Blocks in, chunks out. Same input always gives the same output."""
    cfg = cfg or ChunkConfig()
    chunks: list[Chunk] = []
    ordinal = 0

    for bloco in _juntar_pequenos(doc.blocks, cfg):
        texto = bloco.text.strip()
        if not texto:
            continue

        if bloco.kind in cfg.never_split or len(texto) <= cfg.max_chars:
            pedacos = [texto]
        else:
            pedacos = _cortar(texto, cfg)

        prefixo = _prefixo_contextual(doc_path, bloco.heading_path)
        pedacos = _respeitar_orcamento(pedacos, prefixo, bloco.kind, cfg)

        total = len(pedacos)
        for i, pedaco in enumerate(pedacos, start=1):
            local = bloco.locator
            if total > 1:
                local = f"{local} ({i}/{total})" if local else f"parte {i}/{total}"
            chunks.append(
                Chunk(
                    id=chunk_id(doc_path, bloco.heading_path, local, ordinal),
                    doc_path=doc_path,
                    ordinal=ordinal,
                    heading_path=bloco.heading_path,
                    text=pedaco,
                    locator=local,
                    kind=bloco.kind,
                )
            )
            ordinal += 1

    return chunks


def estatisticas(chunks: Iterable[Chunk]) -> dict[str, float]:
    tamanhos = [c.chars for c in chunks]
    if not tamanhos:
        return {"chunks": 0, "chars": 0, "media": 0.0, "maior": 0, "menor": 0}
    return {
        "chunks": len(tamanhos),
        "chars": sum(tamanhos),
        "media": sum(tamanhos) / len(tamanhos),
        "maior": max(tamanhos),
        "menor": min(tamanhos),
    }
