"""R1.2: scanned PDFs become chunks after the text waves, not instead of them."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.ocr import VERSAO, backend_disponivel, doc_de_ocr
from segundocerebro.ingest.reader import parse_file
from segundocerebro.index.indexer import indexar
from segundocerebro.index.isolamento import timeout_para
from segundocerebro.index.orcamento import medir
from segundocerebro.index.store import Store
from tests.falsos import DIM, EmbedderFalso, bytes_pdf, bytes_pdf_misto, config_de_raiz

SINAIS_DE_RECURSO = (
    "subprocesso morreu",
    "timeout",
    "memory",
    "memória",
    "openblas",
    "allocation",
    "cannot allocate",
)
"""When the isolated parse child dies of RAM, the product quarantines — that is
success, not a red suite. Measured 27/08/2026 on the notebook: 2.7 GB free →
OpenBLAS abort → status `erro`; RAM freed → the same tests `ok`. The suite
verdict was the machine window. Same class as F4-R (regime not recorded)."""

PISO_RAM_OCR_MB = 4096
"""Abaixo disto esta suíte **não tem veredito** sobre OCR, e diz isso.

A lista acima cobria metade da superfície, e é a terceira vez que essa forma
aparece neste repositório. Ela trata o caso em que o filho de parse morre
**dizendo** que morreu de recurso — aí há linha de quarentena e status `erro`. O
outro caso é silencioso: sob pressão de memória o `pymupdf` falha ao carregar
dentro do filho e o erro chega como `ModuleNotFoundError: No module named
'mupdf'`, que o produto classifica como *sem parser*. O documento fica `vazio`,
`digitalizado` nunca é marcado, a fila de OCR sai vazia e `progresso.ocr` é 0 —
sem uma linha dizendo que faltou memória.

Medido em 29/08/2026 neste notebook (16 GB), cinco passadas de
`py -m pytest tests/test_ocr.py` em sequência: **2 reprovaram com 3,5–3,6 GB
livres e 3 passaram com ~3,9 GB**, sem uma linha de código mudar entre elas. O
piso de 4 GB é essa medição mais a de 27/08 (2,7 GB → abort), com folga.

Acima do piso, `vazio` continua reprovando: é regressão de verdade e o sinal não
se perde. Abaixo, o teste **pula com o número na mensagem** — mesmo desenho de
`tests/test_baseline.py` com o `census.toml`, e a lição do `F4-R` aplicada à
suíte: braço sem regime de máquina gravado mede a janela, não o braço.

