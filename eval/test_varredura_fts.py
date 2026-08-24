"""A grade e a regra do `C3.a` — testadas sem índice, porque decisão é aritmética.

O que estes testes guardam é a **regra declarada antes de rodar**, incluindo a
conclusão negativa. Uma regra que só existe na cabeça de quem olha a tabela é a
tabela escolhendo sozinha, e este projeto já registrou o custo disso duas vezes
(`eval/varredura.py`, `docs/dourado-cobertura.md`).
"""

from __future__ import annotations

import pytest

from eval.fonte import ESCRITORIO, REUNIAO
from eval.harness import KS_PADRAO, Pergunta, Resultado, ResultadoPergunta
from eval.varredura_fts import (
    MINIMO_ARMADILHAS,
    PESOS_CAMINHO,
    PESOS_NOME,
    PESOS_TRILHA,
    REFERENCIA,
    REGRA,
    Ponto,
    grade,
    margem,
    render,
)


def _item(
    id_: str,
    *,
    grupo: str,
    posicao: int | None,
    armadilha: bool = False,
) -> ResultadoPergunta:
    """Uma pergunta que acertou na posição `posicao` (1-based), ou nunca."""
    fonte = "Meetings/daily.docx" if grupo == REUNIAO else "Projetos/contrato.pdf"
    pergunta = Pergunta(
        id=id_,
        tipo="semantica",
        pergunta="p",
        fontes=(fonte,),
        validada=True,
        armadilha=armadilha,
    )
    recall = {k: (1.0 if posicao is not None and posicao <= k else 0.0) for k in (*KS_PADRAO, 10)}
    return ResultadoPergunta(
        pergunta=pergunta,
        recuperados=[],
        posicao_primeiro_acerto=posicao,
        recall=recall,
        mrr=0.0 if posicao is None else 1.0 / posicao,
        ndcg={5: 0.0, 10: 0.0},
    )


def _ponto(
    triplo: tuple[float, float, float],
    *,
    reuniao: list[int | None],
    escritorio: list[int | None],
    armadilhas: int = MINIMO_ARMADILHAS,
) -> Ponto:
    itens = [_item(f"r{i}", grupo=REUNIAO, posicao=p) for i, p in enumerate(reuniao)]
    itens += [_item(f"e{i}", grupo=ESCRITORIO, posicao=p) for i, p in enumerate(escritorio)]
    # As armadilhas entram como perguntas de escritório resolvidas no top-10,
    # porque a porta conta caso resolvido e não média.
    itens += [_item(f"a{i}", grupo=ESCRITORIO, posicao=1, armadilha=True) for i in range(armadilhas)]
    itens += [
        _item(f"x{i}", grupo=ESCRITORIO, posicao=None, armadilha=True)
        for i in range(6 - armadilhas)
    ]
    return Ponto(*triplo, Resultado(retriever="t", ks=KS_PADRAO, itens=itens))


def test_grade_tem_os_dezoito_bracos_do_complemento() -> None:
    assert len(grade()) == len(PESOS_CAMINHO) * len(PESOS_TRILHA) * len(PESOS_NOME) == 18
    assert len(set(grade())) == 18


def test_a_referencia_esta_na_grade() -> None:
    """Sem o braço de hoje na grade não há contra o que ler os outros."""
    assert REFERENCIA in grade()


def test_margem_e_uma_pergunta_saindo_do_terceiro_para_o_primeiro() -> None:
    assert margem(11) == pytest.approx((1 - 1 / 3) / 11)
    assert margem(0) == 0.0


def test_regra_escolhe_quem_sobe_reuniao_sem_perder_o_agregado() -> None:
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    bom = _ponto((1.0, 0.3, 0.5), reuniao=[1, 1, 1], escritorio=[1, 1, 1])

    veredito = REGRA([ref, bom])

    assert veredito.escolhido is bom
    assert veredito.referencia is ref


def test_regra_recusa_quem_sobe_reuniao_derrubando_o_agregado() -> None:
    """É a troca que a média esconderia e que o recorte existe para mostrar."""
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    troca = _ponto((1.0, 0.0, 0.5), reuniao=[1, 1, 1], escritorio=[5, 5, 5])

    veredito = REGRA([ref, troca])

    assert veredito.escolhido is None
    assert "agregado" in veredito.motivo


