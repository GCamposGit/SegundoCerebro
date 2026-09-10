"""Empacota uma pasta em bundle Markdown — manifesto primeiro, corte em documento.

`J.d`. `list_folder` enumera, `outline` mapeia, `get_document` lê um arquivo.
`pack_folder` é o que o agente chama quando a tarefa é cobrir a pasta: o
sumário, depois os canônicos inteiros, orçamento em caracteres Unicode,
continuação por cursor. Nunca corta no meio de um documento, nunca ranqueia,
nunca resume. Quem escreve o paper é o cliente.
FND-03a: desacopla manifesto de leitura integral; orçamento e limites por chamada.
FND-03b: modo estrito opt-in; documento maior que a página vai para get_document.
"""

from __future__ import annotations

import base64
import binascii
import json
from hashlib import sha256
from typing import Any

from ..index.store import Store
from .documento import LeitorDocumento
from .empacote_pagina import (
    ITENS_POR_PAGINA,
    PaginaEstrita,
    _Pronto,
    _omissao,
    carregar_pagina_legado,
    montar_estrita,
)
from .identidade import montar_uri
from .manifesto import listar, vigentes
from .original import ErroLeitura
from .registro import Documento, quarentena_da_pasta

POLITICAS = ("canonicos", "todos", "apenas_listados")
CHARS_PADRAO = 8_000
MAX_CHARS = 32_000
CURSOR_MAX = 256


def _decodificar(cursor: str | None, estrito: bool) -> tuple[str, int, int] | None:
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= CURSOR_MAX:
            raise ValueError
        dados = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(dados, list) or not dados:
            raise ValueError
        marca, esperado = ("pf:2", 4) if estrito else ("pf:1", 3)
        if len(dados) != esperado or dados[0] != marca:
            raise ValueError
        if not isinstance(dados[1], str) or len(dados[1]) != 64:
            raise ValueError
        if type(dados[2]) is not int or dados[2] < 0:
            raise ValueError
        omitidos = 0
        if estrito:
            if type(dados[3]) is not int or dados[3] < 0:
                raise ValueError
            omitidos = dados[3]
        return dados[1], dados[2], omitidos
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise ErroLeitura("cursor_invalido", "Cursor inválido. Reinicie o pacote sem cursor.") from None


def _cursor(versao: str, inicio: int, inicio_omitidos: int = 0, estrito: bool = False) -> str:
    if estrito:
        payload: list[Any] = ["pf:2", versao, inicio, inicio_omitidos]
    else:
        payload = ["pf:1", versao, inicio]
    dados = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(dados).decode("ascii")


def _orcamento(budget_chars: int) -> int:
    if type(budget_chars) is not int or budget_chars < 1:
        raise ErroLeitura("orcamento_invalido", "budget_chars deve ser um inteiro positivo.")
    return min(budget_chars, MAX_CHARS)


def _ids(ids: list[str] | None) -> tuple[str, ...]:
    if ids is None:
        return ()
    if not isinstance(ids, list) or any(type(i) is not str or not i.strip() for i in ids):
        raise ErroLeitura("ids_invalidos", "ids é uma lista de identificadores ou caminhos não vazios.")
    vistos: list[str] = []
    for item in ids:
        pedido = item.strip()
        if pedido not in vistos:
            vistos.append(pedido)
    return tuple(vistos)


def _escolher(
    documentos: list[Documento], politica: str, pedidos: tuple[str, ...],
) -> tuple[list[Documento], list[dict[str, str]]]:
    if politica not in POLITICAS:
        raise ErroLeitura(
            "politica_invalida",
            "politica deve ser canonicos, todos ou apenas_listados.",
        )
    if pedidos and politica != "apenas_listados":
        raise ErroLeitura("ids_sem_politica", "ids só vale com politica=apenas_listados.")
    if politica == "apenas_listados":
        return _apenas_listados(documentos, pedidos)
    if politica == "canonicos":
        canonico = vigentes(documentos)
        return [d for d in documentos if (d.raiz, d.caminho) in canonico], []
    return list(documentos), []


