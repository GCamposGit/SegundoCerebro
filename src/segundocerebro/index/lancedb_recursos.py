"""Fechamento explícito dos recursos síncronos do LanceDB."""

from __future__ import annotations


def fechar_recursos(tabela: object, db: object) -> None:
    """Fecha tabela e conexão assíncrona sem depender de coleta de lixo."""
    for recurso in (tabela, getattr(db, "_conn", None)):
        fechar_lsm = getattr(recurso, "close_lsm_writers", None)
        if callable(fechar_lsm):
            fechar_lsm()
        fechar = getattr(recurso, "close", None)
        if callable(fechar):
            fechar()


def fechar_store(conexao: object, tabela: object, db: object) -> None:
    """Fecha SQLite e LanceDB mesmo quando uma etapa de fechamento falha."""
    try:
        commit = getattr(conexao, "commit")
        commit()
    finally:
        try:
            fechar = getattr(conexao, "close")
            fechar()
        finally:
            fechar_recursos(tabela, db)
