"""POST /api/medir fora do event loop — FND-05.

Não importa o encoder: o `medidor` é injetado. Store da medição real fica no
worker injetado, não na thread da requisição.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import ErroDeConfig
from ..index.travas import NOME_DA_TRAVA
from .erros import MedicaoIndisponivel
from .trabalho import Ocupado, executar


def rota_medir(
    autorizado: Callable[[Request], bool],
    config_de: Callable[[], Any],
    base_de: Callable[..., Any],
    ajuste_de: Callable[..., Any],
    medidor: Callable[..., dict[str, Any]],
    medicoes: Any,
) -> Callable[[Request], Any]:
    async def medir(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = config_de()
            base = base_de(conf, corpo)
            pesos, busca = ajuste_de(corpo, base)
        except (ErroDeConfig, ValueError) as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        if (base.indice / NOME_DA_TRAVA).exists():
            return JSONResponse(
                {"erro": f"a base '{base.id}' está sendo indexada — medir agora daria número instável"},
                status_code=409,
            )
        try:
            resultado = await executar(base.id, lambda: medidor(base, pesos, busca))
        except Ocupado as erro:
            return JSONResponse({"erro": str(erro), "codigo": erro.codigo}, status_code=409)
        except MedicaoIndisponivel as erro:
            return JSONResponse({"erro": str(erro)}, status_code=503)
        medicoes.registrar(base.id, pesos, busca, resultado)
        return JSONResponse({"base": base.id, "medicao": resultado})

    return medir
