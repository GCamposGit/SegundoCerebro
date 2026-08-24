"""O caminho entregue como recuperador de primeira classe.

O que estes testes guardam é a razão de o módulo existir: **o `peso_nome` é
inerte em `buscar_chunks`**. Enquanto isso for verdade, o harness tem de conseguir
medir os dois caminhos, e o rótulo tem de dizer qual foi medido.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.entregue import FATOR_DE_CHUNKS, CaminhoEntregue
from eval.harness import Pergunta, avaliar
from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida
from tests.test_index import DIM, EmbedderFalso, chunk


@pytest.fixture
def indice(tmp_path: Path):  # noqa: ANN201
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    textos = {
        # O nome grita "politica de ia"; o corpo não fala do assunto.
        "Politicas/politica de ia.md": "documento normativo interno sem termo util",
        # O corpo trata do assunto; o nome não denuncia.
        "Projetos/anexo iii.md": "a classificacao de risco de inteligencia artificial",
        "Outros/nota.md": "assunto diverso sem relacao",
    }
    chunks = [chunk(f"c{i}", p, 0, t) for i, (p, t) in enumerate(textos.items())]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()
    yield store, emb
    store.fechar()


def _busca(indice, peso_nome: float, *, usar_lexical: bool = True) -> BuscaHibrida:  # noqa: ANN001
    store, emb = indice
    return BuscaHibrida(
        store,
        emb,
        candidatos=10,
        usar_lexical=usar_lexical,
        usar_nome=bool(peso_nome),
        peso_nome=peso_nome,
    )


def test_peso_nome_e_inerte_no_caminho_entregue(indice) -> None:  # noqa: ANN001
    """O defeito inteiro, em quatro linhas — e a razão de este módulo existir.

    Verificado também no índice corporativo em 24/08/2026, com três consultas:
    `buscar_chunks` devolve exatamente o mesmo com `peso_nome` 0 e 0,5, enquanto
    `search` muda a ordem em todas.
    """
    consulta = "politica de ia"
    sem = CaminhoEntregue(interno=_busca(indice, 0.0))
    com = CaminhoEntregue(interno=_busca(indice, 0.5))

    assert [h.path for h in sem.search(consulta, 3)] == [h.path for h in com.search(consulta, 3)]


def test_search_de_documento_sente_o_peso_do_nome(indice) -> None:  # noqa: ANN001
    """O outro lado do mesmo fato: no caminho que o eval mede, o peso pesa.

    O bm25 fica **desligado** aqui, e a razão é o próprio `C3.a`: a coluna
    `caminho` do FTS5 já carrega o nome do arquivo, então num acervo de três
    documentos ela sozinha promove o mesmo alvo e o ranqueador de nome não tem o
    que acrescentar. Com o lexical ligado este teste passava por empate, não por
    acerto — a dupla contagem escondendo o efeito que ele quer mostrar.
    """
    consulta = "politica de ia"
    sem = [h.path for h in _busca(indice, 0.0, usar_lexical=False).search(consulta, 3)]
    com = [h.path for h in _busca(indice, 0.5, usar_lexical=False).search(consulta, 3)]

    assert sem != com
    assert com[0] == "Politicas/politica de ia.md", "o nome promove o documento certo"


def test_peso_nome_e_inerte_no_entregue_tambem_sem_o_bm25(indice) -> None:  # noqa: ANN001
    """Sem o bm25, o caminho entregue fica só com o denso — e continua cego ao nome.

    Fecha a saída do teste acima: a inércia não é empate produzido pela coluna
    `caminho`; é ausência do ranqueador naquele caminho.
    """
    consulta = "politica de ia"
    sem = CaminhoEntregue(interno=_busca(indice, 0.0, usar_lexical=False))
    com = CaminhoEntregue(interno=_busca(indice, 0.5, usar_lexical=False))

    assert [h.path for h in sem.search(consulta, 3)] == [h.path for h in com.search(consulta, 3)]


def test_rotulo_diz_qual_caminho_foi_medido(indice) -> None:  # noqa: ANN001
    """Relatório que diga só "híbrido" é indistinguível do que mediu o outro caminho."""
    nome = CaminhoEntregue(interno=_busca(indice, 0.5)).nome

    assert "buscar_chunks" in nome
    assert "caminho entregue" in nome


def test_documento_fica_com_a_posicao_do_seu_melhor_trecho(indice) -> None:  # noqa: ANN001
    """O mesmo colapso que `search` faz por dentro — senão mede-se a regra, não a busca."""
    store, emb = indice
    extra = chunk("c9", "Projetos/anexo iii.md", 1, "segundo trecho do mesmo arquivo")
    store.gravar_chunks([extra], emb.embed_passagens([extra.text]), mtime=1.0)
    store.commit()

    entregue = CaminhoEntregue(interno=_busca(indice, 0.5))
    caminhos = [h.path for h in entregue.search("classificacao de risco", 3)]

    assert len(caminhos) == len(set(caminhos)), "um documento aparece uma vez só"


def test_pede_trechos_suficientes_para_encher_k_documentos(indice) -> None:  # noqa: ANN001
    """`k` trechos rendem menos de `k` documentos — medido: 14 de 59 perguntas.

    O fator existe por causa disso, e baixá-lo faz o relatório dizer "o caminho
    entregue recupera menos" quando o que faltou foi o adaptador pedir o bastante.
    """
    pedidos: list[int] = []

    class _Espia:
        nome = "espia"

        def buscar_chunks(self, consulta: str, k: int, contexto: int = 0):  # noqa: ANN001, ARG002, ANN202
            pedidos.append(k)
            return []

    CaminhoEntregue(interno=_Espia()).search("qualquer", 20)

    assert pedidos == [20 * FATOR_DE_CHUNKS]


def test_entra_no_harness_como_recuperador_qualquer(indice) -> None:  # noqa: ANN001
    """É o ponto do pacote: o caminho entregue passa a ser mensurável como os outros."""
    perguntas = [
        Pergunta(
            id="q1",
            tipo="semantica",
            pergunta="classificacao de risco de inteligencia artificial",
            fontes=("Projetos/anexo iii.md",),
            validada=True,
        )
    ]

    resultado = avaliar(CaminhoEntregue(interno=_busca(indice, 0.5)), perguntas)

    assert resultado.recall(1) == 1.0
    assert "buscar_chunks" in resultado.retriever
