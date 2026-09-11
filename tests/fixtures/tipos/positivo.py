"""Valid use of the MCP result envelope — pyright must accept this file."""

from __future__ import annotations

from segundocerebro.mcp.respostas import erro_operacional, sucesso

ok = sucesso({"hits": []})
err = erro_operacional("documento ausente", "ausente", {"acao": "reiniciar"})
assert ok.is_error is False
assert err.is_error is True
