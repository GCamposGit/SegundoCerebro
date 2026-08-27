"""R1.2: scanned PDFs become chunks after the text waves, not instead of them."""

from __future__ import annotations

from pathlib import Path

from segundocerebro.census import Config, RootSpec
from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.ocr import VERSAO, backend_disponivel, doc_de_ocr
from segundocerebro.ingest.reader import parse_file
from segundocerebro.index.indexer import indexar
from segundocerebro.index.isolamento import timeout_para
from segundocerebro.index.store import Store
from tests.test_index import DIM, EmbedderFalso
from tests.test_ingest import bytes_pdf


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
        Config(roots=[RootSpec(name="teste", path=raiz)]),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=True,
    )
    assert not progresso.interrompido
    assert store.estado_documento("politica.md").status == "ok"
    escaneado = store.estado_documento("escaneado.pdf")
    assert escaneado is not None
    assert escaneado.status == "ok"
    assert escaneado.parser == VERSAO
    assert escaneado.n_chunks >= 1
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
        Config(roots=[RootSpec(name="teste", path=raiz)]),
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


def test_config_ocr_desligado_por_padrao(tmp_path: Path) -> None:
    from segundocerebro.config import carregar

    caminho = tmp_path / "config.toml"
    caminho.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is False
    caminho.write_text('[indexacao]\nocr = true\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is True
