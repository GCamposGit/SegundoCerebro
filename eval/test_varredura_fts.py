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
    idioma_fonte: str = "pt",
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
        idioma="pt",
        idioma_fonte=idioma_fonte,
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


def _ponto_bilingue(
    triplo: tuple[float, float, float],
    *,
    cross: list[int | None],
    mesma: list[int | None],
) -> Ponto:
    """Ponto com as duas fatias de idioma povoadas, para a guarda ter o que ver."""
    itens = [
        _item(f"c{i}", grupo=ESCRITORIO, posicao=p, idioma_fonte="en")
        for i, p in enumerate(cross)
    ]
    itens += [
        _item(f"m{i}", grupo=REUNIAO, posicao=p, idioma_fonte="pt") for i, p in enumerate(mesma)
    ]
    itens += [_item(f"a{i}", grupo=ESCRITORIO, posicao=1, armadilha=True) for i in range(5)]
    itens += [_item("x0", grupo=ESCRITORIO, posicao=None, armadilha=True)]
    return Ponto(*triplo, Resultado(retriever="t", ks=KS_PADRAO, itens=itens))


def test_regra_recusa_quem_sobe_a_media_e_quebra_a_ponte_pt_en() -> None:
    """A guarda de `C4.5` dentro da varredura, e o motivo de a régua vir antes.

    Dois dos três votos da fusão são cegos a idioma por construção, e a fatia
    mesma-língua é quatro vezes maior — mexer no peso deles pode quebrar **só** a
    ponte e passar na média.
    """
    ref = _ponto_bilingue(REFERENCIA, cross=[1, 1, 2], mesma=[3, 3, 3, 3, 3, 3])
    quebra = _ponto_bilingue((1.0, 1.0, 0.25), cross=[9, 9, 9], mesma=[1, 1, 1, 1, 1, 1])

    assert quebra.resultado.mrr() > ref.resultado.mrr(), "sobe a média, que é a armadilha"
    assert quebra.mrr_da_fatia("cross-lingual") < ref.mrr_da_fatia("cross-lingual")

    veredito = REGRA([ref, quebra])

    assert veredito.escolhido is None


def test_razao_cross_lingual_e_zero_sem_as_duas_fatias() -> None:
    """Sem as duas povoadas não há razão; devolver 1,0 faria a porta passar por ausência."""
    so_mesma = _ponto(REFERENCIA, reuniao=[1], escritorio=[1])

    assert so_mesma.n_da_fatia("cross-lingual") == 0
    assert so_mesma.razao_cross_lingual == 0.0


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


def test_motivo_nomeia_o_criterio_que_eliminou() -> None:
    """O veredito mentia quando a guarda cross-lingual entrou como terceiro critério.

    A mensagem era fixa e citava dois critérios; braços que mantinham porta e
    agregado e perdiam a ponte PT↔EN eram relatados como se tivessem quebrado a
    porta. Relatório que dá o motivo errado é pior que relatório sem motivo.
    """
    ref = _ponto_bilingue(REFERENCIA, cross=[1, 1, 2], mesma=[3, 3, 3, 3, 3, 3])
    quebra = _ponto_bilingue((1.0, 1.0, 0.25), cross=[9, 9, 9], mesma=[1, 1, 1, 1, 1, 1])

    motivo = REGRA([ref, quebra]).motivo

    assert "cross-lingual" in motivo
    assert "porta 3" in motivo and "agregado" in motivo, "diz o que os braços mantiveram"


def test_relatorio_negativo_por_cross_lingual_explica_a_ponte() -> None:
    ref = _ponto_bilingue(REFERENCIA, cross=[1, 1, 2], mesma=[3, 3, 3, 3, 3, 3])
    quebra = _ponto_bilingue((1.0, 1.0, 0.25), cross=[9, 9, 9], mesma=[1, 1, 1, 1, 1, 1])
    pontos = [ref, quebra]

    texto = render(pontos, REGRA(pontos), "contexto")

    assert "agnóstico a idioma" in texto
    assert "três lados" in texto


def test_razao_sobe_quando_o_denominador_cai_e_a_tabela_mostra_os_dois() -> None:
    """Razão melhor com mesma-língua pior é regressão disfarçada de avanço."""
    ref = _ponto_bilingue(REFERENCIA, cross=[5, 9, 9], mesma=[1, 1, 1, 1, 1, 1])
    disfarce = _ponto_bilingue((1.0, 0.0, 0.5), cross=[5, 9, 9], mesma=[1, 1, 1, 9, 9, 9])

    # A ponte não melhorou em nada: o recall@5 cross-lingual é o mesmo nos dois.
    assert disfarce.recall5_da_fatia("cross-lingual") == ref.recall5_da_fatia("cross-lingual")
    assert disfarce.recall5_da_fatia("mesma-língua") < ref.recall5_da_fatia("mesma-língua")
    assert disfarce.razao_cross_lingual > ref.razao_cross_lingual

    texto = render([ref, disfarce], REGRA([ref, disfarce]), "contexto")

    assert "r@5 cross" in texto and "r@5 mesma" in texto
