"""Leitura MCP paginada das células estruturadas de uma planilha."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mcp.types import ToolAnnotations

from ..acesso.identidade import conferir_base, interpretar
from ..acesso.planilha import PaginaCelulas, ler_pagina_celulas
from ..acesso.registro import Documento, resolver
from ..index.ocorrencia import CaminhoAmbiguo
from .respostas import ResultadoTool, erro_operacional, sucesso

if TYPE_CHECKING:
    from .server import Recursos

MAX_CELULAS = 200
PADRAO_CELULAS = 100
MAX_CURSOR = 512

DESCRICAO = (
    "Lê valores exatos que já foram estruturados e indexados em uma planilha. "
    "Use quando `search` indicar abas em digesto ou quando precisar de valores de "
    "células individuais. A leitura é paginada por cursor e limitada a 200 células "
    "por chamada; informe documento (doc_id, URI sc:// ou caminho) e opcionalmente "
    "aba, root_id e cursor. Consulta apenas os dados persistidos no índice, sem abrir "
    "o arquivo original."
)


def _binding(base_id: str, sha256: str, arquivo: str, root_id: str, aba: str) -> str:
    dados = json.dumps(
        [base_id, sha256, arquivo, root_id, aba], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(dados).hexdigest()


def _codificar_cursor(
    binding: str, ultima: tuple[str, int, str], entregues: int
) -> str:
    dados = json.dumps(
        {"v": 1, "b": binding, "k": [ultima[0], ultima[1], ultima[2]], "n": entregues},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _decodificar_cursor(cursor: str, binding: str) -> tuple[tuple[str, int, str], int] | None:
    if not cursor:
        return None
    if len(cursor) > MAX_CURSOR:
        raise ValueError("cursor grande demais")
    preenchido = cursor + "=" * (-len(cursor) % 4)
    dados = json.loads(base64.b64decode(preenchido, altchars=b"-_", validate=True))
    if not isinstance(dados, dict) or set(dados) != {"v", "b", "k", "n"}:
        raise ValueError("formato de cursor inválido")
    if dados["b"] != binding:
        raise LookupError("cursor de outro contexto")
    chave = dados["k"]
    entregues = dados["n"]
    if (
        dados["v"] != 1
        or isinstance(dados["v"], bool)
        or not isinstance(chave, list)
        or len(chave) != 3
        or not isinstance(chave[0], str)
        or not isinstance(chave[1], int)
        or isinstance(chave[1], bool)
        or chave[1] < 1
        or not isinstance(chave[2], str)
        or not isinstance(entregues, int)
        or isinstance(entregues, bool)
        or entregues < 1
    ):
        raise ValueError("conteúdo do cursor inválido")
    return (chave[0], chave[1], chave[2]), entregues


def _resolver_documento(
    recursos: Recursos, documento: str, root_id: str
) -> tuple[Documento | None, ResultadoTool | None]:
    referencia = interpretar(documento, root_id=root_id)
    if not referencia.valida:
        return None, erro_operacional(referencia.erro, "referencia_invalida")
    if root_id:
        referencia = replace(referencia, root_id=root_id)
    erro_base = conferir_base(referencia, getattr(recursos.base, "id", ""))
    if erro_base:
        return None, erro_operacional(erro_base, "referencia_invalida")
    try:
        alvo = resolver(recursos.store, referencia)
    except CaminhoAmbiguo as erro:
        return None, erro_operacional(str(erro), "caminho_ambiguo")
    if alvo is None:
        return None, erro_operacional("documento não encontrado no índice", "documento_nao_encontrado")
    if not alvo.sha256:
        return None, erro_operacional(
            "o documento não tem hash no índice; não há identidade segura para consultar células",
            "documento_sem_hash",
            {"arquivo": alvo.caminho},
        )
    return alvo, None


def _montar_payload(
    alvo: Documento,
    pagina: PaginaCelulas,
    aba: str,
    vinculo: str,
    entregues_antes: int,
    limite: int,
) -> ResultadoTool:
    tem_mais = len(pagina.linhas) > limite
    linhas = pagina.linhas[:limite]
    celulas = [
        {
            "aba": nome_aba,
            "linha": numero_linha,
            "coluna": coluna,
            "valor": valor,
            "onde": f"{nome_aba}!{coluna}{numero_linha}",
        }
        for nome_aba, numero_linha, coluna, valor in linhas
    ]
    entregues = entregues_antes + len(celulas)
    cursor_proximo = (
        _codificar_cursor(vinculo, linhas[-1][:3], entregues) if tem_mais and linhas else None
    )
    payload: dict[str, Any] = {
        "arquivo": alvo.caminho,
        "root_id": alvo.root_id,
        "aba": aba or None,
        "total": pagina.total,
        "mostrando": (
            f"{entregues_antes + 1}-{entregues} de {pagina.total}"
            if celulas
            else f"0 de {pagina.total}"
        ),
        "restante": max(0, pagina.total - entregues),
        "completo": not tem_mais,
        "cursor_proximo": cursor_proximo,
        "celulas": celulas,
    }
    if pagina.total == 0:
        payload["aviso"] = "Nenhuma célula estruturada foi persistida para este documento."
    return sucesso(payload)


def _ler_pagina(
    recursos: Recursos,
    alvo: Documento,
    aba: str,
    cursor: str,
    max_celulas: int,
) -> ResultadoTool:
    limite = max(1, min(int(max_celulas), MAX_CELULAS))
    vinculo = _binding(
        getattr(recursos.base, "id", ""), alvo.sha256, alvo.caminho, alvo.root_id, aba
    )
    try:
        continuacao = _decodificar_cursor(cursor, vinculo)
    except LookupError:
        return erro_operacional(
            "o cursor pertence a outro documento, aba ou base", "cursor_contexto_divergente"
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return erro_operacional("cursor inválido", "cursor_invalido")

    depois_de = continuacao[0] if continuacao else None
    entregues_antes = continuacao[1] if continuacao else 0
    pagina = ler_pagina_celulas(
        recursos.store, alvo.sha256, aba=aba, depois_de=depois_de, limite=limite
    )
    if entregues_antes > pagina.total:
        return erro_operacional("cursor não corresponde mais aos dados disponíveis", "cursor_invalido")
    return _montar_payload(alvo, pagina, aba, vinculo, entregues_antes, limite)


def _ler_documento(
    recursos: Recursos,
    documento: str,
    aba: str,
    cursor: str,
    max_celulas: int,
    root_id: str,
) -> ResultadoTool:
    alvo, erro = _resolver_documento(recursos, documento, root_id)
    if erro is not None:
        return erro
    if alvo is None:
        return erro_operacional("documento não encontrado no índice", "documento_nao_encontrado")
    return _ler_pagina(recursos, alvo, aba, cursor, max_celulas)


def registrar(servidor: Any, recursos: Any) -> None:  # noqa: ANN401 — fronteira MCP dinâmica
    """Registra a primitiva MCP sem acoplar a consulta à abertura do original."""

    @servidor.tool(
        description=DESCRICAO,
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, open_world_hint=False
        ),
    )
    def read_spreadsheet_cells(
        documento: str,
        aba: str = "",
        cursor: str = "",
        max_celulas: int = PADRAO_CELULAS,
        root_id: str = "",
    ) -> Any:  # noqa: ANN401 — protocolo serializa dict e CallToolResult
        """Retorna uma página limitada de células persistidas para o documento."""
        return _ler_documento(recursos, documento, aba, cursor, max_celulas, root_id)
