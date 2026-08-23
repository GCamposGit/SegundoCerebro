"""The shape every parser produces, regardless of the source format.

One normalized representation is what lets chunking, embedding and the MCP
surface stay ignorant of whether a passage came from a PDF page, a slide or a
spreadsheet range. Two fields carry the weight:

- `heading_path` — the trail of headings above the block. It becomes the
  contextual header prefixed to the text before embedding, which is the single
  cheapest precision gain available (see ARCHITECTURE.md §3).
- `locator` — where a human finds it again: "p. 12", "slide 4",
  "Orçamento!A1:F40". Provenance is an invariant of the project, not a nicety.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .natureza import Natureza


class BlockKind(str, Enum):
    TEXT = "texto"
    TABLE = "tabela"
    SLIDE_NOTES = "notas"
    SHEET = "planilha"


@dataclass(frozen=True)
class Block:
    """A passage with its position in the document's structure."""

    heading_path: tuple[str, ...]
    text: str
    locator: str = ""
    kind: BlockKind = BlockKind.TEXT

    @property
    def contextual_text(self) -> str:
        """Text with the heading trail prefixed — what actually gets embedded."""
        if not self.heading_path:
            return self.text
        return " > ".join(self.heading_path) + "\n---\n" + self.text


@dataclass(frozen=True)
class ParsedDoc:
    name: str
    blocks: tuple[Block, ...] = ()
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def total_chars(self) -> int:
        return sum(len(b.text) for b in self.blocks)


class ParseStatus(str, Enum):
    """Why a document did or did not yield text.

    Every non-OK status is recorded rather than swallowed: a corpus where 8%
    of the files quietly failed looks exactly like a corpus where the ranking
    is bad, and the two demand opposite fixes.
    """

    OK = "ok"
    EMPTY = "vazio"  # opened fine, no extractable text (scanned PDF, image deck)
    LOCKED = "travado"  # open in Word/Excel — retry on the next pass
    CLOUD_ONLY = "placeholder"  # content not on disk; reading would download it
    UNSUPPORTED = "sem_parser"
    ERROR = "erro"
    GONE = "sumiu"
    """O arquivo foi enumerado e não existia mais na hora de abrir.

    Separado de `erro` em 15/08/2026, depois do checkpoint do run completo: 10 de
    18 "erros" eram revisões de planilha apagadas entre a varredura e o
    processamento — a pasta continuava lá, os arquivos não. Num corpus que é
    pasta de trabalho viva isso não é exceção, e enquanto tudo caía em `erro` o
    contador misturava "reconciliar" com "consertar o parser", que pedem coisas
    opostas. Oito erros de verdade estavam enterrados sob dez desaparecimentos.

    Não é repescado: a próxima varredura simplesmente não enumera o arquivo. Quem
    tira o registro do índice é a reconciliação, e é lá que a decisão mora —
    apagar na primeira ausência confundiria queda de rede com exclusão."""
    DEFERRED = "adiado"
    """Caro demais para esta passada, por um limite explícito.

    Não é falha: é "esta planilha de 69 abas" ou "este .csv de 68 MB" custando
    horas, e a passada de hoje quer terminar. Fica registrado com o motivo e é
    repescado na primeira passada que rodar sem o limite — nunca vira documento
    esquecido, que é o que aconteceria movendo o arquivo para uma pasta de fora."""


@dataclass(frozen=True)
class ParseResult:
    path: str
    status: ParseStatus
    doc: ParsedDoc | None = None
    detail: str = ""
    sha256: str = ""
    """Content hash, when the bytes were actually read. Empty for a document
    refused before opening (placeholder) or with no parser — those never had
    content to hash."""

    natureza: "Natureza | None" = None
    """Sinais determinísticos sobre o arquivo, quando os bytes foram lidos.

    Vem junto com o resultado — e não como passada separada — porque calcular
    depois exigiria abrir o arquivo de novo, e abrir de novo é o que o portão de
    leitura existe para evitar."""

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK
