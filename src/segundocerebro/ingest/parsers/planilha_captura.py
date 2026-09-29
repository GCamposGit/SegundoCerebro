"""Compact side channel for exact reads from sheets reduced to a digest."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence

from ..document import Block, LinhaPlanilha


class BlocosPlanilha(list[Block]):
    """Mutable parser output with rows kept outside the embedding blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.linhas_planilha: list[LinhaPlanilha] = []


def coluna_excel(indice: int) -> str:
    """Convert one-based column numbers to Excel names (1 -> A, 27 -> AA)."""
    nome = ""
    while indice > 0:
        indice, resto = divmod(indice - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


def _reter(
    aba: str, linha: int, valores: Sequence[str], blocos: list[Block]
) -> None:
    if isinstance(blocos, BlocosPlanilha) and any(valores):
        blocos.linhas_planilha.append(LinhaPlanilha(aba, linha, tuple(valores)))


def linhas_numeradas(
    aba: str, linhas: Iterable[tuple[int, list[str]]], blocos: list[Block]
) -> Iterator[list[str]]:
    """Retain original worksheet row numbers while yielding rows to the digest."""
    for numero, valores in linhas:
        _reter(aba, numero, valores, blocos)
        yield valores


def linhas_sequenciais(
    aba: str, linhas: Iterable[list[str]], blocos: list[Block]
) -> Iterator[list[str]]:
    """Retain one-based row numbers from a sequential worksheet scan."""
    for numero, valores in enumerate(linhas, start=1):
        _reter(aba, numero, valores, blocos)
        yield valores
