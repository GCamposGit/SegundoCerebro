"""Estimativa de tempo de indexação — os quatro modos de errar.

Três deles foram cometidos durante a F1, com o banco de dados inteiro na mão.
Cada teste aqui guarda um deles.
"""

from __future__ import annotations

import pytest

from segundocerebro.index.estimativa import (
    FATOR_GPU,
    LIMIAR_DE_SUSPENSAO,
    SEGUNDOS_POR_MB,
    Estimador,
    Faixa,
    Relogio,
    faixa_humana,
    humano,
    peso_de,
)

MB = 1_000_000


# --- erro 2: documentos não custam o mesmo -----------------------------------


def test_semente_cuda_nao_muda_a_tabela_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hardware acelera a barra, não o coeficiente versionado da CPU."""
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    cpu = peso_de("a.pdf", MB)
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    gpu = peso_de("a.pdf", MB)
    assert gpu < cpu
    assert cpu / gpu == pytest.approx(FATOR_GPU)


def test_formato_muda_o_peso_do_byte() -> None:
    """137× entre PPTX e DOCX por megabyte — imagem contra texto puro."""
    assert peso_de("a.pptx", MB) < peso_de("a.pdf", MB) < peso_de("a.xlsx", MB)
    assert peso_de("a.docx", MB) / peso_de("a.pptx", MB) > 100


def test_extensao_desconhecida_nao_vale_zero() -> None:
    """Peso zero faria o arquivo desaparecer da barra e ela terminar em 99%."""
    assert peso_de("a.odt", MB) > 0
    assert peso_de("sem_extensao", MB) > 0


def test_peso_e_proporcional_ao_tamanho() -> None:
    assert peso_de("a.pdf", 2 * MB) == pytest.approx(2 * peso_de("a.pdf", MB))


# --- erro 1: denominador errado ----------------------------------------------


def test_o_total_vem_de_fora_e_nao_e_recontado() -> None:
    """O censo conta 3.154 e o indexador processa 1.601.

    Contar aqui de novo é como o denominador errado nasce — reportando 45% quando
    o real é 91%.
    """
    e = Estimador()
    e.declarar([("a.pdf", MB), ("b.pdf", MB)])

    assert e.documentos_totais == 2
    assert e.total == pytest.approx(2 * peso_de("a.pdf", MB))


def test_pular_conta_como_feito_sem_calibrar() -> None:
    """Documento já indexado sai do restante, mas não ensina nada sobre vazão."""
    e = Estimador()
    e.declarar([("a.pdf", MB), ("b.pdf", MB)])
    e.pular("a.pdf", MB)

    assert e.fracao == pytest.approx(0.5)
    assert e.restante().p50 == pytest.approx(peso_de("b.pdf", MB))


def test_fracao_nao_passa_de_um() -> None:
    """Barra que passa de 100% é pior que barra imprecisa."""
    e = Estimador()
    e.declarar([("a.pdf", MB)])
    e.registrar("a.pdf", MB, 10.0)
    e.registrar("surpresa.pdf", MB, 10.0)  # arquivo que apareceu no meio do run
    assert e.fracao == 1.0


# --- erro 3: tempo de parede -------------------------------------------------


def test_suspensao_nao_conta_como_trabalho() -> None:
    """64 h de relógio contra 39 h de trabalho: 40% era máquina dormindo."""
    r = Relogio()
    r.tique(0.0)
    r.tique(10.0)
    r.tique(10.0 + LIMIAR_DE_SUSPENSAO + 3600)  # tampa fechada por uma hora
    r.tique(10.0 + LIMIAR_DE_SUSPENSAO + 3620)

    assert r.ativo == pytest.approx(30.0)
    assert r.suspensoes == 1
    assert r.parado > 3600


def test_pausa_curta_conta_como_trabalho() -> None:
    """Documento lento não é suspensão — o limiar existe para separar os dois."""
    r = Relogio()
    r.tique(0.0)
    r.tique(LIMIAR_DE_SUSPENSAO - 1)

    assert r.ativo == pytest.approx(LIMIAR_DE_SUSPENSAO - 1)
    assert r.suspensoes == 0


def test_relogio_ignora_regressao() -> None:
    """Relógio para trás não pode subtrair trabalho já feito."""
    r = Relogio()
    r.tique(100.0)
    r.tique(90.0)
    assert r.ativo >= 0


# --- erro 4: extrapolação ingênua, e a calibragem que a substitui ------------


def test_estimativa_se_corrige_quando_a_semente_erra() -> None:
    """A tabela governa os primeiros minutos; o run governa o resto."""
    e = Estimador()
    e.declarar([("a.pdf", MB) for _ in range(50)])
    previsto = peso_de("a.pdf", MB)

    inicial = e.restante().p50
    for i in range(30):  # esta máquina é o dobro mais lenta que a semente
        e.registrar(f"{i}.pdf", MB, previsto * 2)

    assert inicial == pytest.approx(50 * previsto)
    assert e.restante().p50 > 20 * previsto * 1.5, "aprendeu que aqui custa mais"


def test_amostra_curta_da_faixa_larga() -> None:
    """Faixa larga com pouca amostra é honestidade, não imprecisão."""
    e = Estimador()
    e.declarar([("a.pdf", MB) for _ in range(10)])
    e.registrar("0.pdf", MB, peso_de("a.pdf", MB))

    faixa = e.restante()
    assert faixa.p90 == pytest.approx(faixa.p50 * 2.0)


def test_faixa_reflete_a_dispersao_observada() -> None:
    """p90 sai do percentil medido, não de um multiplicador inventado."""
    e = Estimador()
    e.declarar([("a.pdf", MB) for _ in range(40)])
    previsto = peso_de("a.pdf", MB)
    for i in range(20):
        lento = previsto * (10 if i % 5 == 0 else 1)  # um em cinco é péssimo
        e.registrar(f"{i}.pdf", MB, lento)

    faixa = e.restante()
    assert faixa.p90 > faixa.p50, "a cauda pesada aparece na faixa"


def test_nada_a_fazer_da_faixa_vazia() -> None:
    e = Estimador()
    e.declarar([("a.pdf", MB)])
    e.registrar("a.pdf", MB, 1.0)

    assert e.restante().vazia
    assert faixa_humana(e.restante()) == "terminando"


# --- como o número aparece na tela -------------------------------------------


@pytest.mark.parametrize(
    "segundos, esperado",
    [(5, "um instante"), (90, "1 min"), (3600, "1 h"), (5400, "1 h 30 min"), (90000, "1 d 1 h")],
)
def test_humano_nunca_mostra_segundos_crus(segundos: int, esperado: str) -> None:
    assert humano(segundos) == esperado


def test_faixa_humana_colapsa_quando_os_dois_lados_batem() -> None:
    assert faixa_humana(Faixa(3600, 3600)) == "1 h"
    assert "entre" in faixa_humana(Faixa(3600, 7200))


def test_coeficientes_sao_os_medidos() -> None:
    """Se alguém mexer nestes números, é porque remediu — e o doc tem que mudar."""
    assert SEGUNDOS_POR_MB == {"pptx": 3.8, "pdf": 48.7, "xlsx": 487.2, "docx": 522.5}
