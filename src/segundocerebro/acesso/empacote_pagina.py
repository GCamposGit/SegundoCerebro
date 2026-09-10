"""Uma página de pack_folder: legado (J.d/FND-03a) e modo estrito (FND-03b).

O Markdown conta caracteres Unicode, nunca tokens. Metadados/itens têm teto
próprio. Documento que não cabe na página estrita vai para get_document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ingest.parse_store import Chave
from .documento import LeitorDocumento
from .identidade import montar_uri
from .original import ErroLeitura
from .registro import Documento

DOCS_POR_CHAMADA_MAX = 100
ITENS_POR_PAGINA = 100
"""Teto de linhas de manifesto/itens por página, independente de budget_chars."""

_MSG_ORCAMENTO = (
    "budget_chars não comporta o envelope mínimo do manifesto. "
    "Aumente o orçamento ou leia o arquivo com get_document."
)


def _exigir_orcamento(ok: bool) -> None:
    if not ok:
        raise ErroLeitura("orcamento_insuficiente", _MSG_ORCAMENTO)


@dataclass(frozen=True)
class _Pronto:
    doc: Documento
    markdown: str
    chave: Chave


@dataclass
class PaginaEstrita:
    markdown: str
    prontos_map: dict[int, _Pronto]
    omitidos_pagina: list[dict[str, str]]
    omitidos_carga: list[dict[str, str]]
    encaminhados: list[dict[str, Any]]
    itens: list[dict[str, Any]]
    incluidos: list[str]
    fim: int
    fim_omitidos: int


def _omissao(doc: Documento, motivo: str, codigo: str = "") -> dict[str, str]:
    item = {"arquivo": doc.caminho, "raiz": doc.raiz, "motivo": motivo}
    if doc.doc_id:
        item["id"] = doc.doc_id
    if codigo:
        item["codigo"] = codigo
    if not doc.doc_id and doc.sem_id:
        item["sem_id"] = doc.sem_id
    return item


def _separador(pronto: _Pronto, base: str) -> str:
    doc = pronto.doc
    linhas = [
        "", "", "---",
        f"id: {doc.doc_id}",
        f"arquivo: {doc.caminho}",
        f"raiz: {doc.raiz}",
    ]
    if base and doc.doc_id:
        linhas.append(f"uri: {montar_uri(base, doc.doc_id)}")
    linhas.extend([
        f"sha256: {doc.sha256}",
        f"chars: {len(pronto.markdown)}",
        "---", "",
    ])
    return "\n".join(linhas)


def carregar_pagina_legado(
    leitor: LeitorDocumento,
    candidatos: list[Documento],
    inicio: int,
    budget: int,
    base: str,
    max_docs: int = DOCS_POR_CHAMADA_MAX,
) -> tuple[dict[int, _Pronto], list[dict[str, str]], list[str], int]:
    """Primeiro da página entra inteiro mesmo acima do orçamento (contrato J.d)."""
    prontos_map: dict[int, _Pronto] = {}
    omitidos: list[dict[str, str]] = []
    blocos: list[str] = []
    usados = 0
    i = inicio

    while i < len(candidatos):
        doc = candidatos[i]
        try:
            chave, canonico, _alvo = leitor.carregar_documento(doc)
            pronto = _Pronto(doc=doc, markdown=canonico.markdown, chave=chave)
            bloco = _separador(pronto, base) + pronto.markdown
        except ErroLeitura as erro:
            omitidos.append(_omissao(doc, str(erro), erro.codigo))
            i += 1
            continue

        if i > inicio and usados + len(bloco) > budget:
            break

        prontos_map[i] = pronto
        blocos.append(bloco)
        usados += len(bloco)
        i += 1
        if len(blocos) >= max_docs:
            break

    return prontos_map, omitidos, blocos, i


def _juntar(prefixo: str, linhas: list[str], sufixo: str, blocos: list[str]) -> str:
    meio = "\n".join(linhas)
    if meio:
        meio += "\n"
    return f"{prefixo}{meio}{sufixo}{''.join(blocos)}"


def _cabe(
    prefixo: str, linhas: list[str], sufixo: str, blocos: list[str], budget: int,
    linha: str | None = None, bloco: str | None = None,
) -> bool:
    extra_l = linhas if linha is None else linhas + [linha]
    extra_b = blocos if bloco is None else blocos + [bloco]
    return len(_juntar(prefixo, extra_l, sufixo, extra_b)) <= budget


def _prefixo_estrito(pasta: str, politica: str, n_pack: int, n_omit: int, inicio: int) -> str:
    nome = pasta.rstrip("/") or "(raiz da base)"
    continuidade = (
        f"continuidade: a partir do documento {inicio + 1}" if n_pack else "continuidade: fim"
    )
    return "\n".join([
        f"# Pacote da pasta {nome}",
        "",
        f"politica: {politica}",
        "modo: estrito",
        f"packaveis: {n_pack}",
        f"omitidos: {n_omit}",
        continuidade,
        "corte: fronteira de documento; maior que a página vai para get_document",
        "unidade: caracteres Unicode do Markdown, não tokens",
        "",
        "## Manifesto",
        "",
    ])


def _linha_doc(marca: str, doc: Documento, chars: int, extra: str = "") -> str:
    ident = doc.doc_id or doc.sem_id or "sem id"
    cauda = f"; {extra}" if extra else ""
    return f"- [{marca}] {doc.caminho} ({ident}, {chars} chars{cauda})"


def _linha_omitido(item: dict[str, str]) -> str:
    ident = item.get("id") or item.get("sem_id") or "sem id"
    return f"- [omitido] {item['arquivo']} ({ident}, {item['motivo']})"


def _item_encaminhado(doc: Documento, chars: int, base: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "arquivo": doc.caminho,
        "raiz": doc.raiz,
        "id": doc.doc_id,
        "chars": chars,
        "papel": "encaminhado",
        "motivo": "maior que o orçamento da página",
        "proximo_passo": "get_document",
        "documento": doc.doc_id or doc.caminho,
    }
    if base and doc.doc_id:
        item["uri"] = montar_uri(base, doc.doc_id)
    return item


def _item_pagina(doc: Documento, chars: int, papel: str, base: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "arquivo": doc.caminho,
        "raiz": doc.raiz,
        "id": doc.doc_id,
        "chars": chars,
        "papel": papel,
    }
    if base and doc.doc_id:
        item["uri"] = montar_uri(base, doc.doc_id)
    return item


def _preencher_omitidos(
    prefixo: str, sufixo: str, budget: int, omitidos_pre: list[dict[str, str]], inicio: int,
) -> tuple[list[str], list[dict[str, str]], int]:
    linhas: list[str] = []
    pagina: list[dict[str, str]] = []
    i = inicio
    while i < len(omitidos_pre) and len(linhas) < ITENS_POR_PAGINA:
        item = omitidos_pre[i]
        linha = _linha_omitido(item)
        if not _cabe(prefixo, linhas, sufixo, [], budget, linha=linha):
            break
        linhas.append(linha)
        pagina.append({**item, "papel": "omitido"})
        i += 1
    return linhas, pagina, i


def _carregar_um(
    leitor: LeitorDocumento, doc: Documento, base: str,
) -> tuple[_Pronto | None, str, dict[str, str] | None]:
    try:
        chave, canonico, _alvo = leitor.carregar_documento(doc)
    except ErroLeitura as erro:
        return None, "", _omissao(doc, str(erro), erro.codigo)
    pronto = _Pronto(doc=doc, markdown=canonico.markdown, chave=chave)
    return pronto, _separador(pronto, base) + pronto.markdown, None


def _acao_documento(
    prefixo: str, linhas: list[str], sufixo: str, blocos: list[str], budget: int,
    linha_ok: str, linha_enc: str, bloco: str,
) -> str:
    """incluir | encaminhar | parar | orcamento — nunca corta o Markdown do arquivo."""
    if _cabe(prefixo, linhas, sufixo, blocos, budget, linha=linha_ok, bloco=bloco):
        return "incluir"
    if _cabe(prefixo, [], sufixo, [], budget, linha=linha_ok, bloco=bloco):
        return "parar"
    if _cabe(prefixo, linhas, sufixo, blocos, budget, linha=linha_enc):
        return "encaminhar"
    if linhas or blocos:
        return "parar"
    return "orcamento"


def _preencher_documentos(
    leitor: LeitorDocumento,
    candidatos: list[Documento],
    inicio: int,
    prefixo: str,
    sufixo: str,
    budget: int,
    base: str,
    linhas: list[str],
) -> tuple[dict[int, _Pronto], list[str], list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], int]:
    prontos: dict[int, _Pronto] = {}
    blocos: list[str] = []
    encaminhados: list[dict[str, Any]] = []
    carga: list[dict[str, str]] = []
    itens: list[dict[str, Any]] = []
    i = inicio
    while i < len(candidatos) and len(linhas) < ITENS_POR_PAGINA:
        pronto, bloco, falha = _carregar_um(leitor, candidatos[i], base)
        if falha is not None:
            linha = _linha_omitido(falha)
            if not _cabe(prefixo, linhas, sufixo, blocos, budget, linha=linha):
                break
            linhas.append(linha)
            carga.append(falha)
            itens.append({**falha, "papel": "omitido"})
            i += 1
            continue
        assert pronto is not None
        chars = len(pronto.markdown)
        linha_ok = _linha_doc("nesta_pagina", pronto.doc, chars)
        linha_enc = _linha_doc(
            "encaminhado", pronto.doc, chars, "maior que a página → get_document",
        )
        acao = _acao_documento(prefixo, linhas, sufixo, blocos, budget, linha_ok, linha_enc, bloco)
        if acao == "incluir":
            linhas.append(linha_ok)
            blocos.append(bloco)
            prontos[i] = pronto
            itens.append(_item_pagina(pronto.doc, chars, "nesta_pagina", base))
            i += 1
        elif acao == "encaminhar":
            encaminhado = _item_encaminhado(pronto.doc, chars, base)
            linhas.append(linha_enc)
            encaminhados.append(encaminhado)
            itens.append(encaminhado)
            i += 1
        elif acao == "parar":
            break
        else:
            _exigir_orcamento(False)
        if len(prontos) >= DOCS_POR_CHAMADA_MAX:
            break
    return prontos, blocos, encaminhados, carga, itens, i


def montar_estrita(
    leitor: LeitorDocumento,
    pasta: str,
    politica: str,
    candidatos: list[Documento],
    omitidos_pre: list[dict[str, str]],
    inicio: int,
    inicio_omitidos: int,
    budget: int,
    base: str,
) -> PaginaEstrita:
    """Uma página cujo Markdown nunca ultrapassa budget_chars (Unicode)."""
    prefixo = _prefixo_estrito(pasta, politica, len(candidatos), len(omitidos_pre), inicio)
    sufixo = "\n## Documentos\n"
    _exigir_orcamento(len(_juntar(prefixo, [], sufixo, [])) < budget)
    linhas, omit_pagina, fim_omit = _preencher_omitidos(
        prefixo, sufixo, budget, omitidos_pre, inicio_omitidos,
    )
    prontos, blocos, encaminhados, carga, itens_docs, fim = _preencher_documentos(
        leitor, candidatos, inicio, prefixo, sufixo, budget, base, linhas,
    )
    markdown = _juntar(prefixo, linhas, sufixo, blocos)
    _exigir_orcamento(len(markdown) <= budget)
    andou = fim > inicio or fim_omit > inicio_omitidos or encaminhados or carga
    falta = inicio < len(candidatos) or inicio_omitidos < len(omitidos_pre)
    _exigir_orcamento(andou or not falta)

    incluidos = [candidatos[k].caminho for k in sorted(prontos)]
    return PaginaEstrita(
        markdown=markdown,
        prontos_map=prontos,
        omitidos_pagina=omit_pagina,
        omitidos_carga=carga,
        encaminhados=encaminhados,
        itens=omit_pagina + itens_docs,
        incluidos=incluidos,
        fim=fim,
        fim_omitidos=fim_omit,
    )