O comportamento silencioso do produto sob pressão de memória é da `F4-O.3`, que
está bloqueada. Este arquivo não o conserta — recusa-se a fingir que o mediu."""


def regime_da_maquina() -> str:
    """A janela em que esta passada rodou, para a mensagem de falha carregá-la."""
    r = medir()
    return (
        f"RAM livre {r.ram_livre_mb} MB de {r.ram_total_mb} MB · "
        f"{r.nucleos} núcleos · {r.gpus} GPU(s)"
    )


def sem_veredito_de_ocr(detalhe: str) -> None:
    """Pula quando a janela da máquina está abaixo do piso; caso contrário, segue.

    Chamado nos dois lugares onde a pressão de memória se disfarça de resultado:
    o documento que fica `vazio` sem linha de quarentena, e a fase de OCR que não
    produz nada num PDF misto — que tem chunks nativos e por isso parece `ok`.
    """
    if medir().ram_livre_mb < PISO_RAM_OCR_MB:
        pytest.skip(
            f"sem veredito de OCR nesta janela: {regime_da_maquina()}, abaixo do piso de "
            f"{PISO_RAM_OCR_MB} MB. {detalhe} — ver PISO_RAM_OCR_MB."
        )


def ocr_produziu_texto_ou_declarou_recurso(store: Store, rel: str, progresso) -> bool:  # noqa: ANN001
    """True if OCR committed chunks. False if the child died of resource/timeout.

    Any other status fails the test: silent EMPTY or missing row would be the
    lie this helper exists to refuse.
    """
    estado = store.estado_documento(rel)
    assert estado is not None, f"{rel} saiu do registro"
    if estado.status == "ok" and estado.n_chunks >= 1:
        return True
    if estado.status != "erro":
        sem_veredito_de_ocr(f"{rel} ficou {estado.status!r}")
        pytest.fail(
            f"{rel} ficou {estado.status!r} — nem ok com texto nem erro honesto. "
            f"Regime: {regime_da_maquina()} (acima do piso de {PISO_RAM_OCR_MB} MB, "
            "então isto é regressão e não a janela da máquina)."
        )
    item = store.quarentena_de(rel)
    assert item is not None, f"{rel} em erro sem linha de quarentena"
    motivo = (item.motivo or "").lower()
    assert any(s in motivo for s in SINAIS_DE_RECURSO), (
        f"{rel} em erro por motivo que não é recurso: {item.motivo!r}"
    )
    assert progresso.quarentena >= 1
    return False


TEXTO_VCE = "Contrato NN-VCE-001 da Varzea Clara Energia."


def test_sem_motor_ocr_e_noop() -> None:
    """The extra is optional. Missing backend is None, not an exception."""
    assert backend_disponivel() in {None, "rapidocr", "tesseract", "teste"}
    if backend_disponivel() not in {None, "teste"}:
        return
    assert doc_de_ocr(bytes_pdf(texto=None, com_imagem=True), "x.pdf") is None


def test_parse_sem_ocr_continua_vazio_no_digitalizado(tmp_path: Path) -> None:
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    resultado = parse_file(str(alvo), ocr=False)
    assert resultado.status is ParseStatus.EMPTY
    assert resultado.natureza is not None
    assert resultado.natureza.digitalizado


def test_parse_com_ocr_falso_vira_trechos(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None
    assert resultado.doc.meta.get("fonte") == "ocr"
    assert resultado.doc.meta.get("parser") == VERSAO
    assert any(TEXTO_VCE in b.text for b in resultado.doc.blocks)
    assert any(b.locator.startswith("p. ") for b in resultado.doc.blocks)


def test_pdf_com_texto_nao_entra_no_ocr(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    chamou = []
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    monkeypatch.setattr(
        "segundocerebro.ingest.reader._ocr_pdf",
        lambda *a, **k: chamou.append(1) or None,
    )
    alvo = tmp_path / "contrato.pdf"
    alvo.write_bytes(bytes_pdf(texto="Contrato 4600009999 com a Nimbus Tecnologia."))
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert chamou == []
    assert "4600009999" in resultado.doc.blocks[0].text


def test_timeout_ocr_soma_no_teto() -> None:
    assert timeout_para(0, "x.pdf") == 60.0
    assert timeout_para(0, "x.pdf", ocr=True) == 180.0


def test_indexar_ocr_depois_do_texto(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """Acceptance: text files are searchable before the scan is OCRed.

    The OCR phase runs after the parse loop. A .md next to a scan is committed
    first; the scan is still `vazio` until the second phase.
    """
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "politica.md").write_text("# Politica VCE\nUso aceitavel de IA.\n", encoding="utf-8")
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))

    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=True,
    )
    assert not progresso.interrompido
    assert store.estado_documento("politica.md").status == "ok"
    if not ocr_produziu_texto_ou_declarou_recurso(store, "escaneado.pdf", progresso):
        store.fechar()
        return
    escaneado = store.estado_documento("escaneado.pdf")
    assert escaneado is not None
    assert escaneado.parser == VERSAO
    assert progresso.ocr >= 1
    texto = " ".join(c.texto for c in store.chunks_de("escaneado.pdf"))
    assert TEXTO_VCE in texto
    store.fechar()


def test_indexar_sem_ocr_nao_mexe_no_digitalizado(tmp_path: Path) -> None:
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))
    store = Store(tmp_path / "indice", DIM)
    indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=False,
    )
    estado = store.estado_documento("escaneado.pdf")
    assert estado is not None
    assert estado.status == "vazio"
    assert estado.n_chunks == 0
    assert store.documentos_para_ocr(VERSAO) == [("escaneado.pdf", "teste")]
    store.fechar()


def test_pdf_misto_nativa_nao_passa_pelo_ocr(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """O.2a: photo page becomes a chunk; native page never hits the engine."""
    chamadas: list[int] = []

    def fake(imagem) -> str:  # noqa: ANN001
        chamadas.append(1)
        return "SCAN-VCE-001"

    monkeypatch.setattr("segundocerebro.ingest.ocr.motor_imagem", fake)
    alvo = tmp_path / "oficio.pdf"
    alvo.write_bytes(bytes_pdf_misto())
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None
    assert len(chamadas) == 1
    texto = " ".join(b.text for b in resultado.doc.blocks)
    assert "4600009999" in texto
    assert "SCAN-VCE-001" in texto
    locators = {b.locator for b in resultado.doc.blocks}
    assert "p. 1" in locators
    assert "p. 2" in locators


def test_indexar_misto_entra_na_fila_ocr(tmp_path: Path) -> None:
    """Without --ocr the native page is searchable and the photo waits in queue."""
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "oficio.pdf").write_bytes(bytes_pdf_misto())
    store = Store(tmp_path / "indice", DIM)
    indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=False,
    )
    estado = store.estado_documento("oficio.pdf")
    assert estado is not None
    assert estado.status == "ok"
    assert estado.n_chunks >= 1
    texto = " ".join(c.texto for c in store.chunks_de("oficio.pdf"))
    assert "4600009999" in texto
    assert store.documentos_para_ocr(VERSAO) == [("oficio.pdf", "teste")]
    store.fechar()


def test_ocr_rasteriza_uma_pagina_por_vez(monkeypatch) -> None:  # noqa: ANN001
    """O.2c: N scan pages, at most one pixmap alive."""
    import pymupdf

    from segundocerebro.ingest.ocr import ocr_pdf

    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    doc = pymupdf.open()
    for _ in range(8):
        pagina = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
        pix.set_rect(pix.irect, (180, 180, 180))
        pagina.insert_image(pymupdf.Rect(0, 0, 500, 700), pixmap=pix)
    dados = doc.tobytes()
    doc.close()

    vivo: list[object] = []
    pico = [0]
    from segundocerebro.ingest import ocr as mod

    original = mod._iter_rasters

    def envolto(dados_pdf, *, teto_mb=None):  # noqa: ANN001
        for item in original(dados_pdf, teto_mb=teto_mb):
            vivo.append(item)
            pico[0] = max(pico[0], len(vivo))
            yield item
            vivo.pop()

    monkeypatch.setattr(mod, "_iter_rasters", envolto)
    paginas = ocr_pdf(dados, teto_mb=256)
    assert paginas is not None
    assert len(paginas) == 8
    assert pico[0] == 1


def test_dpi_ocr_respeita_teto_de_ram() -> None:
    """A page bigger than the parse budget drops to 72 dpi, never below."""
    import pymupdf

    from segundocerebro.ingest.ocr import DPI_OCR, _dpi_cabivel

    doc = pymupdf.open()
    pagina = doc.new_page(width=595, height=842)
    try:
        assert _dpi_cabivel(pagina, teto_mb=1) == 72.0
        assert _dpi_cabivel(pagina, teto_mb=256) == DPI_OCR
    finally:
        doc.close()


def test_indexar_misto_com_ocr_junta_as_paginas(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # parse_isolado runs in a child: a monkeypatch of motor_imagem does not
    # survive spawn. The env var does — same contract as the O.0 suite.
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", "SCAN-VCE-001")
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "oficio.pdf").write_bytes(bytes_pdf_misto())
    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=True,
    )
    if not ocr_produziu_texto_ou_declarou_recurso(store, "oficio.pdf", progresso):
        store.fechar()
        return
    if progresso.ocr < 1:
        # `ok` com chunks nativos e OCR zerado: o PDF misto esconde a pressão de
        # memória atrás das páginas que o parser nativo já tinha lido.
        sem_veredito_de_ocr("a fase de OCR não produziu nada num PDF misto")
    assert progresso.ocr >= 1
    texto = " ".join(c.texto for c in store.chunks_de("oficio.pdf"))
    assert "4600009999" in texto
    assert "SCAN-VCE-001" in texto
    assert store.documentos_para_ocr(VERSAO) == []
    store.fechar()


def test_config_ocr_desligado_por_padrao(tmp_path: Path) -> None:
    from segundocerebro.config import carregar

    caminho = tmp_path / "config.toml"
    caminho.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is False
    caminho.write_text('[indexacao]\nocr = true\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is True


def test_teste_de_ocr_que_indexa_aceita_falha_de_recurso() -> None:
    """The next `indexar(..., ocr=True)` test that asserts ok-only fails here.

    F4-O.2 added a second test with the same assumption the first already had.
    The checklist is this helper, not a list of two names.
    """
    fonte = Path(__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    faltando: list[str] = []
    for no in arvore.body:
        if not isinstance(no, ast.FunctionDef) or not no.name.startswith("test_"):
            continue
        trecho = ast.get_source_segment(fonte, no) or ""
        if "indexar(" not in trecho or "ocr=True" not in trecho:
            continue
        if "ocr_produziu_texto_ou_declarou_recurso" not in trecho:
            faltando.append(no.name)
    assert not faltando, (
        "teste de OCR que indexa e afirma o caminho feliz sem aceitar "
        "quarentena por recurso. Use ocr_produziu_texto_ou_declarou_recurso, "
        "senão a suíte mede a janela de memória outra vez: "
        + ", ".join(faltando)
    )
