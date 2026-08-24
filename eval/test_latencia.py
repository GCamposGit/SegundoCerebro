"""A porta de latência — percentil, as duas espécies de porta, e o relatório.

Nada aqui abre índice: a medição real precisa do acervo e do encoder, e nenhum
dos dois existe no CI. O que a suíte protege é o que decide — o percentil, a
separação entre porta de produto e piso de regressão, e o relatório dizer a
verdade sobre a passada que o gerou.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.latencia import (
    OPERACOES,
    Ambiente,
    Amostra,
    Medicao,
    carregar_portas,
    conferir,
    limites_de,
    main,
    percentil,
    render,
)

AMBIENTE = Ambiente(
    maquina="maquina-de-teste",
    processador="cpu-de-teste",
    nucleos=4,
    documentos=10,
    chunks=100,
    modelo="e5-large",
    threads=4,
)


def _medicao(*amostras: Amostra, rodadas: int = 3, **kw) -> Medicao:  # noqa: ANN003
    return Medicao(amostras=amostras, rodadas=rodadas, **kw)


# --- percentil --------------------------------------------------------------


def test_percentil_devolve_uma_medicao_que_aconteceu() -> None:
    """Posto mais próximo, não interpolado.

    O valor tem que ser um dos tempos observados, para quem investigar a cauda
    poder dizer "esta consulta levou isto" em vez de "a média de duas levou"."""
    valores = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert percentil(valores, 0.95) in valores
    assert percentil(valores, 0.95) == 100.0
    assert percentil(valores, 0.50) == 3.0


def test_percentil_de_amostra_vazia_e_zero() -> None:
    assert percentil([], 0.95) == 0.0


def test_percentil_nao_depende_da_ordem_de_entrada() -> None:
    assert percentil([5.0, 1.0, 3.0], 0.5) == percentil([1.0, 3.0, 5.0], 0.5)


def test_p50_e_p95_da_amostra() -> None:
    a = Amostra("search", tuple(float(i) for i in range(1, 101)))
    assert (a.n, a.p50, a.p95) == (100, 50.0, 95.0)
    assert (a.minimo, a.maximo) == (1.0, 100.0)
    assert a.desvio > 0


def test_desvio_de_uma_amostra_so_e_zero() -> None:
    """`statistics.stdev` estoura com n=1, e n=1 acontece: uma consulta só."""
    assert Amostra("search", (5.0,)).desvio == 0.0


# --- as duas portas ---------------------------------------------------------


PORTAS = {
    "produto": {"p95": {"search": 300}},
    "regressao": {
        "notebook-15w": {"descricao": "x", "p95": {"search": 3000}},
        "desktop": {"p95": {"search": 500}},
    },
}


def test_porta_de_produto_reprovada_nao_e_falha_de_ninguem() -> None:
    """Ela existe para dizer quanto falta, e por isso aparece mesmo reprovando.

    Uma porta que sumisse do relatório quando reprova esconderia justamente o
    número que `R4.1` e `R3.3` têm de perseguir."""
    a = Amostra("search", (1000.0,) * 20)
    violacoes = conferir([a], PORTAS, "notebook-15w")
    especies = {v.especie for v in violacoes}
    assert especies == {"produto"}
    (v,) = violacoes
    assert v.fator == pytest.approx(1000 / 300)


def test_piso_de_regressao_e_por_maquina() -> None:
    """O mesmo p95 aprova numa máquina e reprova na outra — é o ponto do campo.

    1.418 ms num i7 de 15 W não diz nada sobre o desktop, e um piso medido lá
    reprovaria aqui todo dia."""
    a = Amostra("search", (1000.0,) * 20)
    assert not [v for v in conferir([a], PORTAS, "notebook-15w") if v.especie == "regressao"]
    assert [v for v in conferir([a], PORTAS, "desktop") if v.especie == "regressao"]


def test_sem_maquina_nenhum_piso_e_conferido() -> None:
    a = Amostra("search", (1000.0,) * 20)
    assert not [v for v in conferir([a], PORTAS, "") if v.especie == "regressao"]


def test_maquina_desconhecida_nao_inventa_piso() -> None:
    a = Amostra("search", (99999.0,) * 20)
    assert not [v for v in conferir([a], PORTAS, "maquina-que-nao-existe") if v.especie == "regressao"]


def test_operacao_sem_amostra_nao_vira_violacao() -> None:
    """Braço não medido não é braço reprovado.

    `--sem-rerank` não mede `search+rerank`; contar isso como violação faria a
    porta falhar por ausência de medição, que é o oposto do que ela mede."""
    portas = {"regressao": {"m": {"p95": {"search+rerank": 10}}}}
    assert conferir([Amostra("search", (1.0,))], portas, "m") == []


def test_metadado_numerico_da_maquina_nao_vira_porta() -> None:
    """`indice_chunks = 98326` fora da subtabela `p95` não é uma porta de 98 s.

    Com tudo no mesmo nível os dois eram indistinguíveis, e o resultado era uma
    linha que nunca dispara parecendo cobertura."""
    portas = {"regressao": {"m": {"indice_chunks": 98326, "p95": {"search": 10}}}}
    violacoes = conferir([Amostra("search", (50.0,)), Amostra("read_note", (1.0,))], portas, "m")
    assert [v.operacao for v in violacoes] == ["search"]


def test_secao_sem_subtabela_p95_nao_confere_nada() -> None:
    portas = {"regressao": {"m": {"descricao": "notebook"}}}
    assert conferir([Amostra("search", (50.0,))], portas, "m") == []


# --- relatório --------------------------------------------------------------


def test_relatorio_declara_as_rodadas_que_rodaram() -> None:
    """A primeira versão imprimia a constante do módulo e saiu dizendo "3 rodadas"
    numa passada de 1 — a mesma armadilha dos "None candidatos" de `eval.rodar`."""
    texto = render(_medicao(Amostra("search", (1.0, 2.0)), rodadas=1), AMBIENTE, [], {}, "")
    assert "1 rodada(s)" in texto
    assert "3 rodada(s)" not in texto


def test_relatorio_sem_portas_diz_que_nao_ha() -> None:
    texto = render(_medicao(Amostra("search", (1.0,))), AMBIENTE, [], {}, "")
    assert "Nenhuma porta declarada" in texto


def test_relatorio_marca_piso_rompido_como_falha() -> None:
    amostra = Amostra("search", (4000.0,) * 20)
    violacoes = conferir([amostra], PORTAS, "notebook-15w")
    texto = render(_medicao(amostra), AMBIENTE, violacoes, PORTAS, "notebook-15w")
    assert "piso(s) de regressão rompido(s)" in texto
    assert "❌" in texto


def test_relatorio_conta_os_neighbors_vazios() -> None:
    """`neighbors` rápido e `neighbors` sem assunto são a mesma medição vista de fora."""
    texto = render(
        _medicao(Amostra("neighbors", (0.2,) * 10), vizinhos_medidos=10, vizinhos_vazios=7),
        AMBIENTE,
        [],
        {},
        "",
    )
    assert "**3 de 10**" in texto


def test_ambiente_entra_no_relatorio() -> None:
    """Número sem máquina é mentira, do mesmo jeito que número sem corpus."""
    texto = render(_medicao(Amostra("search", (1.0,))), AMBIENTE, [], {}, "")
    for pedaco in ("maquina-de-teste", "cpu-de-teste", "100 trechos", "e5-large"):
        assert pedaco in texto


def test_deriva_expoe_a_maquina_esquentando() -> None:
    """p50 por rodada, na ordem — a maior fonte de variação desta medição.

    O mesmo código no mesmo índice mediu p95 de 1 916 ms com o notebook frio e
    2 877 ms depois de minutos de reranking. Uma p50 agregada esconde isso; três
    em ordem mostram a frequência caindo enquanto a medição corre."""
    m = _medicao(
        Amostra("search", (10.0, 12.0, 11.0, 20.0, 22.0, 21.0, 30.0, 32.0, 31.0)), rodadas=3
    )
    assert m.deriva() == [11.0, 21.0, 31.0]
    texto = render(m, AMBIENTE, [], {}, "")
    assert "p50 por rodada" in texto


def test_uma_rodada_so_nao_tem_deriva_a_mostrar() -> None:
    """Com uma rodada não há série; inventar uma linha sugeriria estabilidade medida."""
    m = _medicao(Amostra("search", (10.0, 12.0)), rodadas=1)
    assert m.deriva() == []
    assert "p50 por rodada" not in render(m, AMBIENTE, [], {}, "")


def test_deriva_segue_o_braco_medido() -> None:
    """No braço com reranker a série é a dele, não a de `search`, que nem existe."""
    m = _medicao(
        Amostra("search+rerank", (10.0, 12.0, 20.0, 22.0)),
        Amostra("read_note", (0.1,) * 4),
        rodadas=2,
    )
    object.__setattr__(m, "braco", "search+rerank")
    assert m.deriva() == [10.0, 20.0]


# --- o arquivo de portas versionado -----------------------------------------


def test_arquivo_de_portas_existe_e_declara_as_duas_especies() -> None:
    portas = carregar_portas()
    assert portas, "eval/portas-latencia.toml é a porta versionada de R9.3"
    assert "produto" in portas
    assert "regressao" in portas


def test_toda_porta_declarada_e_de_uma_operacao_conhecida() -> None:
    """Porta de operação inexistente nunca dispara e parece cobertura.

    É o mesmo modo de falha de `fora_de_escopo` não catalogado: a linha existe,
    ninguém a lê, e o relatório sugere uma guarda que não há."""
    portas = carregar_portas()
    secoes = [portas.get("produto", {})] + list(portas.get("regressao", {}).values())
    for secao in secoes:
        for chave in limites_de(secao):
            assert chave in OPERACOES, f"porta para operação desconhecida: {chave}"


def test_portas_ausentes_devolvem_vazio(tmp_path: Path) -> None:
    assert carregar_portas(tmp_path / "nao-existe.toml") == {}


# --- CLI --------------------------------------------------------------------


def test_porta_sem_maquina_e_recusada() -> None:
    """Piso sem máquina não é porta, é número solto: o mesmo p95 aprova num
    desktop e reprova num notebook de 15 W."""
    assert main(["--porta"]) == 2
