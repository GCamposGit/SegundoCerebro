"""Reranking — a lógica de reordenação, sem carregar o cross-encoder.

O modelo tem 1 GB e leva dezenas de segundos para abrir; nenhuma regra de
ordenação precisa dele para ser verificada. O teste que exige o modelo real
existe, marcado `modelo`, e fica fora da rodada padrão — mesma política do
encoder denso.
"""

from __future__ import annotations

import pytest

from segundocerebro.retrieve.rerank import CANDIDATOS_PARA_RERANK, Reranker


class RerankerFalso(Reranker):
    """Pontua pelo tamanho do texto — determinístico e sem modelo."""

    def __init__(self, **kwargs) -> None:
        super().__init__(lazy=True, **kwargs)
        self.chamadas: list[list[str]] = []

    def pontuar(self, consulta: str, textos):
        self.chamadas.append(list(textos))
        return [float(len(t)) for t in textos]


def test_reordena_pela_pontuacao_do_cross_encoder() -> None:
    r = RerankerFalso(candidatos=10)
    itens = ["a", "ccc", "bb"]

    assert r.reordenar("q", itens, lambda t: t) == ["ccc", "bb", "a"]


def test_so_a_cabeca_e_reordenada() -> None:
    """A cauda existe para revocação, não para exibição — reranqueá-la custa caro."""
    r = RerankerFalso(candidatos=2)
    itens = ["a", "bb", "cccc", "d"]

    assert r.reordenar("q", itens, lambda t: t) == ["bb", "a", "cccc", "d"]
    assert r.chamadas == [["a", "bb"]], "só os 2 primeiros foram ao modelo"


def test_lista_curta_demais_nao_chama_o_modelo() -> None:
    r = RerankerFalso(candidatos=10)

    assert r.reordenar("q", ["unico"], lambda t: t) == ["unico"]
    assert r.reordenar("q", [], lambda t: t) == []
    assert r.chamadas == []


def test_empate_preserva_a_ordem_da_fusao() -> None:
    """Sem sinal do cross-encoder, quem manda é o ranqueamento anterior."""
    r = RerankerFalso(candidatos=10)
    itens = ["aa", "bb", "cc"]

    assert r.reordenar("q", itens, lambda t: t) == itens


def test_texto_de_extrai_o_campo_certo() -> None:
    r = RerankerFalso(candidatos=10)
    itens = [{"id": 1, "texto": "curto"}, {"id": 2, "texto": "muito mais longo"}]

    ordem = r.reordenar("q", itens, lambda d: d["texto"])
    assert [d["id"] for d in ordem] == [2, 1]


def test_candidatos_e_o_botao_de_latencia() -> None:
    """O custo é linear nos pares e independe do tamanho do acervo."""
    assert CANDIDATOS_PARA_RERANK == 25
    assert RerankerFalso(candidatos=5).candidatos == 5


def test_id_descreve_o_experimento() -> None:
    r = RerankerFalso(candidatos=25)
    assert "bge-reranker-base" in r.id and "@25" in r.id and "substitui" in r.id
    assert "peso0.5" in RerankerFalso(candidatos=25, peso=0.5).id


# --- o reranker como quarto ranqueador ---------------------------------------


def test_com_peso_a_ordem_anterior_ainda_pesa() -> None:
    """Fundir por posição em vez de substituir: o consenso anterior não some.

    Com peso 1, o item que o cross-encoder ama mas estava em último não salta
    para o topo — ele sobe, disputando com quem já estava bem colocado.
    """
    r = RerankerFalso(candidatos=10, peso=1.0)
    # o falso pontua por tamanho: 'dddd' é o favorito do cross-encoder e está em 4º
    itens = ["a", "b", "c", "dddd"]

    ordem = r.reordenar("q", itens, lambda t: t)

    assert ordem[0] != "dddd", "não deve saltar de último para primeiro"
    assert ordem.index("dddd") < 3, "mas deve subir"


def test_peso_zero_mantem_a_ordem_da_fusao() -> None:
    """Voz nula é o mesmo que reranker desligado."""
    r = RerankerFalso(candidatos=10, peso=0.0)
    itens = ["a", "b", "c", "dddd"]
    assert r.reordenar("q", itens, lambda t: t) == itens


def test_peso_alto_se_aproxima_de_substituir() -> None:
    r_alto = RerankerFalso(candidatos=10, peso=50.0)
    r_subst = RerankerFalso(candidatos=10)
    itens = ["a", "bb", "cccc", "d"]

    assert r_alto.reordenar("q", itens, lambda t: t) == r_subst.reordenar("q", itens, lambda t: t)


def test_fusao_usa_a_mesma_rrf_dos_outros_ranqueadores() -> None:
    """Não é uma segunda implementação de fusão — é a mesma porta."""
    import inspect

    from segundocerebro.retrieve.rerank import Reranker

    assert "from .hybrid import rrf" in inspect.getsource(Reranker.reordenar)


@pytest.mark.modelo
def test_cross_encoder_real_separa_relevante_de_irrelevante() -> None:
    """Com o modelo de verdade: a passagem que responde tem que vencer.

    Fora da rodada padrão porque baixa e carrega 1 GB. É a classe de teste que
    pega o modelo trocado por um que não entende português.
    """
    r = Reranker(candidatos=10)
    consulta = "Qual empresa propôs a implantação de IA nos processos de negócio?"
    textos = [
        "A tabela de férias do setor administrativo referente ao mês de julho.",
        "A consultoria apresenta proposta de atuação para implantação de inteligência "
        "artificial nos processos de negócio da Acme Holding.",
    ]

    scores = r.pontuar(consulta, textos)
    assert scores[1] > scores[0]
