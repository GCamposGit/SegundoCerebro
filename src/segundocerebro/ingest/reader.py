"""The only place in the system that opens a corpus file.

Every parser receives bytes, never a path. That is deliberate: three hazards
found in the real corpus have to be handled once, in one place, or they will be
forgotten in the fifth parser someone adds.

1. **Cloud placeholders.** On a synced OneDrive/SharePoint folder a file may not
   be on disk. Opening it triggers a download. The check happens here, before
   any read, and hydration only ever happens when explicitly allowed.
2. **Paths over 260 characters.** 34 files in the corpus; the Windows API fails
   with "file not found", which is the most misleading error possible.
3. **Files locked by Word/Excel.** The corpus is a live working folder, so this
   is routine. It gets a retry and then an explicit `travado` status — never a
   crash, never a silent skip.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping

from ..census import caminho_estendido, is_cloud_only
from ..logger import get_logger
from .document import ParsedDoc, ParseResult, ParseStatus
from .natureza import EXTENSOES_DE_PLANILHA, detectar, mb_de_abas

log = get_logger("ingest.reader")

RETRIES_PADRAO = 2
ESPERA_PADRAO = 1.0

# R1.1: OLE legado → OOXML via LibreOffice, then the modern parser.
# The dispatcher is not this module's to edit (`parsers/__init__.py` is
# "um de cada vez"). The convert lives here, next to C7.a recalc.
EXTENSOES_LEGADO = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}
_CONTEUDO_JA_ESTRUTURADO = frozenset({"html", "xml", "pptx", "spreadsheetml"})


class CloudOnlyFile(OSError):
    """The content is not on disk; reading it would pull it from the cloud."""


class FileLocked(OSError):
    """Another process holds the file — Word and Excel do this routinely."""


def read_bytes(
    path: str,
    *,
    allow_hydration: bool = False,
    retries: int = RETRIES_PADRAO,
    espera: float = ESPERA_PADRAO,
) -> bytes:
    """Read a corpus file, refusing to hydrate placeholders by default."""
    alvo = caminho_estendido(path)

    st = os.stat(alvo)
    if is_cloud_only(getattr(st, "st_file_attributes", 0)) and not allow_hydration:
        raise CloudOnlyFile(f"placeholder de nuvem, leitura recusada: {path}")

    ultimo: OSError | None = None
    for tentativa in range(retries + 1):
        try:
            with open(alvo, "rb") as fh:
                return fh.read()
        except PermissionError as exc:
            ultimo = exc
            if tentativa < retries:
                log.debug("arquivo travado, nova tentativa em %.1fs: %s", espera, path)
                time.sleep(espera)
    raise FileLocked(f"arquivo em uso por outro processo: {path}") from ultimo


def _adiar_por_tamanho(path: str, limite_mb: float) -> ParseResult | None:
    """`adiado` for an oversized file, without reading a single byte of content.

    Size comes from `stat`, which does not hydrate a cloud placeholder. A 269 MB
    export must not be loaded into RAM just so we can decide not to index it.
    """
    try:
        tamanho = os.stat(caminho_estendido(path)).st_size
    except OSError:
        return None
    mb = tamanho / 1_000_000
    if mb <= limite_mb:
        return None
    extensao = os.path.splitext(path)[1].lower()
    log.info(
        "adiado: %s tem %.1f MB em disco (limite %.1f MB para %s)",
        path,
        mb,
        limite_mb,
        extensao,
    )
    return ParseResult(
        path=path,
        status=ParseStatus.DEFERRED,
        detail=f"{mb:.1f} MB em disco, acima do limite de {limite_mb:.1f} MB para {extensao}",
    )


def parse_file(
    path: str,
    *,
    allow_hydration: bool = False,
    retries: int = RETRIES_PADRAO,
    espera: float = ESPERA_PADRAO,
    limite_planilha_mb: float | None = None,
    limite_texto_mb: float | None = None,
    limites_mb: Mapping[str, float] | None = None,
    ocr: bool = False,
) -> ParseResult:
    """Read and parse one file, turning every failure into a recorded status.

    `limites_mb` adia pelo tamanho em disco **antes** de abrir, por extensão.
    `limite_texto_mb` é o atalho legado para `.txt` (C7.d: CSV left this gate —
    the spreadsheet parser turns a dump into a digest instead of hiding the
    file). `limite_planilha_mb` adia planilhas pelo XML de abas, que o tamanho
    em disco não prevê. As três decisões moram aqui, e não no indexador, pelo
    mesmo motivo que a recusa de placeholder de nuvem mora aqui: é uma decisão
    sobre **abrir ou não abrir o conteúdo**, e ter dois lugares que decidem
    isso é como o portão único se perde.
    """
    from .parsers import parser_for  # local import keeps the registry lazy

    extensao = os.path.splitext(path)[1].lower()
    parser = parser_for(extensao)
    if parser is None:
        return ParseResult(path=path, status=ParseStatus.UNSUPPORTED, detail=extensao)

    mapa = dict(limites_mb or {})
    if limite_texto_mb is not None:
        if limite_texto_mb > 0:
            mapa[".txt"] = limite_texto_mb
        else:
            mapa.pop(".txt", None)
    teto = mapa.get(extensao)
    if teto is not None and teto > 0:
        adiado = _adiar_por_tamanho(path, teto)
        if adiado is not None:
            return adiado

    try:
        dados = read_bytes(path, allow_hydration=allow_hydration, retries=retries, espera=espera)
    except CloudOnlyFile as exc:
        return ParseResult(path=path, status=ParseStatus.CLOUD_ONLY, detail=str(exc))
    except FileLocked as exc:
        log.warning("travado, será reindexado na próxima passada: %s", path)
        return ParseResult(path=path, status=ParseStatus.LOCKED, detail=str(exc))
    except FileNotFoundError as exc:
        # Enumerado e apagado antes de chegarmos nele — rotina num acervo que é
        # pasta de trabalho viva, e não a mesma coisa que um parser quebrado.
        log.info("sumiu entre a varredura e a leitura: %s", path)
        return ParseResult(path=path, status=ParseStatus.GONE, detail=f"{type(exc).__name__}: {exc}")
    except OSError as exc:
        return ParseResult(path=path, status=ParseStatus.ERROR, detail=f"{type(exc).__name__}: {exc}")

    sha = hashlib.sha256(dados).hexdigest()
    nome = os.path.basename(path)

    if limite_planilha_mb is not None and extensao in EXTENSOES_DE_PLANILHA:
        mb = mb_de_abas(dados)
        if mb is not None and mb > limite_planilha_mb:
            log.info("adiada: %s tem %.0f MB de XML de abas (limite %.0f)", path, mb, limite_planilha_mb)
            return ParseResult(
                path=path,
                status=ParseStatus.DEFERRED,
                detail=f"{mb:.0f} MB de XML de abas, acima do limite de {limite_planilha_mb:.0f}",
                sha256=sha,
                natureza=detectar(path, dados),
            )

    try:
        doc = parser(dados, nome)
    except Exception as exc:  # a corrupt file must not stop the indexing run
        # R1.1: xlrd/ole_texto recusou, Calc/Writer still might. Encryption is
        # not that class — LibreOffice would prompt and hang.
        if extensao in EXTENSOES_LEGADO and "criptograf" not in str(exc).lower():
            legado = _converter_legado(None, dados, nome, extensao)
            if legado is not None:
                doc = legado
            else:
                doc = None
        else:
            doc = None
        if doc is None:
            natureza = detectar(path, dados)
            if not natureza.extensao_mente:
                log.warning("falha ao interpretar %s: %s", path, exc)
                return ParseResult(
                    path=path,
                    status=ParseStatus.ERROR,
                    detail=f"{type(exc).__name__}: {exc}",
                    sha256=sha,
                    natureza=natureza,
                )

            # Não é corrupção: é outro formato com a extensão errada. Antes de
            # desistir, tentar o parser do conteúdo — o `detalhe` já dizia qual era,
            # e recusar um documento que sabemos interpretar seria desperdício.
            alternativo = _reinterpretar(path, dados, nome, natureza.familia_real)
            if alternativo is None:
                # Dizer o conteúdo real no `detalhe` poupa a investigação que este
                # caso já custou uma vez.
                log.warning(
                    "%s tem extensão %s mas conteúdo %s — não é corrupção",
                    path,
                    os.path.splitext(path)[1].lower(),
                    natureza.familia_real,
                )
                return ParseResult(
                    path=path,
                    status=ParseStatus.UNSUPPORTED,
                    detail=f"extensão mente: conteúdo é {natureza.familia_real}",
                    sha256=sha,
                    natureza=natureza,
                )
            doc = alternativo

    if extensao in EXTENSOES_LEGADO and doc.meta.get("convertido") != "libreoffice":
        melhor = _converter_legado(doc, dados, nome, extensao)
        if melhor is not None:
            doc = melhor

    if doc.meta.get("sem_valor_em_cache") == "1":
        doc = _recalcular_planilha(doc, dados, nome, parser)

    natureza = detectar(path, dados, doc)
    if ocr and natureza.digitalizado:
        ocr_doc = _ocr_pdf(dados, nome, nativo=doc)
        if ocr_doc is not None and ocr_doc.blocks:
            natureza = detectar(path, dados, ocr_doc)
            return ParseResult(
                path=path,
                status=ParseStatus.OK,
                doc=ocr_doc,
                sha256=sha,
                natureza=natureza,
            )
    if not doc.blocks or not doc.total_chars:
        detalhe = "digitalizado, sem camada de texto" if natureza.digitalizado else "nenhum texto extraível"
        return ParseResult(
            path=path,
            status=ParseStatus.EMPTY,
            doc=doc,
            detail=detalhe,
            sha256=sha,
            natureza=natureza,
        )

    return ParseResult(path=path, status=ParseStatus.OK, doc=doc, sha256=sha, natureza=natureza)


def _reinterpretar(path: str, dados: bytes, nome: str, familia: str) -> ParsedDoc | None:
    """Segunda tentativa pelo conteúdo, para o arquivo cuja extensão mente.

    Devolve `None` quando não há parser sem ambiguidade para a família — aí o
    resultado volta a ser `sem_parser` com o motivo, que é honesto. Uma segunda
    falha também devolve `None`: o arquivo pode estar corrompido *e* mentir sobre
    a extensão, e nesse caso o motivo que interessa continua sendo o primeiro.
    """
    from .parsers import parser_for_familia

    parser = parser_for_familia(familia)
    if parser is None:
        return None
    try:
        doc = parser(dados, nome)
    except Exception as exc:  # noqa: BLE001 — mesmo motivo da primeira tentativa
        log.warning("extensão mente (%s) e o parser de %s também falhou: %s", path, familia, exc)
        return None
    log.info("extensão mente: %s interpretado como %s", path, familia)
    return doc


def _ocr_pdf(dados: bytes, nome: str, nativo: ParsedDoc | None = None) -> ParsedDoc | None:
    """Second pass on scan pages. Missing extra is `None`, not EMPTY-with-a-lie.

    `nativo` is the cheap parse: mixed PDFs keep those blocks and only the
    photo pages go through the engine.
    """
    from .ocr import doc_de_ocr

    return doc_de_ocr(dados, nome, nativo=nativo)


def _converter_legado(
    doc: ParsedDoc | None,
    dados: bytes,
    nome: str,
    extensao: str,
) -> ParsedDoc | None:
    """OLE → OOXML via LibreOffice, then the modern parser. `None` keeps the fallback.

    Parsers never spawn soffice. Missing binary is the ole_texto/xlrd result,
    not EMPTY — same contract as C7.a recalc.
    """
    if doc is not None and (doc.meta or {}).get("conteudo_real") in _CONTEUDO_JA_ESTRUTURADO:
        return None
    moderno = EXTENSOES_LEGADO.get(extensao)
    if moderno is None:
        return None
    from .converters.libreoffice import converter
    from .parsers import parser_for

    convertido = converter(dados, extensao)
    if convertido is None:
        return None
    parser_mod = parser_for(moderno)
    if parser_mod is None:
        return None
    try:
        novo = parser_mod(convertido, nome)
    except Exception as exc:  # noqa: BLE001 — convert succeeded, modern parse did not
        log.warning("%s: LibreOffice converteu %s mas o parser %s recusou: %s", nome, extensao, moderno, exc)
        return None
    if not novo.blocks or not novo.total_chars:
        log.info("%s: LibreOffice converteu %s mas não saiu texto", nome, extensao)
        return None
    meta = dict(novo.meta)
    meta["convertido"] = "libreoffice"
    meta["formato"] = extensao.lstrip(".")
    log.info("%s: legado %s via LibreOffice → %s (%d blocos)", nome, extensao, moderno, len(novo.blocks))
    return ParsedDoc(name=novo.name, blocks=novo.blocks, meta=meta)


def _recalcular_planilha(doc: ParsedDoc, dados: bytes, nome: str, parser) -> ParsedDoc:  # noqa: ANN001
    """LibreOffice writes cached values; without it the flag stays (C7.a).

    Parsers never spawn soffice — they return bytes. This is the one place
    allowed to try, and a missing binary is a visible warning, not EMPTY.
    """
    from .converters.libreoffice import recalcular_xlsx

    convertido = recalcular_xlsx(dados)
    if convertido is None:
        log.info("%s: fórmulas sem cache e LibreOffice ausente — valor não entra no índice", nome)
        return doc
    try:
        novo = parser(convertido, nome)
    except Exception as exc:  # noqa: BLE001 — convert succeeded, parse of the result did not
        log.warning("%s: recálculo LibreOffice produziu arquivo ilegível: %s", nome, exc)
        return doc
    if novo.meta.get("sem_valor_em_cache") == "1" or not novo.blocks:
        log.info("%s: LibreOffice converteu mas o cache da fórmula continua vazio", nome)
        return doc
    meta = dict(novo.meta)
    meta["recalculado"] = "libreoffice"
    log.info("%s: recálculo via LibreOffice preencheu fórmulas sem cache", nome)
    return ParsedDoc(name=novo.name, blocks=novo.blocks, meta=meta)


def empty_doc(nome: str, **meta: str) -> ParsedDoc:
    return ParsedDoc(name=nome, blocks=(), meta=meta)
