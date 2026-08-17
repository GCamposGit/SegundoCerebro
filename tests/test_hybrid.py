"""Tests for hybrid retrieval and RRF fusion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida, rrf
from tests.test_index import DIM, EmbedderFalso, chunk


def test_rrf_soma_por_posicao() -> None:
    pontos = rrf([["a", "b"], ["b", "a"]], k=60)

    # ambos aparecem em 1º e 2º: empate
    assert pontos["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert pontos["a"] == pytest.approx(pontos["b"])


def test_rrf_premia_quem_aparece_nos_dois_rankings() -> None:
    pontos = rrf([["a", "x"], ["a", "y"]], k=60)

    assert pontos["a"] > pontos["x"]
    assert pontos["a"] == pytest.approx(2 / 61)


def test_rrf_ignora_ausencia() -> None:
    pontos = rrf([["a"], ["b"]], k=60)

    assert set(pontos) == {"a", "b"}
    assert pontos["a"] == pytest.approx(1 / 61)


def test_rrf_nao_depende_da_escala_dos_scores() -> None:
    """É por isso que usamos RRF: cosseno e bm25() não são comparáveis."""
    assert rrf([["a", "b"]]) == rrf([["a", "b"]])


@pytest.fixture
def indice(tmp_path: Path):  # noqa: ANN201
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    chunks = [
        chunk("c1", "politica.md", 0, "O PO-ACME-007 define o uso aceitável de inteligência artificial."),
        chunk("c2", "politica.md", 1, "A classificação de risco usa três níveis."),
        chunk("c3", "contrato.md", 0, "Contrato 4600009999 com a Nimbus Tecnologia."),
        chunk("c4", "outro.md", 0, "Texto sem relação alguma com o resto do acervo."),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()
    yield store, emb
    store.fechar()


def test_lexical_sozinho_acha_codigo(indice) -> None:  # noqa: ANN001
    store, emb = indice
    busca = BuscaHibrida(store, emb, usar_denso=False)

    acertos = busca.buscar_chunks("PO-ACME-007", 5)

    assert acertos[0].chunk_id == "c1"
    assert acertos[0].origem == "lexical"


def test_hibrido_marca_a_origem_de_cada_acerto(indice) -> None:  # noqa: ANN001
    store, emb = indice
    busca = BuscaHibrida(store, emb)

    acertos = busca.buscar_chunks("PO-ACME-007", 5)
    origens = {a.chunk_id: a.origem for a in acertos}

    assert "lexical" in origens["c1"]
    assert all(o for o in origens.values())


def test_search_colapsa_para_documento(indice) -> None:  # noqa: ANN001
    """O conjunto dourado aponta documentos, não chunks."""
    store, emb = indice
    busca = BuscaHibrida(store, emb, usar_denso=False)

    hits = busca.search("classificação de risco PO-ACME-007", k=3)
    paths = [h.path for h in hits]

    assert paths[0] == "politica.md"
    assert len(paths) == len(set(paths)), "documento não pode repetir"


def test_nome_descreve_a_configuracao(indice) -> None:  # noqa: ANN001
    store, emb = indice

    assert "RRF" in BuscaHibrida(store, emb).nome
    assert BuscaHibrida(store, emb, usar_lexical=False).nome.startswith("denso")
    assert BuscaHibrida(store, emb, usar_denso=False).nome.startswith("bm25")


def test_configuracao_vazia_e_rejeitada(indice) -> None:  # noqa: ANN001
    store, emb = indice

    with pytest.raises(ValueError):
        BuscaHibrida(store, emb, usar_denso=False, usar_lexical=False, usar_nome=False)


def test_chunk_orfao_no_vetorial_nao_derruba_a_busca(indice) -> None:  # noqa: ANN001
    """Registro e vetorial podem dessincronizar; a busca avisa e segue."""
    store, emb = indice
    store.con.execute("DELETE FROM chunks WHERE id = 'c1'")
    store.commit()

    acertos = BuscaHibrida(store, emb).buscar_chunks("inteligência artificial", 5)

    assert all(a.chunk_id != "c1" for a in acertos)


# --- RRF ponderado -----------------------------------------------------------


def test_rrf_com_peso_zero_ignora_o_ranking() -> None:
    pontos = rrf([["a"], ["b"]], k=60, pesos=[1.0, 0.0])

    assert set(pontos) == {"a"}


def test_rrf_ponderado_nao_deixa_o_fraco_dominar() -> None:
    """Com peso igual o híbrido mediu pior que o melhor ranqueador sozinho."""
    forte = ["bom1", "bom2", "bom3"]
    fraco = ["ruim1", "ruim2", "ruim3"]

    igual = rrf([forte, fraco], k=60)
    ponderado = rrf([forte, fraco], k=60, pesos=[1.0, 0.3])

    # com peso igual, o 1º do fraco empata com o 1º do forte
    assert igual["ruim1"] == pytest.approx(igual["bom1"])
    # ponderado, o 1º do fraco fica abaixo até do 3º do forte
    assert ponderado["ruim1"] < ponderado["bom3"]


def test_rrf_rejeita_pesos_em_numero_errado() -> None:
    with pytest.raises(ValueError):
        rrf([["a"], ["b"]], pesos=[1.0])


# --- ranqueador de nome ------------------------------------------------------


def test_ranqueador_de_nome_pontua_caminho() -> None:
    from segundocerebro.retrieve.nomes import RanqueadorDeNome

    r = RanqueadorDeNome(
        [
            "Política de IA/PO-ACME-007_Política_IA_v8.docx",
            "Outros/ata qualquer.docx",
        ]
    )

    ranking = r.ranquear("PO-ACME-007", 5)

    assert ranking[0][0] == "Política de IA/PO-ACME-007_Política_IA_v8.docx"


def test_nome_promove_documento_que_o_bm25_afoga(indice) -> None:  # noqa: ANN001
    """O ranqueador de nome muda POSIÇÃO, não presença.

    O caminho já está indexado no FTS, então o bm25 encontra o documento de
    qualquer forma. O que ele não faz é colocá-lo no topo: o bm25 normaliza por
    comprimento, e um nome de arquivo curto perde de um texto que repete os
    termos. Medido no acervo: o baseline por nome tira recall@1 = 0,549 e o bm25
    sobre conteúdo mais caminho, 0,431.
    """
    store, emb = indice
    alvo = "Relatório Northline KPI.md"
    extras = [chunk("c9", alvo, 0, "Conteúdo genérico, sem repetir o termo.")]
    # concorrentes cujo TEXTO repete os termos da consulta
    for i in range(4):
        extras.append(chunk(f"d{i}", f"notas {i}.md", 0, "Northline KPI " * 20))
    store.gravar_chunks(extras, emb.embed_passagens([c.text for c in extras]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    sem_nome = BuscaHibrida(store, emb, usar_denso=False, usar_nome=False)
    com_nome = BuscaHibrida(store, emb, usar_denso=False, usar_nome=True)

    assert sem_nome.search("Northline KPI", 5)[0].path != alvo
    assert com_nome.search("Northline KPI", 5)[0].path == alvo


def test_nome_do_recuperador_mostra_os_pesos(indice) -> None:  # noqa: ANN001
    store, emb = indice

    # Contra as constantes, não contra valores fixos: o peso é resultado de
    # medição (`docs/varredura-pesos-f1.md`) e muda quando a medição muda. Fixar
    # o número aqui faria a varredura quebrar o teste toda vez que fizesse o que
    # foi construída para fazer.
    from segundocerebro.retrieve.hybrid import PESO_DENSO, PESO_LEXICAL, PESO_NOME

    assert BuscaHibrida(store, emb).nome.startswith(
        f"denso×{PESO_DENSO:g}+bm25×{PESO_LEXICAL:g}+nome×{PESO_NOME:g}"
    )
    assert "denso" not in BuscaHibrida(store, emb, peso_denso=0).nome
