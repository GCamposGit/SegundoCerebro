"""Retrieval metrics. Pure functions, no I/O, no corpus — trivially testable.

Every question in the golden set carries one or more expected sources. Two
situations need different accounting, so `modo` picks the rule:

- `qualquer` — the listed sources are interchangeable (the same document in two
  folders, or in .docx and .pdf). Finding one of them is a complete success.
- `todas` — the question genuinely needs every source (multi-hop: the decision
  is in one file, the price in another). Partial credit is proportional.

`modo` only changes recall. MRR and nDCG treat every listed source as relevant
in both cases, which is what they mean: a relevant document ranked high is good
regardless of why it was listed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import log2

MODO_QUALQUER = "qualquer"
MODO_TODAS = "todas"
MODOS = (MODO_QUALQUER, MODO_TODAS)


def _sem_repetidos(ranked: Sequence[str]) -> list[str]:
    """Keep first occurrence only — a duplicate must not be counted twice."""
    vistos: set[str] = set()
    saida: list[str] = []
    for p in ranked:
        if p not in vistos:
            vistos.add(p)
            saida.append(p)
    return saida


def recall_at_k(ranked: Sequence[str], relevantes: Iterable[str], k: int, modo: str = MODO_QUALQUER) -> float:
    """Fraction of the expected sources found in the top k."""
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo}")
    esperados = set(relevantes)
    if not esperados or k <= 0:
        return 0.0
    encontrados = len(set(_sem_repetidos(ranked)[:k]) & esperados)
    if modo == MODO_TODAS:
        return encontrados / len(esperados)
    return 1.0 if encontrados else 0.0


def reciprocal_rank(ranked: Sequence[str], relevantes: Iterable[str], k: int | None = None) -> float:
    """1/posição do primeiro acerto; 0 se nenhum acerto entra no corte."""
    esperados = set(relevantes)
    for i, p in enumerate(_sem_repetidos(ranked), start=1):
        if k is not None and i > k:
            break
        if p in esperados:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevantes: Iterable[str], k: int) -> float:
    """nDCG with binary gain: rewards relevant documents ranked higher."""
    esperados = set(relevantes)
    if not esperados or k <= 0:
        return 0.0
    topo = _sem_repetidos(ranked)[:k]
    dcg = sum(1.0 / log2(i + 2) for i, p in enumerate(topo) if p in esperados)
    idcg = sum(1.0 / log2(i + 2) for i in range(min(len(esperados), k)))
    return dcg / idcg if idcg else 0.0


def media(valores: Iterable[float]) -> float:
    vals = list(valores)
    return sum(vals) / len(vals) if vals else 0.0
