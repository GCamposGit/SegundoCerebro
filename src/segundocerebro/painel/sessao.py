"""Sessão do painel — porta, token e o arquivo que religa a mesma URL.

Saiu de `app.py` em 02/09/2026, costura do `Q16`: `__main__.py` já importava
este conjunto, e a rota de exportar o vault precisava entrar sem o módulo
passar do teto. Docstrings de decisão movem verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PORTA_PADRAO = 18787
"""Porta fixa para o atalho do Windows reabrir a mesma URL.

0 (livre) fazia cada abertura nascer noutro endereço, e o usuário não tinha
como voltar à tela sem perguntar ao agente."""

SESSAO_PAINEL = ".painel.json"


def caminho_da_sessao(config: Path) -> Path:
    return Path(config).expanduser().resolve().parent / SESSAO_PAINEL


def ler_sessao(config: Path) -> dict[str, Any] | None:
    alvo = caminho_da_sessao(config)
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    porta, token = dados.get("porta"), dados.get("token")
    if not isinstance(porta, int) or not isinstance(token, str) or not token:
        return None
    return {"porta": porta, "token": token, "url": dados.get("url") or f"http://127.0.0.1:{porta}/?token={token}"}


def gravar_sessao(config: Path, porta: int, token: str) -> None:
    alvo = caminho_da_sessao(config)
    payload = {
        "porta": porta,
        "token": token,
        "url": f"http://127.0.0.1:{porta}/?token={token}",
    }
    tmp = alvo.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(alvo)


def painel_responde(porta: int, token: str, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """True se já há um painel vivo nesta porta com este token."""
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    pedido = Request(
        f"http://{host}:{porta}/api/estado",
        headers={"x-painel-token": token},
        method="GET",
    )
    try:
        with urlopen(pedido, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (URLError, TimeoutError, OSError):
        return False