def test_regra_recusa_ganho_menor_que_uma_pergunta() -> None:
    """Ganho dentro do arredondamento não é achado, e a regra diz isso antes."""
    ref = _ponto(REFERENCIA, reuniao=[2, 2, 2], escritorio=[1, 1, 1])
    quase = _ponto((0.5, 0.3, 0.5), reuniao=[2, 2, 1], escritorio=[1, 1, 1])

    # Uma pergunta de 2º para 1º em três: +0,167 de MRR. A margem exige o
    # equivalente a 3º → 1º, que com n=3 é +0,222.
    assert quase.mrr_do_grupo(REUNIAO) - ref.mrr_do_grupo(REUNIAO) < margem(3)

    veredito = REGRA([ref, quase])

    assert veredito.escolhido is None
    assert "margem" in veredito.motivo


def test_regra_recusa_quem_quebra_a_porta_tres() -> None:
    """4 de 6 armadilhas é regressão de porta declarada, com qualquer média."""
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    fora = _ponto((1.0, 0.0, 0.0), reuniao=[1, 1, 1], escritorio=[1, 1, 1], armadilhas=4)

    assert not fora.elegivel

    veredito = REGRA([ref, fora])

    assert veredito.escolhido is None


def test_empate_prefere_menos_caminho_e_menos_nome() -> None:
    """Entre iguais, a que depende menos da forma de superfície do nome.

    É a configuração que generaliza para o acervo de `IMG_2034.pdf`, que é o caso
    que `R6.1` vai encontrar e este acervo não tem.
    """
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    caro = _ponto((1.0, 1.0, 0.25), reuniao=[1, 1, 1], escritorio=[1, 1, 1])
    barato = _ponto((1.0, 0.0, 0.25), reuniao=[1, 1, 1], escritorio=[1, 1, 1])

    assert REGRA([ref, caro, barato]).escolhido is barato


def test_empate_em_trilha_prefere_nao_mexer() -> None:
    """O empate que a regra declarada não sabia desfazer, em 24/08/2026.

    `caminho` e `nome` iguais, `trilha` diferente, tudo o mais medindo o mesmo: a
    escolha caía na ordem da grade. Mexer num peso que mediu plano é mudança sem
    número, então o desempate prefere a trilha da referência.
    """
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    mexe = _ponto((0.5, 1.0, 0.25), reuniao=[1, 1, 1], escritorio=[1, 1, 1])
    nao_mexe = _ponto((1.0, 1.0, 0.25), reuniao=[1, 1, 1], escritorio=[1, 1, 1])

    assert REGRA([ref, mexe, nao_mexe]).escolhido is nao_mexe
    assert REGRA([ref, nao_mexe, mexe]).escolhido is nao_mexe, "não pode depender da ordem"


def test_relatorio_negativo_diz_que_a_hipotese_foi_refutada() -> None:
    """A conclusão negativa tem de estar escrita, não deduzida de tabela vazia."""
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    pontos = [ref, _ponto((1.0, 0.0, 0.5), reuniao=[3, 3, 3], escritorio=[5, 5, 5])]

    texto = render(pontos, REGRA(pontos), "contexto")

    assert "Nada passa" in texto
    assert "refutada" in texto
    assert "F4-P" in texto


def test_relatorio_positivo_traz_o_toml_de_aplicar() -> None:
    ref = _ponto(REFERENCIA, reuniao=[3, 3, 3], escritorio=[1, 1, 1])
    bom = _ponto((0.5, 0.3, 0.25), reuniao=[1, 1, 1], escritorio=[1, 1, 1])

    texto = render([ref, bom], REGRA([ref, bom]), "contexto")

    assert "[base.pesos]" in texto
    assert "fts_caminho = 0.3" in texto
    assert "não reindexa nada" in texto


def test_relatorio_traz_a_grade_inteira() -> None:
    """Superfície plana e superfície com pico levam a conclusões diferentes."""
    pontos = [
        _ponto(REFERENCIA, reuniao=[3], escritorio=[1]),
        _ponto((0.5, 0.3, 0.25), reuniao=[2], escritorio=[1]),
        _ponto((0.5, 0.0, 0.0), reuniao=[4], escritorio=[2]),
    ]

    texto = render(pontos, REGRA(pontos), "contexto")

    assert texto.count("| 0.5 |") + texto.count("| 1 |") >= 3
    assert "referência" in texto
