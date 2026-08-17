"""A porta 5 é por caso, não por média — estes testes fixam o que "por caso" quer dizer."""

from __future__ import annotations

from eval.comparar import MAX_QUEDAS_DO_PRIMEIRO, comparar, render
from eval.harness import Pergunta, Resultado, ResultadoPergunta


def item(id_: str, posicao: int | None, *, armadilha: bool = False, tipo: str = "exato") -> ResultadoPergunta:
    return ResultadoPergunta(
        pergunta=Pergunta(id=id_, tipo=tipo, pergunta=f"pergunta {id_}", fontes=("a.pdf",), armadilha=armadilha),
        recuperados=[],
        posicao_primeiro_acerto=posicao,
        recall={1: 0.0, 10: 0.0},
        mrr=0.0,
        ndcg=0.0,
    )


def resultado(nome: str, itens: list[ResultadoPergunta]) -> Resultado:
    return Resultado(retriever=nome, ks=(1, 10), itens=itens)


def test_detecta_melhora_piora_e_empate() -> None:
    antes = resultado("a", [item("g1", 5), item("g2", 1), item("g3", 3)])
    depois = resultado("b", [item("g1", 1), item("g2", 4), item("g3", 3)])

    movs = {m.id: m for m in comparar(antes, depois)}

    assert movs["g1"].melhorou and not movs["g1"].piorou
    assert movs["g2"].piorou and movs["g2"].caiu_do_primeiro
    assert not movs["g3"].melhorou and not movs["g3"].piorou


def test_nao_achado_conta_como_pior_que_qualquer_posicao() -> None:
    """`None` é pior que a posição 20; sem isso a comparação inverteria o sinal."""
    antes = resultado("a", [item("g1", 20), item("g2", None)])
    depois = resultado("b", [item("g1", None), item("g2", 20)])

    movs = {m.id: m for m in comparar(antes, depois)}

    assert movs["g1"].piorou and movs["g1"].perdeu_de_vez
    assert movs["g2"].melhorou and not movs["g2"].perdeu_de_vez


def test_regressao_em_armadilha_reprova_mesmo_com_tudo_o_mais_melhorando() -> None:
    """A porta diz "nenhuma regressão em caso crítico" — e crítico é armadilha."""
    antes = resultado("a", [item("g1", 5), item("g2", 5), item("g3", 1, armadilha=True)])
    depois = resultado("b", [item("g1", 1), item("g2", 1), item("g3", 4, armadilha=True)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: não passa.**" in texto
    assert "2 perguntas melhoraram, 1 pioraram" in texto


def test_orcamento_permite_troca_favoravel() -> None:
    """Melhorar trinta e piorar uma tem que passar — é a razão de a porta ser orçamento."""
    antes = resultado("a", [item(f"g{i}", 5) for i in range(30)] + [item("gx", 1)])
    depois = resultado("b", [item(f"g{i}", 1) for i in range(30)] + [item("gx", 2)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: passa.**" in texto


def test_estoura_o_orcamento_de_quedas_do_primeiro() -> None:
    n = MAX_QUEDAS_DO_PRIMEIRO + 1
    antes = resultado("a", [item(f"g{i}", 1) for i in range(n)])
    depois = resultado("b", [item(f"g{i}", 2) for i in range(n)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: não passa.**" in texto


def test_pergunta_ausente_de_um_dos_lados_e_ignorada() -> None:
    """Conjunto dourado que cresceu entre as duas execuções não pode inventar movimento."""
    antes = resultado("a", [item("g1", 1)])
    depois = resultado("b", [item("g1", 1), item("g2", 3)])

    assert [m.id for m in comparar(antes, depois)] == ["g1"]
