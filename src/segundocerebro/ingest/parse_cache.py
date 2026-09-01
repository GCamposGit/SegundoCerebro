"""Integra o portão de leitura ao parse store sem acoplar o indexador aos parsers.

O arquivo original ainda é aberto pelo ``reader``: o cache só entra depois do
hash e antes do parser. Assim um hit evita PDF/Office/OCR/LibreOffice, mas não
contorna limites de tamanho, placeholders nem a detecção determinística da
natureza do documento.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..logger import get_logger
from .canonico import reconstruir, renderizar
from .converters.libreoffice import EXTENSOES_LEGADO
from .document import ParsedDoc, ParseResult, ParseStatus
from .natureza import EXTENSOES_DE_PLANILHA, detectar
from .ocr import VERSAO as OCR_VERSAO
from .parse_store import (
    ROTA_LIBREOFFICE,
    ROTA_NATIVA,
    ROTA_OCR,
    Chave,
    ParseStore,
    assinatura_do_motor,
    chave_de,
)
from .parsers import parser_version_for

log = get_logger("ingest.parse_cache")


def _chave(sha256: str, parser: str, rota: str) -> Chave:
    return Chave(
        sha256=sha256,
        parser=parser,
        rota=rota,
        motor=assinatura_do_motor(rota),
    )


def _candidatas(sha256: str, extensao: str, *, ocr: bool) -> tuple[Chave, ...]:
    parser = parser_version_for(extensao)
    chaves: list[Chave] = []
    if ocr:
        chaves.append(_chave(sha256, OCR_VERSAO, ROTA_OCR))
    if extensao in EXTENSOES_LEGADO or extensao in EXTENSOES_DE_PLANILHA:
        chaves.append(_chave(sha256, parser, ROTA_LIBREOFFICE))
    chaves.append(_chave(sha256, parser, ROTA_NATIVA))
    return tuple(chaves)


def obter_resultado(
    indice: Path | None,
    *,
    path: str,
    dados: bytes,
    sha256: str,
    ocr: bool,
) -> ParseResult | None:
    """Reconstrói um resultado sem chamar parser; miss continua o fluxo normal."""
    if indice is None:
        return None
    extensao = os.path.splitext(path)[1].lower()
    store = ParseStore(indice)
    for chave in _candidatas(sha256, extensao, ocr=ocr):
        canonico = store.obter(chave)
        if canonico is None:
            continue
        doc = ParsedDoc(
            name=os.path.basename(path),
            blocks=reconstruir(canonico),
            meta=canonico.meta,
        )
        natureza = detectar(path, dados, doc)
        # O parse nativo vazio de um scan não satisfaz uma passada que pediu
        # OCR. Ele continua sendo um hit válido para a passada barata.
        if ocr and natureza.digitalizado and doc.meta.get("fonte") != "ocr":
            continue
        if doc.blocks and doc.total_chars:
            status, detalhe = ParseStatus.OK, ""
        else:
            status = ParseStatus.EMPTY
            detalhe = (
                "digitalizado, sem camada de texto"
                if natureza.digitalizado
                else "nenhum texto extraível"
            )
        log.debug("parse store hit (%s): %s", chave.rota, path)
        return ParseResult(
            path=path,
            status=status,
            doc=doc,
            detail=detalhe,
            sha256=sha256,
            natureza=natureza,
            parse_store_consultado=True,
            parse_store_hit=True,
        )
    return None


def gravar_resultado(indice: Path | None, resultado: ParseResult) -> None:
    """Persiste parses reproduzíveis; falha do cache nunca invalida o parse."""
    if (
        indice is None
        or resultado.doc is None
        or not resultado.sha256
        or resultado.status not in {ParseStatus.OK, ParseStatus.EMPTY}
    ):
        return
    extensao = os.path.splitext(resultado.path)[1].lower()
    parser = (
        resultado.doc.meta.get("parser") or OCR_VERSAO
        if resultado.doc.meta.get("fonte") == "ocr"
        else parser_version_for(extensao)
    )
    chave = chave_de(resultado.sha256, parser, resultado.doc.meta)
    try:
        ParseStore(indice).gravar(chave, renderizar(resultado.doc))
    except OSError as erro:
        log.warning("não foi possível gravar parse store de %s: %s", resultado.path, erro)
