"""The measurement gate must reject fast but incomplete or mismatched runs."""

from copy import deepcopy
import json

import pymupdf
import pytest

from segundocerebro.repositorio import raiz

from . import parse_store_benchmark as bench
from .parse_store_corpus import gerar, manifesto, rasterizar


def observacoes():
    return [{"nome": f"{i:02d}-{braco}", "segundos": tempo,
             "assinatura": {"chunks": "iguais"}, "manifesto": {"vce.pdf": "hash"},
             "modelo": "real:1", "estado_antes": {"tomada": None},
             "estado_depois": {"tomada": None}, "etapas": [{"suspeito": 0}],
             "progresso": {"parse_store_consultas": 8, "parse_store_hits": hits,
                           "interrompido": False, "quarentena": 0, "pulados": 0}}
            for i in range(1, 7) for braco, tempo, hits in [("frio", 10, 0), ("quente", 1, 8)]]


def test_veredito_pareado_e_deterministico():
    obs = observacoes()
    resultado = bench.resumir(obs)
    assert resultado == bench.resumir(deepcopy(obs))
    assert resultado["hipotese_80pct"] == "confirmada"
    assert resultado["reducao_media"] == pytest.approx(0.9)
    assert resultado["ic95"] == pytest.approx([0.9, 0.9])
    for o in obs[1::2]:
        o["segundos"] = 3
    assert bench.resumir(obs)["hipotese_80pct"] == "refutada"


@pytest.mark.parametrize("campo,valor", [
    ("nome", "01-frio"), ("assinatura", {"chunks": "diferentes"}),
    ("manifesto", {}), ("modelo", "outro"), ("segundos", 0),
    ("segundos", float("nan")), ("segundos", float("inf")),
    ("etapas", [{"suspeito": 1}]), ("estado_depois", {"tomada": True}),
])
def test_recusa_contraste_invalido(campo, valor):
    obs = observacoes()
    obs[1][campo] = valor
    with pytest.raises(ValueError):
        bench.resumir(obs)


@pytest.mark.parametrize("campo,valor", [
    ("parse_store_hits", 0), ("parse_store_consultas", 0),
    ("interrompido", True), ("quarentena", 1), ("pulados", 1),
])
def test_cache_inativo_ou_rebuild_incompleto_nao_contam(campo, valor):
    obs = observacoes()
    obs[1]["progresso"][campo] = valor
    with pytest.raises(ValueError):
        bench.resumir(obs)


def test_nao_aceita_pares_incompletos_ou_nova_grade():
    for obs in (observacoes()[:-1], observacoes() + observacoes()[:2]):
        with pytest.raises(ValueError):
            bench.resumir(obs)


def test_fixture_scan_tem_imagem_com_texto_mas_nao_texto_embutido(tmp_path):
    original, destino = tmp_path / "texto.pdf", tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Contrato NN-VCE-001")
        doc.save(original)
    rasterizar(original, destino)
    with pymupdf.open(destino) as doc:
        assert not doc[0].get_text()
        assert doc[0].get_images()
    assert set(manifesto(tmp_path)) == {"texto.pdf", "scan.pdf"}


def test_resultado_nao_sobrescreve_arquivo_existente(tmp_path):
    arquivo = tmp_path / "resultado.json"
    bench.gravar(arquivo, {"a": 1})
    with pytest.raises(FileExistsError):
        bench.gravar(arquivo, {"a": 2})
    assert json.loads(arquivo.read_text()) == {"a": 1}


def test_worker_recusa_indice_existente(tmp_path):
    indice = tmp_path / "01-frio"
    indice.mkdir()
    (indice / "registro.db").touch()
    with pytest.raises(ValueError, match="já existe"):
        bench.worker(tmp_path, "01-frio")


@pytest.mark.parametrize("backend", [None, "teste"])
def test_sem_ocr_real_recusa_antes_de_gerar_corpus(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(bench, "backend_disponivel", lambda: backend)
    alvo = tmp_path / "experimento"
    with pytest.raises(RuntimeError, match="OCR real"):
        bench.rodar(alvo)
    assert not alvo.exists()


def test_gerador_nao_sobrescreve_destino_existente(tmp_path, monkeypatch):
    monkeypatch.setattr("eval.parse_store_corpus.encontrar_soffice", lambda: "soffice")
    with pytest.raises(FileExistsError):
        gerar(tmp_path)


def test_calibracao_isolada_por_rodada_sem_mudar_ambiente(tmp_path, monkeypatch):
    chamadas = []
    def executar_fake(cmd, **kwargs):
        chamadas.append((cmd, kwargs))
        bench.gravar(tmp_path / "01-frio.json", {"nome": "01-frio"})
    monkeypatch.setattr(bench.subprocess, "run", executar_fake)
    ambiente = {"SEGUNDOCEREBRO_CALIBRACAO": "historico-do-usuario"}
    bench.executar(tmp_path, "01-frio", ambiente)
    assert ambiente["SEGUNDOCEREBRO_CALIBRACAO"] == "historico-do-usuario"
    assert chamadas[0][1]["env"]["SEGUNDOCEREBRO_CALIBRACAO"] == str(tmp_path / "01-frio/calibracao")
    assert chamadas[0][1]["timeout"] == 300


def test_relatorio_publicado_regenera_o_contraste():
    dados = json.loads((raiz() / "docs/jf-parse-store-20260902.json").read_text(encoding="utf-8"))
    assert bench.resumir(dados["observacoes"]) == dados["resumo"]
    assert all(o["assinatura"] == dados["aquecimento"]["assinatura"] for o in dados["observacoes"])
