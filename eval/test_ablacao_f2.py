"""A tabela consolidada carrega a fatia de idioma — a outra metade de C4.5.

O critério de aceite do pacote tem duas partes, e esta é a que não aparece em
`render_markdown`: `eval.ablacao_f2` monta a **sua** tabela, e é ela que decide
troca de modelo denso e de reranker. Sem as colunas de idioma ali, a fatia
existiria no relatório por recuperador e faltaria exatamente onde as decisões
que ela deve vigiar são tomadas.
"""

from __future__ import annotations

from eval.ablacao_f2 import Braco, Medida, render
from eval.harness import Pergunta, avaliar
from eval.idioma import EN, MISTO, PT
from eval.test_escopo import RecuperadorFixo


def _medida(perguntas: list[Pergunta], rotulo: str = "híbrido") -> Medida:
    resultado = avaliar(RecuperadorFixo(["a.pdf", "b.pdf"]), perguntas)
    return Medida(
        braco=Braco(rotulo, "o que acrescenta", montar=lambda *a: None),
        resultado=resultado,
        segundos_por_consulta=1.0,
    )


def _p(id_: str, fonte: str, idioma: str, idioma_fonte: str) -> Pergunta:
    return Pergunta(
        id=id_,
        tipo="exato",
        pergunta=f"pergunta {id_}",
        fontes=(fonte,),
        idioma=idioma,
        idioma_fonte=idioma_fonte,
    )


def test_as_duas_colunas_de_idioma_estao_na_tabela() -> None:
    medida = _medida([_p("g1", "a.pdf", PT, PT), _p("g2", "b.pdf", PT, EN)])
    tabela = render([medida], "contexto", "")
    assert "MRR mesma-língua" in tabela
    assert "MRR cross-lingual" in tabela
    assert medida.mesma_lingua_mrr == 1.0
    assert medida.cross_mrr == 0.5


def test_fatia_vazia_sai_como_travessao_e_nao_como_zero() -> None:
    """Zero diria que a ponte entre idiomas falhou; travessão diz que não foi medida.

    Um braço cujo dourado não tem par cross-lingual não falhou em nada, e a
    tabela de ablação é lida para decidir modelo. Zero inventado numa coluna
    dessas é pior que a ausência — o travessão faz perguntar, o zero não."""
    medida = _medida([_p("g1", "a.pdf", PT, PT)])
    assert medida.cross_mrr is None
    linha = next(l for l in render([medida], "contexto", "").splitlines() if l.startswith("| **híbrido**"))
    assert linha.count("| — |") == 1


def test_par_indecidido_nao_entra_em_nenhuma_das_duas() -> None:
    medida = _medida([_p("g1", "a.pdf", PT, MISTO), _p("g2", "b.pdf", PT, PT)])
    assert medida.mesma_lingua_mrr == 0.5
    assert medida.cross_mrr is None
