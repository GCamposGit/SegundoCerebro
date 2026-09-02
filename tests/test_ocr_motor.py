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


def _texto_em_dpi(fontsize: float, dpi: float) -> str:
    """Raster a 10 pt line at `dpi` and run RapidOCR. Not the production path."""
    import numpy as np
    import pymupdf

    origem = pymupdf.open()
    pagina = origem.new_page(width=595, height=842)
    pagina.insert_text((72, 140), TEXTO_PLANTADO, fontsize=fontsize, fontname="helv")
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    origem.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n).copy()
    saida = RapidOCR()(arr)
    linhas = saida[0] or []
    return " ".join(item[1] for item in linhas if isinstance(item, list) and len(item) >= 2)


def test_dpi_200_nao_e_alavanca_em_10pt() -> None:
    """O.2b: 10 pt Helvetica is read at 72 dpi too — 200 dpi is not the lever.

    Adopting 200 would cost RAM without buying recall on this fixture.
    Production raster stays 144 (`Matrix(2,2)`). Another size is another package.
    """
    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    assert IDENTIFICADOR in _texto_em_dpi(10, 72)
    assert IDENTIFICADOR in _texto_em_dpi(10, 200)


@pytest.mark.skipif(os.name != "nt", reason="Job Object is Windows-only")
@pytest.mark.parametrize("ram_mb", [560, 2048])
def test_scan_isolado_nunca_disfarca_falha_de_memoria(tmp_path, scan_vce, ram_mb):
    """Real child + real OCR. A small budget permits resource error, never EMPTY."""
    from segundocerebro.index.isolamento import parse_isolado
    from segundocerebro.ingest.document import MOTIVO_RECURSO, ParseStatus

    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    alvo = tmp_path / "oficio-vce.pdf"
    alvo.write_bytes(scan_vce)
    resultado = parse_isolado(str(alvo), ocr=True, ram_mb=ram_mb, timeout=60)
    if ram_mb == 560 and resultado.status is ParseStatus.ERROR:
        assert resultado.detail.startswith(MOTIVO_RECURSO), resultado.detail
    else:
        assert resultado.status is ParseStatus.OK, resultado.detail
        assert resultado.doc is not None
        assert IDENTIFICADOR in " ".join(b.text for b in resultado.doc.blocks)


def test_scan_branco_real_continua_vazio(tmp_path):
    from segundocerebro.index.isolamento import parse_isolado
    from segundocerebro.ingest.document import ParseStatus

    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    alvo = tmp_path / "branco.pdf"
    alvo.write_bytes(pdf_scan_do_texto(""))
    resultado = parse_isolado(str(alvo), ocr=True, timeout=60)
    assert resultado.status is ParseStatus.EMPTY, resultado.detail


@pytest.mark.skipif(os.name != "nt", reason="Job Object is Windows-only")
def test_indexador_real_quarentena_e_recupera_scan(tmp_path, scan_vce, store):
    """Only embeddings are fake: real scan/OCR/cache/registry and subprocess."""
    from segundocerebro.index.indexer import indexar
    from segundocerebro.index.quarentena import aposentado, por_recurso
    from segundocerebro.ingest.ocr import VERSAO
    from tests.falsos import EmbedderFalso, config_de_raiz

    assert os.environ.get("SEGUNDOCEREBRO_OCR_FAKE") is None
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "scan.pdf").write_bytes(scan_vce)
    cfg = config_de_raiz(raiz)
    opcoes = dict(publicar=False, reconciliar_ao_fim=False, parse_workers=1)
    indexar(cfg, store, EmbedderFalso(), ocr=True, ram_parse_mb=560, **opcoes)
    estado = store.estado_documento("scan.pdf")
    assert estado is not None and estado.status in {"ok", "erro"}
    if estado.status == "erro":
        item = store.quarentena_de("scan.pdf")
        assert item is not None and por_recurso(item.motivo) and not aposentado(item)
        assert "scan.pdf" in dict(store.documentos_para_ocr(VERSAO))
        store.limpar_quarentena("scan.pdf")  # avoid waiting for the backoff
        indexar(cfg, store, EmbedderFalso(), ocr=False, ram_parse_mb=560, **opcoes)
        assert store.estado_documento("scan.pdf").status == "erro"
    indexar(cfg, store, EmbedderFalso(), ocr=True, ram_parse_mb=2048, **opcoes)
    assert store.estado_documento("scan.pdf").status == "ok"
    assert store.quarentena_de("scan.pdf") is None
    assert "scan.pdf" not in dict(store.documentos_para_ocr(VERSAO))
    assert any(IDENTIFICADOR in c.texto for c in store.chunks_de("scan.pdf"))


def test_tipos_reais_e_envelope_do_backend():
    from onnxruntime.capi.onnxruntime_pybind11_state import RuntimeException
    from rapidocr_onnxruntime.utils.infer_engine import ONNXRuntimeError, OrtInferSession
    from segundocerebro.ingest.ocr_recursos import falha_de_memoria

    original = RuntimeException("Status Message: bad allocation")

    class Session:
        def run(self, *_a):
            raise original

    engine = OrtInferSession.__new__(OrtInferSession)
    engine.session = Session()
    engine.get_input_names = lambda: ["input"]
    engine.get_output_names = lambda: ["output"]
    with pytest.raises(ONNXRuntimeError) as capturada:
        engine(None)
    assert capturada.value.__cause__ is original
    assert falha_de_memoria(capturada.value)
