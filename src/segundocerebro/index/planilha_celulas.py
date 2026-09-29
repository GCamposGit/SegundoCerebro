"""Persist compact parsed rows as queryable cells outside the vector index."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..ingest.document import LinhaPlanilha
from ..ingest.parsers.planilha_captura import coluna_excel

if TYPE_CHECKING:
    from .store import Store


def persistir_linhas(
    store: Store, sha256: str, linhas: Sequence[LinhaPlanilha]
) -> int:
    """Replace cell rows for a content hash, keeping them out of chunks/vectors."""
    if not sha256 or not linhas:
        return 0

    store.con.execute("DELETE FROM planilha_celulas WHERE sha256 = ?", (sha256,))
    registros = (
        (sha256, linha.aba, linha.linha, coluna_excel(indice), valor)
        for linha in linhas
        for indice, valor in enumerate(linha.valores, start=1)
        if valor
    )
    cursor = store.con.executemany(
        "INSERT INTO planilha_celulas (sha256, aba, linha, coluna, valor) VALUES (?,?,?,?,?)",
        registros,
    )
    return cursor.rowcount
