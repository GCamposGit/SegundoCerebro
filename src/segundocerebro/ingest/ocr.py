"""OCR of scanned PDFs — a second pass, never inline with the cheap parse.

The PDF parser already marks `digitalizado` and returns no blocks. That is
the first-day path: text files stay searchable while scans wait. This module
turns those scans into pages of text when a backend is installed.

Backends, in order:
1. RapidOCR (ONNX) — `pip install segundocerebro[ocr]`, no system binary.
2. Tesseract, if `tesseract` is on PATH and `pytesseract` imports.
3. Nothing — `None`, not an exception. The extra is optional; the default
   install and the standard suite stay identical to today.

Parsers still receive bytes. Rendering is pymupdf, which already opens PDFs.
The indexer owns *when* this runs (after the four text waves).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from ..logger import get_logger
from .document import Block, BlockKind, ParsedDoc

log = get_logger("ingest.ocr")

VERSAO = "ocr:1"
"""Own parser_version so an OCR engine change re-parses scans, not text PDFs."""

# Test hook: (numpy image) -> text. Survives missing RapidOCR in the standard suite.
motor_imagem: Callable | None = None


@dataclass(frozen=True)
class PaginaTexto:
    numero: int
    texto: str


def backend_disponivel() -> str | None:
    """Which engine would run. `None` = OCR is a no-op this install."""
    if motor_imagem is not None or os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is not None:
        return "teste"
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    else:
        return "rapidocr"
    import shutil

    if shutil.which("tesseract"):
        try:
            import pytesseract  # noqa: F401
        except Exception:  # noqa: BLE001
            return None
        return "tesseract"
    return None


def _imagens_das_paginas(dados: bytes):
    """Rasterise each PDF page. Copy the buffer — pymupdf reuses it."""
    import numpy as np
    import pymupdf

    documento = pymupdf.open(stream=dados, filetype="pdf")
    imagens = []
    try:
        for pagina in documento:
            pix = pagina.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            imagens.append(arr.copy())
    finally:
        documento.close()
    return imagens


_rapid: object | None = None


def _texto_rapidocr(imagem) -> str:  # noqa: ANN001
    global _rapid
    from rapidocr_onnxruntime import RapidOCR

    if _rapid is None:
        _rapid = RapidOCR()
    saida = _rapid(imagem)
    linhas = saida[0] if isinstance(saida, tuple) else saida
    if not linhas:
        return ""
    partes: list[str] = []
    for item in linhas:
        if isinstance(item, dict) and item.get("text"):
            partes.append(str(item["text"]))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            partes.append(str(item[1]))
    return "\n".join(p for p in partes if p.strip())


def _texto_tesseract(imagem) -> str:  # noqa: ANN001
    import pytesseract
    from PIL import Image

    pil = Image.fromarray(imagem)
    return (pytesseract.image_to_string(pil, lang="por+eng") or "").strip()


def _texto_de(imagem) -> str:  # noqa: ANN001
    fake = os.environ.get("SEGUNDOCEREBRO_OCR_FAKE")
    if fake is not None:
        return fake.strip()
    if motor_imagem is not None:
        return (motor_imagem(imagem) or "").strip()
    backend = backend_disponivel()
    if backend == "rapidocr":
        return _texto_rapidocr(imagem)
    if backend == "tesseract":
        return _texto_tesseract(imagem)
    return ""


def ocr_pdf(dados: bytes) -> list[PaginaTexto] | None:
    """OCR every page. `None` if no backend; empty list if the engine saw nothing."""
    if backend_disponivel() is None:
        return None
    try:
        imagens = _imagens_das_paginas(dados)
    except Exception as exc:  # noqa: BLE001 — a bad scan must not kill the wave
        log.warning("OCR não rasterizou o PDF: %s", exc)
        return None
    paginas: list[PaginaTexto] = []
    for i, imagem in enumerate(imagens, start=1):
        try:
            texto = _texto_de(imagem)
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR falhou na página %d: %s", i, exc)
            texto = ""
        paginas.append(PaginaTexto(numero=i, texto=texto))
    return paginas


def doc_de_ocr(dados: bytes, nome: str) -> ParsedDoc | None:
    """ParsedDoc with one block per page that yielded text. `None` if OCR is off."""
    paginas = ocr_pdf(dados)
    if paginas is None:
        return None
    blocos = [
        Block(
            heading_path=(),
            text=p.texto,
            locator=f"p. {p.numero}",
            kind=BlockKind.TEXT,
        )
        for p in paginas
        if p.texto.strip()
    ]
    if not blocos:
        return None
    backend = backend_disponivel() or "ocr"
    return ParsedDoc(
        name=nome,
        blocks=tuple(blocos),
        meta={
            "formato": "pdf",
            "fonte": "ocr",
            "backend": backend,
            "parser": VERSAO,
            "paginas": str(len(paginas)),
            "suspeita": "digitalizado",
        },
    )
