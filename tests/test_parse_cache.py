from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, ParsedDoc
from segundocerebro.index.isolamento import parse_isolado
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import Store
from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.parse_store import (
    ROTA_LIBREOFFICE,
    ROTA_NATIVA,
    Chave,
    ParseStore,
    rota_de,
)
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.ingest.reader import parse_file
from tests.falsos import DIM, EmbedderFalso, bytes_pdf, corpus


TEXTO = "Política de IA\n\nO contrato 4600009999 continua vigente."


def _parser_que_nao_pode_rodar(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
    raise AssertionError("o parser foi chamado apesar do hit no parse store")


def test_parse_file_grava_e_reaproveita_antes_do_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indice = tmp_path / "indice"
    alvo = tmp_path / "politica.txt"
    alvo.write_text(TEXTO, encoding="utf-8")

    primeiro = parse_file(str(alvo), indice=indice)
    assert primeiro.status is ParseStatus.OK
    assert ParseStore(indice).estatisticas()["entradas"] == 1

    monkeypatch.setitem(
        __import__("segundocerebro.ingest.parsers", fromlist=["_REGISTRY"])._REGISTRY,
        ".txt",
        _parser_que_nao_pode_rodar,
    )
    segundo = parse_file(str(alvo), indice=indice)

    assert segundo.status is ParseStatus.OK
    assert segundo.sha256 == primeiro.sha256
    assert segundo.doc == primeiro.doc
    assert segundo.natureza == primeiro.natureza


def test_hash_novo_nao_reaproveita_entrada_velha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indice = tmp_path / "indice"
    alvo = tmp_path / "politica.txt"
    alvo.write_text(TEXTO, encoding="utf-8")
    primeiro = parse_file(str(alvo), indice=indice)
    alvo.write_text(TEXTO + "\nAlterado.", encoding="utf-8")

    chamadas = []

    def parser_novo(dados: bytes, nome: str):
        chamadas.append((dados, nome))
        return primeiro.doc

    monkeypatch.setitem(
        __import__("segundocerebro.ingest.parsers", fromlist=["_REGISTRY"])._REGISTRY,
        ".txt",
        parser_novo,
    )
    segundo = parse_file(str(alvo), indice=indice)

    assert segundo.status is ParseStatus.OK
    assert segundo.sha256 != primeiro.sha256
    assert len(chamadas) == 1
    assert ParseStore(indice).estatisticas()["entradas"] == 2


def test_parse_isolado_encaminha_o_indice_ao_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indice = tmp_path / "indice"
    alvo = tmp_path / "ata.txt"
    alvo.write_text(TEXTO, encoding="utf-8")
    primeiro = parse_isolado(str(alvo), indice=indice)

    monkeypatch.setitem(
        __import__("segundocerebro.ingest.parsers", fromlist=["_REGISTRY"])._REGISTRY,
        ".txt",
        _parser_que_nao_pode_rodar,
    )
    segundo = parse_isolado(str(alvo), indice=indice)

    assert primeiro.status is segundo.status is ParseStatus.OK
    assert segundo.doc == primeiro.doc


def test_rota_ocr_nao_vaza_para_a_passada_nativa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indice = tmp_path / "indice"
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", "Contrato OCR 4600009999")

    por_ocr = parse_file(str(alvo), indice=indice, ocr=True)
    nativo = parse_file(str(alvo), indice=indice, ocr=False)

    assert por_ocr.status is ParseStatus.OK
    assert por_ocr.doc.meta.get("fonte") == "ocr"
    assert nativo.status is ParseStatus.EMPTY
    assert nativo.doc.meta.get("fonte") != "ocr"
    assert ParseStore(indice).estatisticas()["entradas"] == 2

    monkeypatch.setattr(
        "segundocerebro.ingest.reader._ocr_pdf",
        _parser_que_nao_pode_rodar,
    )
    quente = parse_file(str(alvo), indice=indice, ocr=True)
    assert quente.parse_store_hit
    assert quente.doc == por_ocr.doc


def test_rebuild_de_modelo_usa_store_e_preserva_os_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indice = tmp_path / "indice"
    store = Store(indice, DIM)
    cfg = corpus(tmp_path / "corpus")
    indexar(cfg, store, EmbedderFalso(model_id="modelo-a:8"), parse_workers=1)
    antes = {
        path: tuple((c.ordinal, c.trilha, c.locator, c.kind, c.texto) for c in store.chunks_de(path))
        for path in ("contrato.md", "Política de IA/PO-ACME-007_Política_IA_v8.md")
    }

    monkeypatch.setitem(
        __import__("segundocerebro.ingest.parsers", fromlist=["_REGISTRY"])._REGISTRY,
        ".md",
        _parser_que_nao_pode_rodar,
    )
    progresso = indexar(
        cfg,
        store,
        EmbedderFalso(model_id="modelo-b:8"),
        parse_workers=1,
    )
    depois = {
        path: tuple((c.ordinal, c.trilha, c.locator, c.kind, c.texto) for c in store.chunks_de(path))
        for path in antes
    }

    assert progresso.indexados == 2
    assert progresso.parse_store_hits == progresso.parse_store_consultas == 3
    assert "parse store 100% (3/3)" in progresso.resumo()
    assert depois == antes
    assert store.estatisticas()["modelos"] == ["modelo-b:8"]
    store.fechar()


def test_falha_ao_gravar_cache_nao_invalida_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alvo = tmp_path / "ata.txt"
    alvo.write_text(TEXTO, encoding="utf-8")

    def sem_disco(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise OSError("disco indisponível")

    monkeypatch.setattr(ParseStore, "gravar", sem_disco)
    resultado = parse_file(str(alvo), indice=tmp_path / "indice")

    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None


def test_metadados_reais_do_libreoffice_selecionam_a_rota_externa() -> None:
    assert rota_de({"convertido": "libreoffice"}) == ROTA_LIBREOFFICE
    assert rota_de({"recalculado": "libreoffice"}) == ROTA_LIBREOFFICE


def _gravar_nativo(indice: Path, extensao: str, sha256: str, **meta: str) -> None:
    doc = ParsedDoc(
        name=f"legado{extensao}",
        blocks=(Block(heading_path=(), text="conteúdo nativo"),),
        meta=meta,
    )
    chave = Chave(
        sha256=sha256,
        parser=parser_version_for(extensao),
        rota=ROTA_NATIVA,
    )
    ParseStore(indice).gravar(chave, renderizar(doc))


def test_instalar_libreoffice_invalida_cache_nativo_de_legado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from segundocerebro.ingest import parse_cache

    indice = tmp_path / "indice"
    sha256 = "a" * 64
    _gravar_nativo(indice, ".doc", sha256)
    monkeypatch.setattr(
        parse_cache,
        "assinatura_do_motor",
        lambda rota: "soffice:novo" if rota == ROTA_LIBREOFFICE else "",
    )

    resultado = parse_cache.obter_resultado(
        indice,
        path=str(tmp_path / "legado.doc"),
        dados=b"ole",
        sha256=sha256,
        ocr=False,
    )

    assert resultado is None, "o miss força a nova conversão pelo LibreOffice"


def test_instalar_libreoffice_so_invalida_planilha_que_precisa_recalculo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from segundocerebro.ingest import parse_cache

    indice = tmp_path / "indice"
    precisa, pronta = "b" * 64, "c" * 64
    _gravar_nativo(indice, ".xlsx", precisa, sem_valor_em_cache="1")
    _gravar_nativo(indice, ".xlsx", pronta)
    monkeypatch.setattr(
        parse_cache,
        "assinatura_do_motor",
        lambda rota: "soffice:novo" if rota == ROTA_LIBREOFFICE else "",
    )

    kwargs = {"indice": indice, "path": str(tmp_path / "dados.xlsx"), "dados": b"zip", "ocr": False}
    assert parse_cache.obter_resultado(sha256=precisa, **kwargs) is None
    assert parse_cache.obter_resultado(sha256=pronta, **kwargs).parse_store_hit
