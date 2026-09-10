"""POST /api/exportar — a ação do `J.e` no painel.

Import tardio do vault: abrir o painel não pode arrastar Parse Store, encoder
nem o indexador. A recusa de destino dentro da raiz é a mesma do CLI.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import ErroDeConfig
from ..logger import get_logger
from .trabalho import Ocupado, executar

log = get_logger("painel.exportar")

DIM_LEITURA = 8


def rota_exportar(
    autorizado: Callable[[Request], bool],
    config_de: Callable[[], Any],
    base_de: Callable[..., Any],
) -> Callable[[Request], Any]:
    async def exportar(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        destino = corpo.get("destino")
        if not isinstance(destino, str) or not destino.strip():
            return JSONResponse(
                {"erro": "Informe a pasta do vault, fora das raízes indexadas."},
                status_code=400,
            )
        try:
            base = base_de(config_de(), corpo)
            saida = await executar(base.id, lambda: _gerar(base, corpo, destino.strip()))
            return JSONResponse(saida)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        except Ocupado as erro:
            return JSONResponse({"erro": str(erro), "codigo": erro.codigo}, status_code=409)
        except _ErroDeExportacao as erro:
            return JSONResponse({"erro": str(erro), "codigo": erro.codigo}, status_code=400)
        except OSError:
            return JSONResponse(
                {"erro": "Não foi possível gravar o vault. Confira o destino e o acesso ao disco."},
                status_code=500,
            )

    return exportar


class _ErroDeExportacao(ValueError):
    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


def _gerar(base: Any, corpo: dict[str, Any], destino: str) -> dict[str, Any]:
    from ..acesso.documento import LeitorDocumento
    from ..acesso.original import ErroLeitura
    from ..acesso.vault import ErroVault, exportar as gerar
    from ..index.store import Store
    from ..retrieve.glossario import Glossario

    if not Path(base.indice).exists():
        raise _ErroDeExportacao("sem_indice", "Índice não encontrado. Indexe a base antes de exportar.")
    censo_cfg = base.censo()
    raizes = [Path(r.path) for r in censo_cfg.roots]
    glossario = Glossario.de_arquivo(base.glossario) if base.glossario else Glossario.vazio()
    store = Store(base.indice, DIM_LEITURA)
    try:
        return gerar(
            store, Path(destino), leitor=LeitorDocumento(store, base), raizes=raizes,
            pasta=str(corpo.get("pasta") or ""),
            politica=str(corpo.get("politica") or "canonicos"),
            recursivo=True, base=base.id, censo_cfg=censo_cfg,
            glossario=glossario, completo=bool(corpo.get("completo")),
        )
    except (ErroVault, ErroLeitura) as erro:
        raise _ErroDeExportacao(erro.codigo, str(erro)) from erro
    finally:
        store.fechar()
