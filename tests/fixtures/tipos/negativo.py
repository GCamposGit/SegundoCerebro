"""Deliberate contract break — must NOT live in src. Pyright must reject this."""

from __future__ import annotations

from segundocerebro.mcp.respostas import erro_operacional, sucesso

sucesso("nao-e-mapeamento")


def devolve_int() -> int:
    return erro_operacional("faltou o id", "ausente")
