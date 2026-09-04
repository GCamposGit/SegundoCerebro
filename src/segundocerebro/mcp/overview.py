"""Ferramenta MCP de panorama e orientação (`overview`) — R7.1."""

from __future__ import annotations

from typing import Any

from ..acesso.overview import resumo_base

DESCRICAO_OVERVIEW = (
    "Panorama estatístico da base de conhecimento: total de documentos e trechos indexados, "
    "período coberto (datas mais antiga e mais recente), formatos mais comuns, pastas "
    "principais, taxa de sucesso da indexação e documentos digitalizados pendentes de OCR. "
    "Use no início de uma sessão para orientar o plano de busca ou leitura da base."
)


def registrar(servidor: Any, recursos: Any) -> None:
    """Registra a ferramenta overview no servidor MCP."""
    base = getattr(recursos, "base", None)
    base_id = getattr(base, "id", "") or ""

    @servidor.tool(description=DESCRICAO_OVERVIEW)
    def overview() -> dict[str, Any]:
        """Devolve panorama estatístico estruturado da base de conhecimento."""
        return resumo_base(recursos.store, base_id=base_id)
