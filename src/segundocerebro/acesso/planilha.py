"""Consultas limitadas às células de planilhas já estruturadas no índice."""

from __future__ import annotations

from dataclasses import dataclass

from ..index.store import Store


@dataclass(frozen=True)
class PaginaCelulas:
    total: int
    linhas: tuple[tuple[str, int, str, str], ...]


def contar_celulas(store: Store, sha256: str, aba: str = "") -> int:
    """Conta células persistidas; nunca abre nem interpreta o arquivo original."""
    if aba:
        linha = store.con.execute(
            "SELECT COUNT(*) FROM planilha_celulas WHERE sha256 = ? AND aba = ?",
            (sha256, aba),
        ).fetchone()
    else:
        linha = store.con.execute(
            "SELECT COUNT(*) FROM planilha_celulas WHERE sha256 = ?", (sha256,)
        ).fetchone()
    return int(linha[0])


def ler_pagina_celulas(
    store: Store,
    sha256: str,
    *,
    aba: str = "",
    depois_de: tuple[str, int, str] | None = None,
    limite: int = 200,
) -> PaginaCelulas:
    """Lê no máximo `limite + 1` registros para detectar continuação por chave."""
    total = contar_celulas(store, sha256, aba)
    filtros = ["sha256 = ?"]
    parametros: list[object] = [sha256]
    if aba:
        filtros.append("aba = ?")
        parametros.append(aba)
    if depois_de is not None:
        filtros.append("(aba, linha, coluna) > (?, ?, ?)")
        parametros.extend(depois_de)
    where = " AND ".join(filtros)
    linhas = store.con.execute(
        "SELECT aba, linha, coluna, valor FROM planilha_celulas WHERE "
        f"{where} ORDER BY aba, linha, coluna LIMIT ?",
        (*parametros, limite + 1),
    ).fetchall()
    return PaginaCelulas(
        total=total,
        linhas=tuple(
            (str(linha["aba"]), int(linha["linha"]), str(linha["coluna"]), str(linha["valor"]))
            for linha in linhas
        ),
    )
