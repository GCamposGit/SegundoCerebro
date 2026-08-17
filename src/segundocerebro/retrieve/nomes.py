"""Scoring by file name and folder path.

This is the strongest single signal in this corpus, and the measurement says so:
the F0 baseline reads **only** names and paths and reaches recall@1 = 0,549,
while BM25 over chunk text plus path reaches 0,431. BM25 normalises by document
length, so a 60-character file name drowns in 1.800 characters of body text —
putting the path inside the text index is not the same as ranking by it.

So the name becomes its own ranker, fused with the others. Same code that powers
the F0 baseline lives here, on purpose: if the baseline and the ranker scored
differently, comparing them would measure the difference between two scorers
instead of the value of the signal.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Interrogativos e artigos não carregam sinal de recuperação aqui.
PALAVRAS_VAZIAS = frozenset(
    """
    a as o os um uma uns umas de do da dos das em no na nos nas ao aos e ou que qual quais quanto
    quanta quantos quantas como onde quando por para com sem sobre entre foi ser sao e_ tem teve
    ha havia esta estao qual_ the of in on for to and is are what which how many much where when
    nosso nossa nossos nossas meu minha seu sua algum alguma algo isso este esta esse essa aquele
    faco fazer usar chamar ter pode devem deve
    """.split()
)

TOKEN = re.compile(r"[0-9a-z]+")
PESO_NOME = 2.0
PESO_PASTA = 1.0


def normalizar(texto: str) -> str:
    """Lowercase and strip accents — 'Inteligência' and 'inteligencia' must match."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    return [t for t in TOKEN.findall(normalizar(texto)) if len(t) > 1 and t not in PALAVRAS_VAZIAS]


@dataclass(frozen=True)
class DocumentoIndexado:
    rel: str
    tokens_nome: frozenset[str]
    tokens_pastas: frozenset[str]

    @classmethod
    def de_caminho(cls, rel: str) -> "DocumentoIndexado":
        partes = rel.split("/")
        nome = frozenset(tokenizar(partes[-1]))
        return cls(
            rel=rel,
            tokens_nome=nome,
            tokens_pastas=frozenset(tokenizar(" ".join(partes[:-1]))) - nome,
        )


def indexar_caminhos(caminhos: Iterable[str]) -> list[DocumentoIndexado]:
    return [DocumentoIndexado.de_caminho(c) for c in caminhos]


def pontuar(documentos: Sequence[DocumentoIndexado], consulta: str) -> list[tuple[str, float]]:
    """Rank document paths by token overlap. Name counts double; folders once."""
    termos = set(tokenizar(consulta))
    if not termos:
        return []

    pontuados: list[tuple[float, int, str]] = []
    for doc in documentos:
        no_nome = len(termos & doc.tokens_nome)
        nas_pastas = len(termos & doc.tokens_pastas)
        if not (no_nome or nas_pastas):
            continue
        score = PESO_NOME * no_nome + PESO_PASTA * nas_pastas
        # Caminho curto vence empate: um acerto em "Contratos/x.pdf" é mais
        # específico que o mesmo acerto dez pastas abaixo.
        pontuados.append((-score, len(doc.rel), doc.rel))

    pontuados.sort()
    return [(rel, -neg) for neg, _, rel in pontuados]


class RanqueadorDeNome:
    """Document-level ranker over paths. No content, no model, no index."""

    nome = "nome de arquivo"

    def __init__(self, caminhos: Iterable[str]) -> None:
        self.documentos = indexar_caminhos(caminhos)

    def ranquear(self, consulta: str, k: int) -> list[tuple[str, float]]:
        return pontuar(self.documentos, consulta)[:k]