def _apenas_listados(
    documentos: list[Documento], pedidos: tuple[str, ...],
) -> tuple[list[Documento], list[dict[str, str]]]:
    if not pedidos:
        raise ErroLeitura("ids_obrigatorios", "politica=apenas_listados exige a lista ids.")
    por_id = {d.doc_id: d for d in documentos if d.doc_id}
    por_arquivo = {(d.raiz, d.caminho): d for d in documentos}
    por_caminho: dict[str, list[Documento]] = {}
    for doc in documentos:
        por_caminho.setdefault(doc.caminho, []).append(doc)
    escolhidos: list[Documento] = []
    for pedido in pedidos:
        doc = por_id.get(pedido)
        if doc is None and pedido in por_caminho:
            if len(por_caminho[pedido]) > 1:
                raise ErroLeitura(
                    "caminho_ambiguo",
                    "Há esse caminho em mais de uma raiz. Use o id ou URI do documento.",
                )
            doc = por_caminho[pedido][0]
        if doc is None:
            doc = next((d for (raiz, caminho), d in por_arquivo.items() if caminho == pedido), None)
        if doc is None:
            raise ErroLeitura("id_ausente", f"Não há {pedido} nesta pasta.")
        escolhidos.append(doc)
    return escolhidos, []


def _versao(
    pasta: str,
    recursivo: bool,
    politica: str,
    pedidos: tuple[str, ...],
    candidatos: list[Documento],
    base: str = "",
    estrito: bool = False,
    omitidos: list[dict[str, str]] | None = None,
) -> str:
    """Identidade da seleção a partir de metadados, sem carregar conteúdo."""
    corpo: dict[str, Any] = {
        "base": base,
        "pasta": pasta,
        "recursivo": recursivo,
        "politica": politica,
        "ids": list(pedidos),
        "docs": [
            (d.raiz, d.caminho, d.sha256, d.parser, d.mtime, d.tamanho)
            for d in candidatos
        ],
    }
    if estrito:
        corpo["estrito"] = True
        corpo["omitidos"] = [
            (o.get("arquivo"), o.get("raiz"), o.get("id"), o.get("motivo"))
            for o in omitidos or ()
        ]
    return sha256(json.dumps(
        corpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _markdown(
    pasta: str,
    politica: str,
    candidatos: list[Documento],
    prontos_map: dict[int, _Pronto],
    omitidos: list[dict[str, str]],
    inicio: int,
) -> str:
    """Sumário estável construído sobre a seleção, sem exigir leitura total."""
    nome = pasta.rstrip("/") or "(raiz da base)"
    linhas = [
        f"# Pacote da pasta {nome}",
        "",
        f"politica: {politica}",
        f"packaveis: {len(candidatos)}",
        f"omitidos: {len(omitidos)}",
        f"continuidade: a partir do documento {inicio + 1}" if candidatos else "continuidade: fim",
        "corte: fronteira de documento; nunca no meio de um arquivo",
        "",
        "## Manifesto",
        "",
    ]
    for i, doc in enumerate(candidatos):
        marca = "feito" if i < inicio else "pendente"
        ident = doc.doc_id
        chars_n = len(prontos_map[i].markdown) if i in prontos_map else doc.tamanho
        linhas.append(f"- [{marca}] {doc.caminho} ({ident}, {chars_n} chars)")
    for item in omitidos:
        linhas.append(
            f"- [omitido] {item['arquivo']} ({item.get('id') or item.get('sem_id') or 'sem id'}"
            f", {item['motivo']})"
        )
    if not candidatos and not omitidos:
        linhas.append("- (nenhum documento nesta pasta)")
    linhas.extend(["", "## Documentos", ""])
    return "\n".join(linhas)


def _itens(
    candidatos: list[Documento],
    prontos_map: dict[int, _Pronto],
    omitidos: list[dict[str, str]],
    inicio: int,
    fim: int,
    base: str,
) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for i, doc in enumerate(candidatos):
        if i < inicio:
            papel = "ja_empacotado"
        elif i < fim:
            papel = "nesta_pagina"
        else:
            papel = "restante"
        chars = len(prontos_map[i].markdown) if i in prontos_map else doc.tamanho
        item: dict[str, Any] = {
            "arquivo": doc.caminho,
            "raiz": doc.raiz,
            "id": doc.doc_id,
            "chars": chars,
            "papel": papel,
        }
        if base and doc.doc_id:
            item["uri"] = montar_uri(base, doc.doc_id)
        saida.append(item)
    for item in omitidos:
        saida.append({**item, "papel": "omitido"})
    return saida


def _envelope(
    pasta: str,
    politica: str,
    recursivo: bool,
    markdown: str,
    candidatos: list[Documento],
    prontos_map: dict[int, _Pronto],
    omitidos: list[dict[str, str]],
    inicio: int,
    fim: int,
    base: str,
    versao: str,
    documentos: list[Documento],
    erros_censo: list[str],
) -> dict[str, Any]:
    restante = len(candidatos) - fim
    total = inicio + len(prontos_map) + restante
    if total and fim > inicio:
        mostrando = f"{inicio + 1}-{inicio + len(prontos_map)} de {total}"
    elif total:
        mostrando = f"nenhum documento a partir da posição {inicio + 1}, de {total}"
    else:
        mostrando = "0 de 0"

    saida: dict[str, Any] = {
        "pasta": pasta.replace("\\", "/").strip().strip("/") or "(raiz da base)",
        "politica": politica,
        "recursivo": bool(recursivo),
        "markdown": markdown,
        "itens": _itens(candidatos, prontos_map, omitidos, inicio, fim, base),
        "incluidos": [candidatos[k].caminho for k in range(inicio, fim) if k in prontos_map],
        "omitidos": omitidos,
        "total": total,
        "mostrando": mostrando,
        "completo": restante == 0,
        "unidade": "documentos",
        "fronteira": (
            "Bundle da versão indexada, sem resumo e sem ranking. Cada documento entra "
            "inteiro ou fica para a próxima página; o que não tem canônico aparece em omitidos. "
            "Cite arquivo e raiz, nunca o cache."
        ),
    }
    if restante:
        saida["cursor_proximo"] = _cursor(versao, fim)
        saida["restante"] = restante
    if not documentos:
        saida["aviso"] = (
            "nenhum documento encontrado sob esta pasta. Confira o caminho como ele aparece "
            "no campo `arquivo` de `search`."
        )
    elif not candidatos:
        saida["aviso"] = (
            "nenhum documento desta seleção tem texto canônico disponível. "
            "Indexe os arquivos so_censo ou use get_document no que já tem identidade."
        )
    if erros_censo:
        saida["aviso_censo"] = (
            f"{len(erros_censo)} falha(s) na enumeração; a lista pode estar incompleta."
        )
    return saida


def _flag_estrito(estrito: object) -> bool:
    if type(estrito) is not bool:
        raise ErroLeitura("modo_invalido", "estrito deve ser true ou false.")
    return estrito


def _partir(
    escolhidos: list[Documento], extras: list[dict[str, str]], quarentena: dict[str, str],
) -> tuple[list[Documento], list[dict[str, str]]]:
    candidatos: list[Documento] = []
    omitidos: list[dict[str, str]] = list(extras)
    for doc in escolhidos:
        if not doc.doc_id:
            omitidos.append(_omissao(doc, doc.sem_id or "sem identidade no índice"))
        elif doc.caminho in quarentena:
            omitidos.append(_omissao(doc, f"em quarentena: {quarentena[doc.caminho]}", "quarentena"))
        elif doc.status and doc.status != "ok":
            omitidos.append(_omissao(doc, f"status: {doc.status}", doc.status))
        else:
            candidatos.append(doc)
    return candidatos, omitidos


def _posicao(
    continuacao: tuple[str, int, int] | None,
    versao: str,
    n_docs: int,
    n_omitidos: int,
) -> tuple[int, int]:
    if continuacao is None:
        return 0, 0
    if continuacao[0] != versao or continuacao[1] > n_docs or continuacao[2] > n_omitidos:
        raise ErroLeitura("cursor_desatualizado", "A pasta ou a política mudou. Reinicie sem cursor.")
    return continuacao[1], continuacao[2]


def _saida_estrita(
    saida: dict[str, Any],
    pagina: PaginaEstrita,
    versao: str,
    candidatos: list[Documento],
    omitidos_pre: list[dict[str, str]],
) -> dict[str, Any]:
    restante = (len(candidatos) - pagina.fim) + (len(omitidos_pre) - pagina.fim_omitidos)
    omitidos = pagina.omitidos_pagina + pagina.omitidos_carga
    saida["estrito"] = True
    saida["unidade"] = "caracteres Unicode"
    saida["teto_itens"] = ITENS_POR_PAGINA
    saida["itens"] = pagina.itens
    saida["incluidos"] = pagina.incluidos
    saida["omitidos"] = omitidos
    saida["encaminhados"] = pagina.encaminhados
    saida["total"] = len(candidatos) + len(omitidos_pre)
    saida["completo"] = restante == 0
    saida["mostrando"] = (
        f"{len(pagina.incluidos)} nesta página, {len(pagina.encaminhados)} encaminhado(s) "
        f"a get_document, {len(omitidos)} omitido(s) desta página"
    )
    saida["fronteira"] = (
        "Modo estrito: o Markdown nunca ultrapassa budget_chars (caracteres Unicode, "
        "não tokens). Documento maior que a página não entra no bundle; use get_document "
        "com o id. Cite arquivo e raiz, nunca o cache."
    )
    saida.pop("cursor_proximo", None)
    saida.pop("restante", None)
    if restante:
        saida["cursor_proximo"] = _cursor(versao, pagina.fim, pagina.fim_omitidos, estrito=True)
        saida["restante"] = restante
    return saida


def empacotar(
    store: Store,
    pasta: str,
    *,
    leitor: LeitorDocumento,
    budget_chars: int = CHARS_PADRAO,
    cursor: str | None = None,
    politica: str = "canonicos",
    ids: list[str] | None = None,
    recursivo: bool = False,
    base: str = "",
    censo_cfg=None,  # noqa: ANN001
    estrito: bool = False,
) -> dict[str, Any]:
    """Bundle manifesto-first; corta só em fronteira de documento."""
    budget = _orcamento(budget_chars)
    flag = _flag_estrito(estrito)
    continuacao = _decodificar(cursor, flag)
    pedidos = _ids(ids)
    documentos, erros_censo = listar(store, pasta, recursivo=recursivo, censo_cfg=censo_cfg)
    escolhidos, extras = _escolher(documentos, politica, pedidos)
    candidatos, omitidos = _partir(
        escolhidos, extras, quarentena_da_pasta(store, pasta, recursivo=recursivo),
    )
    versao = _versao(
        pasta, recursivo, politica, pedidos, candidatos, base,
        estrito=flag, omitidos=omitidos,
    )
    inicio, inicio_omit = _posicao(continuacao, versao, len(candidatos), len(omitidos))
    if flag:
        pagina = montar_estrita(
            leitor, pasta, politica, candidatos, omitidos, inicio, inicio_omit, budget, base,
        )
        saida = _envelope(
            pasta, politica, recursivo, pagina.markdown, candidatos, pagina.prontos_map,
            omitidos, inicio, pagina.fim, base, versao, documentos, erros_censo,
        )
        return _saida_estrita(saida, pagina, versao, candidatos, omitidos)

    prontos_map, omitidos_novos, blocos, fim = carregar_pagina_legado(
        leitor, candidatos, inicio, budget, base,
    )
    omitidos.extend(omitidos_novos)
    markdown = _markdown(pasta, politica, candidatos, prontos_map, omitidos, inicio) + "".join(blocos)
    return _envelope(
        pasta, politica, recursivo, markdown, candidatos, prontos_map, omitidos,
        inicio, fim, base, versao, documentos, erros_censo,
    )
