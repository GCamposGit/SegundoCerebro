"""POST /api/salvar com revisão — FND-06.

Não sobrescreve config.toml se outro escritor já gravou a revisão lida.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import ErroDeConfig
from ..config_escrita import ConflitoDeConfig, gravar
from ..logger import get_logger

log = get_logger("painel.salvar")


def rota_salvar(
    autorizado: Callable[[Request], bool],
    config_de: Callable[[], Any],
    base_de: Callable[..., Any],
    ajuste_de: Callable[..., Any],
    medicoes: Any,
    caminho_config: Path,
) -> Callable[[Request], Any]:
    async def salvar(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = config_de()
            base = base_de(conf, corpo)
            pesos, busca = ajuste_de(corpo, base)
        except (ErroDeConfig, ValueError) as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        medicao = medicoes.de(base.id, pesos, busca)
        if medicao is None:
            return JSONResponse(
                {"erro": "esta configuração ainda não foi medida — meça antes de salvar"},
                status_code=409,
            )
        novas = tuple(
            replace(b, pesos=pesos, busca=busca) if b.id == base.id else b for b in conf.bases
        )
        esperada = corpo.get("revisao")
        if esperada is not None and type(esperada) is not str:
            return JSONResponse({"erro": "revisao inválida"}, status_code=400)
        try:
            nova = gravar(
                replace(conf, bases=novas), caminho_config, revisao_esperada=esperada,
            )
        except ConflitoDeConfig as erro:
            return JSONResponse(
                {"erro": str(erro), "codigo": erro.codigo, "acao": erro.acao},
                status_code=409,
            )
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        log.info("base '%s' salva em %s", base.id, caminho_config)
        return JSONResponse(
            {"base": base.id, "salvo": True, "medicao": medicao, "revisao": nova},
        )

    return salvar
