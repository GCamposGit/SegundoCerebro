"""Ferramenta MCP de panorama e orientação (`overview`) — R7.1."""

from __future__ import annotations

from typing import Any

from mcp.types import CallToolResult

from ..acesso.overview import resumo_base
from .respostas import sucesso

DESCRICAO_OVERVIEW = (
    "Panorama estatístico da base de conhecimento: total de documentos e trechos indexados, "
    "período coberto (datas mais antiga e mais recente), formatos mais comuns, pastas "
    "principais, taxa de sucesso da indexação e documentos digitalizados pendentes de OCR. "
    "Use no início de uma sessão para orientar o plano de busca ou leitura da base. "
    "`status.ok_sem_canonico` conta documentos ok cuja chave atual não acha canônico "
    "no índice. Esse número não autoriza abrir o original."
)


def registrar(servidor: Any, recursos: Any) -> None:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    """Registra a ferramenta overview no servidor MCP."""
    base = getattr(recursos, "base", None)
    base_id = getattr(base, "id", "") or ""

    @servidor.tool(description=DESCRICAO_OVERVIEW)
    def overview() -> CallToolResult:
        """Devolve panorama estatístico estruturado da base de conhecimento."""
        return sucesso(resumo_base(recursos.store, base_id=base_id))

