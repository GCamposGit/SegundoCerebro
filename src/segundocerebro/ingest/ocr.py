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
    except Exception:  # noqa: BLE001 — probe de import: extra [ocr] ausente é no-op
        pass
    else:
        return "rapidocr"
    import shutil

    if shutil.which("tesseract"):
        try:
            import pytesseract  # noqa: F401
        except Exception:  # noqa: BLE001 — probe de import: pytesseract ausente
            return None
        return "tesseract"
    return None


DPI_OCR = 144
"""Production raster: 72 × 2. F4-O.2b: a 10 pt identifier is read at 72 dpi
too, so 200 dpi is not the lever — keep the current matrix."""


def _teto_ocr_mb() -> int:
    from ..index.orcamento import derivar, medir, teto_ram_pagina_ocr_mb

    return teto_ram_pagina_ocr_mb(derivar(medir()))


def _dpi_cabivel(pagina, teto_mb: int, dpi_alvo: float = DPI_OCR) -> float:  # noqa: ANN001
    """Drop dpi so one pixmap fits in the parse budget. Never below 72."""
    rect = pagina.rect
    bytes_a_1dpi = max(1.0, (float(rect.width) / 72.0) * (float(rect.height) / 72.0) * 3.0)
    teto = max(1, int(teto_mb)) * 1024 * 1024
    max_dpi = (teto / bytes_a_1dpi) ** 0.5
    return max(72.0, min(float(dpi_alvo), max_dpi))


def _iter_rasters(dados: bytes, *, teto_mb: int | None = None):
    """Yield `(page_number, rgb_array)` for pages that need OCR, one at a time.

    The list form copied every pixmap; an 80-page scan at 200 dpi is ~1 GB.
    """
    import numpy as np
    import pymupdf

    from .parsers.pdf import pagina_precisa_ocr

    teto = teto_mb if teto_mb is not None else _teto_ocr_mb()
    documento = pymupdf.open(stream=dados, filetype="pdf")
    try:
        for i, pagina in enumerate(documento, start=1):
            texto = pagina.get_text() or ""
            if not pagina_precisa_ocr(pagina, texto):
                continue
            dpi = _dpi_cabivel(pagina, teto)
            pix = pagina.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n).copy()
            pix = None
            yield i, arr
    finally:
        documento.close()


def _imagens_das_paginas(dados: bytes):
    """Materialise rasters. One-page tests still use this; production iterates."""
    return [arr for _, arr in _iter_rasters(dados)]


_rapid: object | None = None


def _texto_rapidocr(imagem) -> str:  # noqa: ANN001
    global _rapid
    from rapidocr_onnxruntime import RapidOCR

    if _rapid is None:
        _rapid = RapidOCR()
    # rapidocr-onnxruntime 1.3–1.4: (linhas, elapsed).
    # linhas = [[box, text, confidence], ...] | None. Pinned by
    # tests/test_ocr_motor.py (marker `ocr`). A v2 of the extra is out of the
    # pin (`<2` in pyproject); a silent shape change breaks that test, not
    # a 10 GB corpus.
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


def ocr_pdf(dados: bytes, *, teto_mb: int | None = None) -> list[PaginaTexto] | None:
    """OCR pages that need it. `None` if no backend; empty if the engine saw nothing.

    Native pages are skipped (same detector as the PDF parser). One pixmap
    at a time, sized to the parse RAM ceiling.
    """
    if backend_disponivel() is None:
        return None
    paginas: list[PaginaTexto] = []
    try:
        for i, imagem in _iter_rasters(dados, teto_mb=teto_mb):
            try:
                texto = _texto_de(imagem)
            except Exception as exc:  # noqa: BLE001 — laço de onda: página de scan hostil não mata o OCR do arquivo
                log.warning("OCR falhou na página %d: %s", i, exc)
                texto = ""
            del imagem
            paginas.append(PaginaTexto(numero=i, texto=texto))
    except Exception as exc:  # noqa: BLE001 — a bad scan must not kill the wave
        log.warning("OCR não rasterizou o PDF: %s", exc)
        return None
    return paginas


def _numero_do_locator(locator: str) -> int:
    partes = (locator or "").split()
    try:
        return int(partes[-1])
    except (ValueError, IndexError):
        return 0


def doc_de_ocr(
    dados: bytes, nome: str, nativo: ParsedDoc | None = None
) -> ParsedDoc | None:
    """ParsedDoc: native blocks kept, OCR blocks only for photo pages.

    `None` if OCR is off or produced nothing — the caller then keeps the
    cheap parse, which is what mixed PDFs need.
    """
    paginas = ocr_pdf(dados)
    if paginas is None:
        return None
    blocos_ocr = [
        Block(
            heading_path=(),
            text=p.texto,
            locator=f"p. {p.numero}",
            kind=BlockKind.TEXT,
        )
        for p in paginas
        if p.texto.strip()
    ]
    if not blocos_ocr:
        return None
    ocr_paginas = {p.numero for p in paginas}
    nativos = [
        b
        for b in (nativo.blocks if nativo is not None else ())
        if _numero_do_locator(b.locator) not in ocr_paginas
    ]
    blocos = sorted(
        (*nativos, *blocos_ocr),
        key=lambda b: _numero_do_locator(b.locator),
    )
    backend = backend_disponivel() or "ocr"
    n_paginas = (nativo.meta.get("paginas") if nativo is not None else None) or str(
        max((p.numero for p in paginas), default=len(paginas))
    )
    meta = {
        "formato": "pdf",
        "fonte": "ocr",
        "backend": backend,
        "parser": VERSAO,
        "paginas": str(n_paginas),
        "suspeita": "digitalizado",
    }
    if nativo is not None:
        for chave in ("motor", "paginas_ocr", "sumario_nativo"):
            if nativo.meta.get(chave):
                meta[chave] = nativo.meta[chave]
    return ParsedDoc(name=nome, blocks=tuple(blocos), meta=meta)
