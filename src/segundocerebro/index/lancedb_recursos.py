"""Fechamento explícito dos recursos síncronos do LanceDB."""

from __future__ import annotations


def fechar_recursos(tabela: object, db: object) -> None:
    """Fecha tabela e conexão assíncrona sem depender de coleta de lixo."""
    for recurso in (tabela, getattr(db, "_conn", None)):
        fechar = getattr(recurso, "close", None)
        if callable(fechar):
            fechar()
