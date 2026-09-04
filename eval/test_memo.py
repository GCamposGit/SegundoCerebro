"""O memo de varredura não pode mudar número nenhum — é a única coisa que prova isso.

Um memo que devolve resultado errado numa varredura de 18 braços não quebra:
ele **desloca a tabela**, e a tabela continua plausível. Foi assim que a primeira
versão da porta de latência mediu 4.394 ms e passaria
(`docs/porta-de-latencia.md`). Daí a forma destes testes: a mesma grade com e sem
memo, métricas idênticas.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from eval.harness import Pergunta, avaliar
from eval.memo import MemoDeBusca
from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida
from tests.falsos import DIM, EmbedderFalso, chunk

BRACOS = [
    (None, 0.5),
    ((1.0, 1.0, 0.0), 0.5),
    ((1.0, 0.5, 0.3), 0.25),
    ((1.0, 1.0, 0.0), 0.0),
]
"""Quatro braços, com repetição de `pesos_fts` de propósito: é a repetição que o
memo tem de acertar."""


@pytest.fixture
def indice(tmp_path: Path):  # noqa: ANN201
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    textos = {
        "Politicas/politica de ia.md": "a classificacao de risco de inteligencia artificial",
        "Projetos/laudo tecnico.md": "este laudo trata da politica de risco aplicada ao projeto",
        "Meetings/diaria 2026-03-11.md": "a equipe discutiu a politica e o risco do projeto",
        "Financeiro/orcamento.md": "valores previstos para o exercicio",
        "Outros/nota.md": "assunto diverso sem relacao",
    }
    chunks = [chunk(f"c{i}", p, 0, t) for i, (p, t) in enumerate(textos.items())]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()
    yield store, emb
    store.fechar()


PERGUNTAS = [
    Pergunta(
        id="q1",
        tipo="semantica",
        pergunta="qual a classificacao de risco",
        fontes=("Politicas/politica de ia.md",),
        validada=True,
    ),
    Pergunta(
        id="q2",
        tipo="exato",
        pergunta="politica de risco do projeto",
        fontes=("Projetos/laudo tecnico.md",),
        validada=True,
    ),
    Pergunta(
        id="q3",
        tipo="semantica",
        pergunta="o que a equipe discutiu",
        fontes=("Meetings/diaria 2026-03-11.md",),
        validada=True,
    ),
]


def _grade(store, embedder) -> list[tuple[float, float, float]]:  # noqa: ANN001
    saida = []
    for pesos_fts, peso_nome in BRACOS:
        busca = BuscaHibrida(
            store,
            embedder,
            candidatos=10,
            usar_nome=bool(peso_nome),
            peso_nome=peso_nome,
            pesos_fts=pesos_fts,
        )
        r = avaliar(busca, PERGUNTAS).restrito_ao_escopo()
        saida.append((r.recall(1), r.mrr(), r.ndcg(k=5)))
    return saida


def test_memo_nao_muda_metrica_nenhuma(indice) -> None:  # noqa: ANN001
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    sem_memo = _grade(store, emb)
    com_memo = _grade(memo.store, memo.embedder)

    assert com_memo == sem_memo


def test_memo_economiza_o_que_promete(indice) -> None:  # noqa: ANN001
    """Taxa baixa é grade mal desenhada, e o resumo é o que denuncia isso."""
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    _grade(memo.store, memo.embedder)

    # 4 braços × 3 perguntas = 12 buscas densas, e o denso não depende de braço:
    # 3 calculadas, 9 evitadas. Lexical tem 3 conjuntos distintos de peso em 4
    # braços, então 9 calculadas e 3 evitadas.
    assert memo.store.buscas == 24
    assert memo.store.acertos == 12
    assert memo.embedder.acertos == 9
    assert "12 de 24" in memo.resumo()


def test_memo_devolve_lista_propria_a_cada_chamada(indice) -> None:  # noqa: ANN001
    """Quem chama ordena e concatena; a lista guardada não pode ser a mesma."""
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    primeira = memo.store.buscar_lexical("politica", 5)
    primeira.append("lixo")
    segunda = memo.store.buscar_lexical("politica", 5)

    assert "lixo" not in segunda


def test_memo_separa_pesos_de_coluna_diferentes(indice) -> None:  # noqa: ANN001
    """A chave inclui os pesos — sem isso o segundo braço leria o cache do primeiro.

    É o defeito que faria a tabela inteira mostrar o mesmo número 18 vezes, o que
    ao menos é visível. Pior seria a variante que erra em um braço só.
    """
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    com_caminho = [a.id for a in memo.store.buscar_lexical("politica", 5, None)]
    sem_caminho = [a.id for a in memo.store.buscar_lexical("politica", 5, (1.0, 1.0, 0.0))]

    assert com_caminho == [a.id for a in store.buscar_lexical("politica", 5, None)]
    assert sem_caminho == [a.id for a in store.buscar_lexical("politica", 5, (1.0, 1.0, 0.0))]


def test_memo_separa_poda_de_termos_ubiquos(indice) -> None:  # noqa: ANN001
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    memo.store.buscar_lexical("politica", 5, podar_ubiquos=True)
    memo.store.buscar_lexical("politica", 5, podar_ubiquos=False)

    assert memo.store.buscas == 2
    assert memo.store.acertos == 0


def test_memo_delega_o_que_nao_e_busca(indice) -> None:  # noqa: ANN001
    """`__getattr__` em vez de lista de métodos: o proxy não pode envelhecer."""
    store, emb = indice
    memo = MemoDeBusca(store, emb)

    assert memo.store.paths_com_chunks() == store.paths_com_chunks()
    assert memo.store.estatisticas()["chunks"] == store.estatisticas()["chunks"]
    assert memo.embedder.model_id == emb.model_id


def test_memo_chaveia_o_denso_pelos_bytes_do_vetor(indice) -> None:  # noqa: ANN001
    """Dois vetores iguais em objetos diferentes têm de bater no mesmo cache."""
    store, emb = indice
    memo = MemoDeBusca(store, emb)
    v = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)

    memo.store.buscar_denso(v, 3, model_id=emb.model_id)
    memo.store.buscar_denso(v.copy(), 3, model_id=emb.model_id)

    assert memo.store.acertos == 1
