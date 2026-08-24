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
    """Hardware acelera o encoder, não o intercepto de E/S."""
    from segundocerebro.index.estimativa import SEGUNDOS_POR_DOCUMENTO

    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    cpu = peso_de("a.pdf", MB)
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    gpu = peso_de("a.pdf", MB)
    assert gpu < cpu
    # Só a parte por MB cai 28×; o intercepto é o mesmo nos dois.
    assert (cpu - SEGUNDOS_POR_DOCUMENTO) / (gpu - SEGUNDOS_POR_DOCUMENTO) == pytest.approx(
        FATOR_GPU
    )


def test_formato_muda_o_peso_do_byte() -> None:
    """137× entre PPTX e DOCX por megabyte — imagem contra texto puro."""
    from segundocerebro.index.estimativa import SEGUNDOS_POR_DOCUMENTO

    assert peso_de("a.pptx", MB) < peso_de("a.pdf", MB) < peso_de("a.xlsx", MB)
    por_mb_docx = peso_de("a.docx", MB) - SEGUNDOS_POR_DOCUMENTO
    por_mb_pptx = peso_de("a.pptx", MB) - SEGUNDOS_POR_DOCUMENTO
    assert por_mb_docx / por_mb_pptx > 100


def test_extensao_desconhecida_nao_vale_zero() -> None:
    """Peso zero faria o arquivo desaparecer da barra e ela terminar em 99%."""
    assert peso_de("a.odt", MB) > 0
    assert peso_de("sem_extensao", MB) > 0


def test_parte_por_megabyte_e_proporcional() -> None:
    """O intercepto é fixo; dobrar o arquivo dobra só a parte por byte."""
    um = peso_de("a.pdf", MB)
    dois = peso_de("a.pdf", 2 * MB)
    zero = peso_de("a.pdf", 0)
    assert zero == pytest.approx(peso_de("b.docx", 0))
    assert dois - um == pytest.approx(um - zero)


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
    from segundocerebro.index.estimativa import SEGUNDOS_POR_DOCUMENTO

    assert SEGUNDOS_POR_MB["pptx"] == 3.8
    assert SEGUNDOS_POR_MB["pdf"] == 48.7
    assert SEGUNDOS_POR_MB["xlsx"] == 487.2
    assert SEGUNDOS_POR_MB["txt"] == 496.0
    assert SEGUNDOS_POR_MB["docx"] == 522.5
    assert SEGUNDOS_POR_DOCUMENTO == 15.0


def test_txt_pequeno_nao_infla_o_restante_de_pdf() -> None:
    """819 transcrições a 24,5 s não podem mandar o PDF que falta para 67 dias.

    Sem intercepto, previsto ≈ 1 s e medido 24 s: a calibragem multiplica o
    restante por ~25. Com intercepto, previsto ≈ medido e o PDF restante
    continua na semente do PDF.
    """
    e = Estimador()
    txts = [(f"{i}.txt", 19_000) for i in range(40)]
    e.declarar([*txts, ("grande.pdf", 20 * MB)])
    for i in range(40):
        e.registrar(f"{i}.txt", 19_000, 24.5)
    # Um PDF de 20 MB na semente CPU é minutos, não dias.
    assert e.restante().p50 < 6 * 3600
    assert e.restante().p90 < 24 * 3600


def test_semente_txt_e_da_ordem_do_docx() -> None:
    """Transcrição é texto puro; a semente 50 (PDF) era 10× baixa."""
    assert peso_de("a.txt", MB) == pytest.approx(peso_de("a.docx", MB), rel=0.1)


def test_arquivo_miudo_nao_joga_a_estimativa() -> None:
    """Média ponderada pelo trabalho: 2 KB lentos não mandam a barra para dias."""
    e = Estimador()
    e.declarar([("grande.pdf", 50 * MB), ("miudo.txt", 2000)])
    previsto_grande = peso_de("grande.pdf", 50 * MB)
    e.registrar("miudo.txt", 2000, 120.0)  # 2 minutos num TXT minúsculo
    # Ainda quase tudo pela frente; a semente do PDF manda, não o outlier.
    assert e.restante().p50 == pytest.approx(previsto_grande, rel=0.35)


def test_pausa_atual_so_existe_enquanto_esta_pausado() -> None:
    r = Relogio()
    r.tique(0.0)
    r.tique(10.0)
    assert r.pausa_atual == 0
    r.contar_parado(30.0, agora=40.0)
    assert r.pausa_atual == pytest.approx(30.0)
    r.fim_pausa()
    assert r.pausa_atual == 0
