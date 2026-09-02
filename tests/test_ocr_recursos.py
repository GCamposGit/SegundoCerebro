"""Q15.b: native allocation failures must not masquerade as empty scans."""

import pytest

from segundocerebro.ingest import ocr
from segundocerebro.ingest.document import FalhaDeAmbiente
from segundocerebro.ingest.ocr_recursos import falha_de_memoria


def erro_onnx(mensagem="Status Message: bad allocation"):
    tipo = type("RuntimeException", (Exception,), {
        "__module__": "onnxruntime.capi.onnxruntime_pybind11_state",
    })
    original = tipo(mensagem)
    envelope = RuntimeError("wrapped inference failure")
    envelope.__cause__ = original
    return envelope


def motor_com_resultados(monkeypatch, resultados):
    monkeypatch.setattr(ocr, "backend_disponivel", lambda: "teste")
    monkeypatch.setattr(ocr, "_iter_rasters", lambda *_a, **_k: enumerate(resultados, 1))

    def texto(resultado):
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(ocr, "_texto_de", texto)


@pytest.mark.parametrize("restantes", [[], [""], [ValueError("invalid image")]])
def test_falha_nativa_sem_texto_nunca_e_vazio(monkeypatch, restantes):
    motor_com_resultados(monkeypatch, [erro_onnx(), *restantes])
    with pytest.raises(FalhaDeAmbiente, match="memória"):
        ocr.ocr_pdf(b"fixture")


def test_rasterizacao_sem_memoria_tambem_declara_recurso(monkeypatch):
    monkeypatch.setattr(ocr, "backend_disponivel", lambda: "teste")

    def quebrar(*_a, **_k):
        raise erro_onnx()

    monkeypatch.setattr(ocr, "_iter_rasters", quebrar)
    with pytest.raises(FalhaDeAmbiente, match="memória"):
        ocr.ocr_pdf(b"fixture")


@pytest.mark.parametrize("resultado", ["", ValueError("invalid image"), erro_onnx("invalid shape")])
def test_vazio_e_erros_sem_sinal_de_memoria_nao_sao_recurso(monkeypatch, resultado):
    motor_com_resultados(monkeypatch, [resultado])
    assert ocr.ocr_pdf(b"fixture") == [ocr.PaginaTexto(1, "")]


def test_pagina_gorda_nao_apaga_texto_de_outras_paginas(monkeypatch):
    motor_com_resultados(monkeypatch, [erro_onnx(), "Contrato VCE"])
    assert ocr.ocr_pdf(b"fixture") == [ocr.PaginaTexto(1, ""), ocr.PaginaTexto(2, "Contrato VCE")]


@pytest.mark.parametrize("mensagem", [
    "Status Message: bad allocation", "std::bad_alloc",
    "Failed to allocate memory for requested buffer of size 5000",
    "Available memory of 16 is smaller than requested bytes of 32",
    "OUT OF MEMORY",
])
def test_assinaturas_onnx_de_alocacao(mensagem):
    assert falha_de_memoria(erro_onnx(mensagem))


@pytest.mark.parametrize("erro", [
    RuntimeError("bad allocation"), ValueError("out of memory"),
    erro_onnx("invalid input shape"), erro_onnx("invalid memory pattern"),
])
def test_texto_solto_ou_falha_de_operacao_nao_basta(erro):
    assert not falha_de_memoria(erro)


@pytest.mark.parametrize("codigo,esperado", [(-4, True), (-215, False), (None, False)])
def test_opencv_exige_codigo_de_memoria(codigo, esperado):
    tipo = type("error", (Exception,), {"__module__": "cv2", "code": codigo})
    assert falha_de_memoria(tipo("native failure")) is esperado


def test_cadeia_ciclica_termina_e_contexto_suprimido_nao_classifica():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert not falha_de_memoria(a)
    a.__cause__ = None
    a.__context__ = MemoryError()
    assert not falha_de_memoria(a)  # assigning a cause suppresses context
    a.__suppress_context__ = False
    assert falha_de_memoria(a)
    a.__cause__ = ValueError("explicit non-memory cause")
    assert not falha_de_memoria(a)


def test_cache_vazio_legado_nao_esconde_falha_nem_impede_recuperacao(tmp_path, monkeypatch):
    from segundocerebro.index.isolamento import parse_isolado
    from segundocerebro.ingest.document import MOTIVO_RECURSO, ParseStatus
    from segundocerebro.ingest.parse_store import ParseStore
    from tests.falsos import bytes_pdf

    alvo, indice = tmp_path / "scan.pdf", tmp_path / "indice"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    monkeypatch.setattr("segundocerebro.index.isolamento.deve_isolar", lambda _p: False)
    assert parse_isolado(str(alvo), indice=indice).status is ParseStatus.EMPTY
    motor_com_resultados(monkeypatch, [erro_onnx()])
    falha = parse_isolado(str(alvo), indice=indice, ocr=True)
    assert falha.status is ParseStatus.ERROR
    assert falha.detail.startswith(MOTIVO_RECURSO)
    assert ParseStore(indice).estatisticas()["entradas"] == 1  # only native EMPTY
    motor_com_resultados(monkeypatch, ["Contrato VCE"])
    recuperado = parse_isolado(str(alvo), indice=indice, ocr=True)
    assert recuperado.status is ParseStatus.OK
    assert not recuperado.parse_store_hit
    hit = parse_isolado(str(alvo), indice=indice, ocr=True)
    assert hit.parse_store_hit and hit.doc == recuperado.doc
