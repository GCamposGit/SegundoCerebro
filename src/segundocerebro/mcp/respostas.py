# pyright: reportReturnType=error, reportArgumentType=error
"""Padronização de respostas e protocolo de erros MCP (FND-07).

Garante CallToolResult(is_error=True) quando houver exceções operacionais reais
(parâmetros ilegais, pasta inexistente, cursor expirado, ID ausente), enquanto
consultas sem correspondência permanecem como respostas normais de sucesso (is_error=False).

FND-10: first public frontier with reportReturnType/reportArgumentType on via
the file comment above. Global pyright keeps those reports off.
"""

from __future__ import annotations

import json
from collections.abc import ItemsView, KeysView, ValuesView
from typing import Any

from mcp.types import CallToolResult, TextContent


class ResultadoTool(CallToolResult):
    """CallToolResult compatível com o wire MCP e acessível como dict para clientes/testes."""

    def __getitem__(self, item: str) -> Any:
        if self.structured_content is not None and item in self.structured_content:
            return self.structured_content[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        if self.structured_content is not None and item in self.structured_content:
            return self.structured_content[item]
        return default

    def __contains__(self, item: object) -> bool:
        return bool(self.structured_content is not None and item in self.structured_content)

    def keys(self) -> KeysView[str]:
        if self.structured_content is not None and isinstance(self.structured_content, dict):
            return self.structured_content.keys()
        return {}.keys()

    def values(self) -> ValuesView[Any]:
        if self.structured_content is not None and isinstance(self.structured_content, dict):
            return self.structured_content.values()
        return {}.values()

    def items(self) -> ItemsView[str, Any]:
        if self.structured_content is not None and isinstance(self.structured_content, dict):
            return self.structured_content.items()
        return {}.items()


def sucesso(payload: dict[str, Any]) -> ResultadoTool:
    """Encapsula resultado com sucesso operacional (is_error=False)."""
    return ResultadoTool(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=False,
    )


def erro_operacional(
    mensagem: str,
    codigo: str,
    dados_extras: dict[str, Any] | None = None,
) -> ResultadoTool:
    """Encapsula erro operacional real com is_error=True e formato padronizado."""
    payload: dict[str, Any] = {
        "erro": mensagem,
        "codigo": codigo,
    }
    if dados_extras:
        payload.update(dados_extras)
    return ResultadoTool(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )
