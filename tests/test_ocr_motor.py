"""F4-O.1: RapidOCR, on the production raster, reads a planted identifier.

O.0 is green against a fake engine (`SEGUNDOCEREBRO_OCR_FAKE`). This file
loads the real `rapidocr-onnxruntime` extra, rasterises known VCE text as an
image-only PDF, and checks the identifier comes back exactly. Mock of the
engine does not count.

Marker `ocr` — outside the default suite and CI (`py -m pytest -m ocr`).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.ocr

pytest.importorskip("rapidocr_onnxruntime")

from rapidocr_onnxruntime import RapidOCR  # noqa: E402

from segundocerebro.ingest.ocr import (  # noqa: E402
    _imagens_das_paginas,
    _texto_rapidocr,
    backend_disponivel,
    doc_de_ocr,
)

IDENTIFICADOR = "NN-VCE-001"
TEXTO_PLANTADO = f"Contrato {IDENTIFICADOR} da Varzea Clara Energia."


def pdf_scan_do_texto(texto: str) -> bytes:
    """A4 page whose only content is a pixmap of `texto` — no text layer."""
    import pymupdf

    origem = pymupdf.open()
    pagina = origem.new_page(width=595, height=842)
    pagina.insert_text((72, 140), texto, fontsize=18, fontname="helv")
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    origem.close()

    destino = pymupdf.open()
    pagina = destino.new_page(width=595, height=842)
    pagina.insert_image(pagina.rect, pixmap=pix)
    dados = destino.tobytes()
    destino.close()
    return dados


@pytest.fixture
def scan_vce() -> bytes:
    return pdf_scan_do_texto(TEXTO_PLANTADO)


def test_fixture_scan_nao_tem_camada_de_texto(scan_vce: bytes) -> None:
    """If this fails we are testing the PDF parser, not the OCR engine."""
    import pymupdf

    doc = pymupdf.open(stream=scan_vce, filetype="pdf")
    try:
        assert doc[0].get_text().strip() == ""
        assert doc[0].get_images()
    finally:
        doc.close()


def test_api_rapidocr_1_4_devolve_tupla_de_linhas(scan_vce: bytes) -> None:
    """Pin the extra's return shape so a silent API drift breaks here, cheap.

    `rapidocr-onnxruntime` 1.3–1.4: `(linhas, elapsed)`.
    Each line is `[box, text, confidence]`. `_texto_rapidocr` reads item[1].
    """
    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    imagens = _imagens_das_paginas(scan_vce)
    assert len(imagens) == 1
    saida = RapidOCR()(imagens[0])
    assert isinstance(saida, tuple) and len(saida) == 2
    linhas, _elapsed = saida
    assert isinstance(linhas, list) and linhas
    primeira = linhas[0]
    assert isinstance(primeira, list) and len(primeira) >= 2
    assert isinstance(primeira[1], str)
    assert IDENTIFICADOR in primeira[1]


def test_rapidocr_recupera_identificador_plantado(scan_vce: bytes) -> None:
    """Binary gate: the identifier appears exactly, one page, one file.

    Production raster (`Matrix(2, 2)`), real engine, no `OCR_FAKE`.
    Identifier missing ⇒ hypothesis refuted. Another engine is another package.
    """
    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    assert backend_disponivel() == "rapidocr"
    via = _texto_rapidocr(_imagens_das_paginas(scan_vce)[0])
    assert IDENTIFICADOR in via

    doc = doc_de_ocr(scan_vce, "oficio-vce.pdf")
    assert doc is not None
    assert doc.meta.get("fonte") == "ocr"
    assert doc.meta.get("backend") == "rapidocr"
    texto = " ".join(b.text for b in doc.blocks)
    assert IDENTIFICADOR in texto
    assert any(b.locator == "p. 1" for b in doc.blocks)
