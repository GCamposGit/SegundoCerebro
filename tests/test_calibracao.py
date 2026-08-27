"""Invariantes da estimativa v2 — `docs/spec-estimativa-v2.md` §12.

Cada teste pega uma **classe** de defeito, não um caso. É o que a regra de ouro
exige de uma correção: a entrega é o método que pega a classe inteira na próxima
vez, não o caso consertado.
"""

from __future__ import annotations

import math
import random

import pytest

from segundocerebro.index.calibracao import (
    Ajuste,
    Calibracao,
    PerfilMaquina,
    encolher,
    impressao_da_maquina,
    prior_de,
    tipo_de,
)
from segundocerebro.index.estimativa import (
    CALIBRADO,
    CALIBRANDO,
    CEGO,
    Cronometro,
    Estimador,
    Faixa,
    Observacao,
    Relogio,
    faixa_humana,
)
from segundocerebro.index.mapa import Item, Mapa


# ---------------------------------------------------------------------------
# ferramentas


def _calib(tmp_path, base="b") -> Calibracao:
    return Calibracao("fp-teste", "modelo-teste", base_id=base, diretorio=tmp_path)


class _Estado:
    """Linha de registro suficiente para `_precisa_indexar`-like."""

    def __init__(self, tamanho=0, mtime=0.0, n_chunks=1, status="ok"):
        self.tamanho = tamanho
        self.mtime = mtime
        self.n_chunks = n_chunks
        self.status = status
        self.sha256 = "x" * 64
        self.model_id = "modelo-teste"
        self.chunker = "1"
        self.parser = "1"


def _obs(tipo="txt", mb=0.001, n_chunks=1, tokens=13, s_embed=0.14, **kw) -> Observacao:
    base = dict(
        rel=f"corpus/a.{tipo}",
        tipo=tipo,
        mb=mb,
        n_chunks=n_chunks,
        tokens=tokens,
        s_parse=0.002,
        s_chunk=0.001,
        s_embed=s_embed,
        s_grava=0.042,
        s_total_ativo=(s_embed or 0) + 0.045,
        perfil="maximo",
        situacao="novo",
        status="ok",
    )
    base.update(kw)
    return Observacao(**base)


# ---------------------------------------------------------------------------
# I1 — p50 <= p90 sempre


def test_i1_faixa_nunca_inverte_mesmo_com_falta_caindo_em_degrau(tmp_path):
    """A faixa invertida ("entre 4 h 8 min e 2 h 13 min") saiu de p50 suavizado
    contra p90 fresco. Aqui o restante cai em degrau — o cenário exato — e a
    asserção da `Faixa` vigia a classe inteira."""
    calib = _calib(tmp_path)
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 60_000, 1.0) for i in range(400)])
    for corte in (0, 100, 380, 399):
        est.mapa.restante = {
            "txt": type(est.mapa.censo["txt"])(n=400 - corte, mb=(400 - corte) * 0.05)
        }
        est.mapa._prontos = {f"c/{i}.txt" for i in range(corte)}
        est.mapa._maiores()
        faixa = est.restante()  # a asserção de Faixa dispara se inverter
        assert faixa.p50 <= faixa.p90


def test_i1_faixa_rejeita_construcao_invertida():
    with pytest.raises(AssertionError):
        Faixa(p50=100.0, p90=10.0)


# ---------------------------------------------------------------------------
# I2 — nada negativo


def test_i2_nnls_nunca_devolve_coeficiente_negativo():
    """Com regressores correlacionados o ajuste sem restrição produz intercepto
    negativo, e a previsão de um arquivo pequeno fica negativa. Sorteio amplo
    porque o que se afirma é uma propriedade, não um caso."""
    rng = random.Random(7)
    for _ in range(300):
        a = Ajuste()
        for _ in range(rng.randint(1, 30)):
            x0 = rng.choice([0.0, 1.0])
            x1 = rng.uniform(0, 500)
            y = rng.uniform(0, 50)
            a.observar(x0, x1, y)
        t0, t1 = a.resolver()
        assert t0 >= 0.0 and t1 >= 0.0


def test_i2_previsao_nunca_negativa(tmp_path):
    calib = _calib(tmp_path)
    rng = random.Random(11)
    for _ in range(60):
        calib.observar(
            _obs(
                mb=rng.uniform(0, 5),
                n_chunks=rng.randint(0, 300),
                tokens=rng.randint(0, 90_000),
                s_embed=rng.uniform(0, 30),
            )
        )
    for mb in (0.0, 1e-9, 0.001, 1.0, 500.0):
        assert calib.prever("txt", mb, "normal") >= 0.0


def test_i2_ajuste_recupera_os_coeficientes_verdadeiros():
    """Com dados bem-condicionados, o ajuste tem de achar a verdade.

    A primeira versão deste teste exigia igualdade com OLS puro. Com o ridge
    isso não vale — e não deve: os pares `(chunks, tokens)` que eu havia usado
    eram colineares (tokens ∝ chunks), o sistema tinha número de condição ~400,
    e OLS ali é instável justamente no eixo que interessa. Variar tokens por
    chunk **independentemente** de chunks é o que torna os dois coeficientes
    separáveis, e é o que acontece de fato num acervo com formatos diferentes.
    """
    a = Ajuste()
    pares = [(10, 500), (10, 6000), (100, 1200), (100, 30000), (50, 2000), (5, 9000)]
    for _ in range(30):
        for n, tok in pares:
            a.observar(float(n), float(tok), 0.02 * n + 0.003 * tok)
    t0, t1 = a.resolver(prior=(0.019, 0.00269))
    # Coeficiente individual num ridge com regressores correlacionados sai
    # enviesado: puxar `t1` para o prior empurra `t0` para cima. É o
    # comportamento correto de um estimador regularizado, então a tolerância por
    # coeficiente é larga de propósito.
    assert t0 == pytest.approx(0.02, rel=0.30)
    assert t1 == pytest.approx(0.003, rel=0.30)
    # O que o modelo existe para acertar é o **tempo**, não o coeficiente. Aí a
    # tolerância é apertada: os vieses se compensam na predição.
    for n, tok in pares:
        verdade = 0.02 * n + 0.003 * tok
        assert t0 * n + t1 * tok == pytest.approx(verdade, rel=0.10)


# ---------------------------------------------------------------------------
# I3 — monotonicidade


def test_i3_restante_nao_cresce_quando_o_mapa_encolhe(tmp_path):
    calib = _calib(tmp_path)
    for _ in range(40):
        calib.observar(_obs())
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(300)])
    Fatia = type(est.mapa.censo["txt"])
    anterior = float("inf")
    for restam in (300, 250, 200, 100, 50, 10, 1):
        est.mapa.restante = {"txt": Fatia(n=restam, mb=restam * 0.05)}
        est.mapa._prontos = {f"c/{i}.txt" for i in range(300 - restam)}
        est.mapa._maiores()
        p50 = est.restante().p50
        assert p50 <= anterior + 1e-9, f"cresceu em {restam}: {p50} > {anterior}"
        anterior = p50


# ---------------------------------------------------------------------------
# I4 — tempo de parede nunca entra no ajuste


def test_i4_suspensao_marca_suspeito_e_nao_move_coeficiente(tmp_path):
    """O defeito que fez o painel prometer 4 h onde faltavam 51 min: um
    documento atravessado por hibernação entrando na calibragem como se aquele
    tempo fosse custo do documento."""
    calib = _calib(tmp_path)
    for _ in range(20):
        calib.observar(_obs())
    antes = (calib.maquina.c0, calib.maquina.c1, calib.maquina.a_io)

    relogio = Relogio()
    relogio.tique(agora=1000.0)
    crono = Cronometro(relogio)
    relogio.tique(agora=1000.5)
    relogio.tique(agora=9000.0)  # salto > LIMIAR_DE_SUSPENSAO: máquina dormiu
    assert relogio.suspensoes == 1
    assert crono.suspeito is True

    obs = crono.observacao(rel="c/a.txt", tipo="txt", mb=0.001, n_chunks=1, tokens=13)
    assert obs.suspeito is True
    calib.observar(obs)
    depois = (calib.maquina.c0, calib.maquina.c1, calib.maquina.a_io)
    assert antes == depois


def test_i4_pausa_do_usuario_tambem_invalida_o_documento():
    """Hibernação incrementa `suspensoes`; "Pausar" no painel incrementa só
    `parado`. Olhar apenas o primeiro deixava um documento atravessado por
    pausa entrar na calibragem com o tempo da pausa dentro."""
    relogio = Relogio()
    relogio.tique(agora=100.0)
    crono = Cronometro(relogio)
    assert crono.suspeito is False
    relogio.contar_parado(300.0, agora=401.0)  # alguém apertou Pausar
    assert relogio.suspensoes == 0             # não foi hibernação
    assert crono.suspeito is True              # mas o relógio não serve


# ---------------------------------------------------------------------------
# I5 — trocar o encoder não reaproveita coeficiente


def test_i5_fingerprint_muda_com_modelo_e_chunker():
    a = impressao_da_maquina("e5-large", "1")
    b = impressao_da_maquina("minilm", "1")
    c = impressao_da_maquina("e5-large", "2")
    d = impressao_da_maquina("e5-large", "1", gpus=["0"])
    assert len({a, b, c, d}) == 4


def test_i5_calibragem_de_outro_modelo_nao_e_lida(tmp_path):
    um = Calibracao(impressao_da_maquina("e5-large", "1"), "e5-large", "b", tmp_path)
    for _ in range(30):
        um.observar(_obs(s_embed=5.0))
    um.gravar()
    assert um.maquina.n_obs == 30

    outro = Calibracao(
        impressao_da_maquina("minilm", "1"), "minilm", "b", tmp_path
    ).carregar()
    assert outro.maquina.n_obs == 0
    um.fechar()
    outro.fechar()


def test_i5_calibragem_sobrevive_a_reabertura(tmp_path):
    fp = impressao_da_maquina("e5-large", "1")
    um = Calibracao(fp, "e5-large", "b", tmp_path)
    for _ in range(30):
        um.observar(_obs(n_chunks=3, tokens=900, s_embed=2.7))
    um.fechar()

    dois = Calibracao(fp, "e5-large", "b", tmp_path).carregar()
    assert dois.maquina.n_obs == 30
    assert dois.prever("txt", 0.001, "maximo") > 0
    dois.fechar()


# ---------------------------------------------------------------------------
# I6 — sem histórico local não sai número


def test_i6_maquina_nova_fica_cega_e_nao_mostra_tempo(tmp_path):
    calib = _calib(tmp_path)
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(50)])
    faixa = est.restante()
    assert est.estado(faixa) == CEGO
    texto = faixa_humana(faixa, CEGO)
    assert "medindo" in texto
    assert "h" not in texto.split()  # nenhuma unidade de tempo


def test_i6_formato_nunca_visto_derruba_o_estado(tmp_path):
    """Com meses de histórico de `.txt`, uma pasta de PDF digitalizado ainda
    tem de sair de `calibrado`. Uma contagem de ciclos deixaria passar."""
    calib = _calib(tmp_path)
    for _ in range(400):
        calib.observar(_obs(tipo="txt"))
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(10)])
    est.mapa.recalcular({}, lambda e, i: True)
    assert est.cobertura == pytest.approx(1.0)

    # agora o que falta é PDF digitalizado, que ninguém mediu neste projeto
    Fatia = type(est.mapa.censo["txt"])
    est.mapa.restante = {"pdf:ocr": Fatia(n=40, mb=400.0)}
    assert est.cobertura < 0.8
    assert est.estado() == CALIBRANDO


def test_i6_estado_vira_calibrado_com_cobertura_e_faixa_estreita(tmp_path):
    calib = _calib(tmp_path)
    for _ in range(300):
        calib.observar(_obs(tipo="txt", s_embed=0.14))
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(500)])
    for _ in range(300):
        est.registrar(_obs(tipo="txt", s_embed=0.14))
    Fatia = type(est.mapa.censo["txt"])
    est.mapa.restante = {"txt": Fatia(n=200, mb=10.0)}
    est.mapa._maiores()
    assert est.estado() == CALIBRADO


# ---------------------------------------------------------------------------
# I7 — mapa derivado, nunca decrementado


def test_i7_mapa_ignora_contador_corrompido(tmp_path):
    """Corrompe o mapa restante à mão e mostra que uma rederivação o descarta.
    É o teste que impede alguém de reintroduzir um contador incremental."""
    mapa = Mapa()
    mapa.declarar([(f"c/{i}.txt", 1_048_576, 1.0) for i in range(10)])
    assert mapa.n_restante == 10

    Fatia = type(mapa.censo["txt"])
    mapa.restante = {"txt": Fatia(n=999, mb=999.0)}  # contador mentindo
    estados = {f"c/{i}.txt": _Estado(tamanho=1_048_576, mtime=1.0) for i in range(4)}
    mapa.recalcular(estados, lambda estado, item: False)

    assert mapa.n_feito == 4
    assert mapa.n_restante == 6
    assert mapa.restante["txt"].mb == pytest.approx(6.0)


def test_i7_mapa_usa_a_regra_de_quem_indexa(tmp_path):
    """`recalcular` recebe o critério; não o reimplementa. Uma regra derivada
    duas vezes é uma regra derivada de dois jeitos."""
    mapa = Mapa()
    mapa.declarar([(f"c/{i}.pdf", 2_097_152, 5.0) for i in range(6)])
    estados = {f"c/{i}.pdf": _Estado(tamanho=2_097_152, mtime=5.0) for i in range(6)}
    chamadas = []

    def precisa(estado, item):
        chamadas.append(item.rel)
        return item.rel.endswith("0.pdf")

    mapa.recalcular(estados, precisa)
    assert len(chamadas) == 6
    assert mapa.n_restante == 1


def test_i7_inalterado_nao_entra_no_restante(tmp_path):
    """Revarredura de acervo indexado custa centésimos da primeira passada.
    Prever pelo modelo completo é o que faz a barra pedir horas."""
    calib = _calib(tmp_path)
    for _ in range(50):
        calib.observar(_obs())
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 200_000, 1.0) for i in range(200)])
    cheio = est.restante().p50

    estados = {f"c/{i}.txt": _Estado(tamanho=200_000, mtime=1.0) for i in range(200)}
    est.recalcular_mapa(estados, lambda e, i: False)
    assert est.restante().p50 == 0.0
    assert cheio > 0


# ---------------------------------------------------------------------------
# I8 — a calibragem aprende a cauda (mataria a v1)


def test_i8_cauda_e_aprendida_e_nao_rejeitada(tmp_path):
    """O CSV real custou 6,0× o previsto — exatamente `CLIP_OUTLIER`, então a v1
    o descartava e nunca convergia.

    O que se afirma aqui é **convergência**, não direção: a estimativa tem de
    andar até o custo observado. A primeira versão deste teste exigia que o
    coeficiente subisse, e falhou porque o prior de CSV já é alto — a
    calibragem estava certa ao puxar para baixo.
    """
    calib = _calib(tmp_path)
    for _ in range(40):
        calib.observar(_obs(tipo="txt", n_chunks=1, tokens=13, s_embed=0.14))

    real = 1_500.0  # este acervo é bem mais caro que o prior prevê
    previsto_inicial = calib.prever("csv", 0.26, "maximo")
    razao = max(previsto_inicial / real, real / previsto_inicial)
    assert razao >= 2.0, (
        "o cenário perdeu o sentido: o prior já acerta, então não há cauda "
        f"para aprender (razão {razao:.1f}). Este guarda já disparou duas vezes "
        "conforme a calibragem melhorou — é ele que impede o teste de virar "
        "tautologia."
    )

    for _ in range(25):
        calib.observar(
            _obs(
                tipo="csv",
                rel="corpus/base.csv",
                mb=0.26,
                n_chunks=345,
                tokens=99_000,
                s_embed=real,
                s_parse=0.5,
                s_grava=1.2,
            )
        )
    depois = calib.prever("csv", 0.26, "maximo")
    erro_antes = abs(previsto_inicial - real) / real
    erro_depois = abs(depois - real) / real
    assert erro_depois < 0.35, f"não convergiu: previu {depois:.0f} s contra {real:.0f} s"
    assert erro_depois < erro_antes / 2


def test_i8_peso_cai_rapido_mas_nunca_zera():
    """O que separa "absurdo" de "caro de verdade" é quantos concordam, não a
    distância. Então o peso cai rápido — quadraticamente no desvio em log — e
    nunca chega a zero, senão nada acumularia e a cauda ficaria ineducável."""
    a = Ajuste()
    assert a.peso_de_huber(1.0, 1.0) == 1.0
    assert a.peso_de_huber(1.0, 2.0) == 1.0, "dentro da banda entra inteiro"

    dobro = a.peso_de_huber(1.0, 100.0)
    quadruplo = a.peso_de_huber(1.0, 10_000.0)
    assert 0 < quadruplo < dobro < 1.0
    # queda quadrática: dobrar o desvio em log divide o peso por ~4
    assert quadruplo == pytest.approx(dobro / 4, rel=0.35)
    assert a.peso_de_huber(1.0, 1e9) > 0, "nunca zero: a cauda tem de poder entrar"


# ---------------------------------------------------------------------------
# o perfil de esforço multiplica só o encoder


def test_perfil_multiplica_encoder_e_nao_o_io(tmp_path):
    """Medido: embed 2,1× e documento 1,20× no mesmo par de execuções. Um
    escalar global não pode ser os dois; aplicado ao encoder, pode."""
    calib = _calib(tmp_path)
    for _ in range(60):
        calib.observar(_obs(n_chunks=10, tokens=3000, s_embed=8.1, s_grava=0.42))

    m = calib.maquina
    assert m.g("maximo") == 1.0
    assert m.g("normal") == pytest.approx(2.0, rel=0.35)

    # documento com muito encoder: a razão entre perfis tende ao g
    pesado_max = calib.prever("txt", 1.0, "maximo")
    pesado_norm = calib.prever("txt", 1.0, "normal")
    razao_pesada = pesado_norm / pesado_max

    # documento minúsculo: quase só I/O, a razão tem de ser bem menor
    leve_max = calib.prever("txt", 1e-6, "maximo")
    leve_norm = calib.prever("txt", 1e-6, "normal")
    razao_leve = leve_norm / leve_max

    assert razao_pesada > razao_leve, (
        "o perfil está sendo aplicado ao documento inteiro, não ao encoder"
    )
    assert razao_leve < 1.5


# ---------------------------------------------------------------------------
# encolhimento e tipo


def test_encolhimento_vai_do_prior_ao_local():
    assert encolher(10.0, 1.0, 0) == 1.0
    assert encolher(10.0, 1.0, 8) == pytest.approx(5.5)
    assert encolher(10.0, 1.0, 800) == pytest.approx(10.0, rel=0.02)


def test_tipo_nao_e_extensao():
    assert tipo_de("a/b.pdf") == "pdf"
    assert tipo_de("a/b.pdf", digitalizado=True) == "pdf:ocr"
    assert tipo_de("a/b.pdf", digitalizado=False) == "pdf:texto"
    assert tipo_de("a/b.xlsx", tem_tabela=True) == "xlsx:tabela"


def test_legado_herda_prior_do_irmao_moderno():
    assert prior_de("doc").tipo == "doc"        # tem prior próprio medido
    assert prior_de("odt") is prior_de("zzz")   # ambos caem no genérico
    assert prior_de("pdf:ocr").k_tok > 0        # cai no prior de `pdf`


def test_prior_generico_cede_a_primeira_medicao(tmp_path):
    calib = _calib(tmp_path)
    antes = calib.prever("zzz", 1.0, "maximo")
    for _ in range(30):
        calib.observar(_obs(tipo="zzz", mb=1.0, n_chunks=2, tokens=400, s_embed=1.2))
    depois = calib.prever("zzz", 1.0, "maximo")
    assert depois != pytest.approx(antes)


# ---------------------------------------------------------------------------
# faixa por Monte Carlo


def test_faixa_do_agregado_e_mais_estreita_que_a_do_arquivo_isolado(tmp_path):
    """Quantil de soma não é soma de quantis. Mil arquivos concentram; um só
    não. Tratar o agregado com a dispersão de um inflaria a faixa até ela não
    dizer nada."""
    calib = _calib(tmp_path)
    for _ in range(50):
        calib.observar(_obs())
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(1000)])
    for i in range(60):
        est.registrar(_obs(s_embed=0.14 * (1.0 + 0.9 * ((i % 7) - 3))))

    Fatia = type(est.mapa.censo["txt"])
    est.mapa.restante = {"txt": Fatia(n=1000, mb=50.0)}
    est.mapa._maiores()
    larga_mil = est.restante().largura_relativa

    est.mapa.restante = {"txt": Fatia(n=1, mb=0.05)}
    est.mapa.itens = [Item(rel="c/0.txt", mb=0.05, tipo="txt", tamanho=50_000)]
    est.mapa._prontos = set()
    est.mapa._maiores()
    larga_um = est.restante().largura_relativa

    assert larga_mil < larga_um


def test_faixa_e_estavel_entre_chamadas(tmp_path):
    """Reamostrar a cada publicação faria o número tremer sem informação nova,
    e tremor lê como instabilidade do sistema."""
    calib = _calib(tmp_path)
    for _ in range(40):
        calib.observar(_obs())
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([(f"c/{i}.txt", 50_000, 1.0) for i in range(100)])
    a, b = est.restante(), est.restante()
    assert (a.p50, a.p90) == (b.p50, b.p90)


# ---------------------------------------------------------------------------
# o estimador não restaura fator contaminado


def test_restaurar_nao_traz_coeficiente_da_execucao_anterior(tmp_path):
    calib = _calib(tmp_path)
    est = Estimador(calibracao=calib, perfil="maximo")
    est.declarar([("c/a.txt", 50_000, 1.0)])
    antes = est.restante().p50
    est.restaurar({"previsto": 1.0, "medido": 9999.0, "fator": 9999.0})
    assert est.restante().p50 == pytest.approx(antes)


def test_g_nao_se_move_sem_dado_pareado(tmp_path):
    """`g` e `(c0, c1)` explicam o mesmo dado. Numa execução de um só perfil o
    produto é identificável e a separação não é — mover `g` ali é escolher uma
    fatoração no escuro e estragar a previsão do outro perfil."""
    calib = _calib(tmp_path)
    semente = calib.maquina.g("normal")
    for _ in range(80):  # só `normal`, nenhuma observação em `maximo`
        calib.observar(_obs(perfil="normal", n_chunks=10, tokens=3000, s_embed=30.0))
    assert calib.maquina.pareavel is False
    assert calib.maquina.g("normal") == pytest.approx(semente)

    # e a máquina lenta foi para os coeficientes, que é o que prevê `normal`
    previsto = calib.prever("txt", 0.02, "normal")
    assert previsto > 0


def test_g_se_move_quando_ha_ancora(tmp_path):
    calib = _calib(tmp_path)
    for _ in range(20):  # âncora no perfil de referência
        calib.observar(_obs(perfil="maximo", n_chunks=10, tokens=3000, s_embed=8.1))
    assert calib.maquina.pareavel is True
    for _ in range(40):  # o mesmo trabalho em `normal` custa 3x, não 2x
        calib.observar(_obs(perfil="normal", n_chunks=10, tokens=3000, s_embed=24.3))
    assert calib.maquina.g("normal") > 2.2, "não aprendeu o fator real do perfil"


def test_barra_fecha_em_um_quando_nada_resta(tmp_path):
    """Numerador e denominador têm de sair do mesmo modelo.

    Acumular o feito com coeficientes que aprendem, contra um total congelado
    no prior, faz a barra parar antes do fim — 97,98% numa passada completa.
    """
    calib = _calib(tmp_path)
    est = Estimador(calibracao=calib, perfil="maximo")
    itens = [(f"c/{i}.txt", 40_000 + i * 100, 1.0) for i in range(30)]
    est.declarar(itens)

    for i, (rel, tamanho, _) in enumerate(itens):
        # cada documento custa bem mais que o prior: os coeficientes se movem
        est.registrar(_obs(rel=rel, mb=tamanho / 1_048_576, n_chunks=8,
                           tokens=2000, s_embed=9.0))
    estados = {rel: _Estado(tamanho=t, mtime=m) for rel, t, m in itens}
    est.recalcular_mapa(estados, lambda e, i: False)

    assert est.mapa.n_restante == 0
    assert est.fracao == pytest.approx(1.0)
    assert est.restante().vazia


def test_barra_nao_anda_para_tras_conforme_aprende(tmp_path):
    """Denominador que se move é barra que volta — pior que barra imprecisa."""
    calib = _calib(tmp_path)
    est = Estimador(calibracao=calib, perfil="maximo")
    itens = [(f"c/{i}.txt", 50_000, 1.0) for i in range(40)]
    est.declarar(itens)
    anterior = 0.0
    for k, (rel, tamanho, _) in enumerate(itens, start=1):
        est.registrar(_obs(rel=rel, mb=tamanho / 1_048_576, n_chunks=8,
                           tokens=2000, s_embed=9.0))
        estados = {r: _Estado(tamanho=t, mtime=m) for r, t, m in itens[:k]}
        est.recalcular_mapa(estados, lambda e, i: False)
        f = est.fracao
        assert f >= anterior - 1e-9, f"barra voltou em {k}: {f} < {anterior}"
        anterior = f
    assert anterior == pytest.approx(1.0)


def test_soma_das_etapas_e_o_tempo_do_documento():
    """Achado numa tabela `medicoes` de run real: a soma das etapas excedia o
    "tempo ativo" em ~2× em **todos** os documentos.

    `Relogio.ativo` só anda em `tique()`, e os tiques são esparsos — o trecho
    entre o último tique e o fim do documento não entrava. As etapas cobrem o
    documento inteiro por construção, então elas são a medida.
    """
    relogio = Relogio()
    relogio.tique(agora=0.0)
    crono = Cronometro(relogio)
    crono.etapas["parse"] = 0.5
    crono.etapas["chunk"] = 0.1
    crono.etapas["embed"] = 3.0
    crono.etapas["grava"] = 0.4
    # nenhum tique novo: o Relogio nem sabe que passou tempo
    assert relogio.ativo == pytest.approx(0.0)
    assert crono.ativo == pytest.approx(4.0)

    o = crono.observacao(rel="a.txt", tipo="txt", mb=0.001, n_chunks=1, tokens=20)
    assert o.s_total_ativo == pytest.approx(4.0)
    assert o.s_total_ativo == pytest.approx(
        (o.s_parse or 0) + (o.s_chunk or 0) + (o.s_embed or 0) + (o.s_grava or 0)
    )


def test_modelo_converge_para_o_custo_observado(tmp_path):
    """Sem isto o viés sistemático vaza para a faixa em vez dos coeficientes.

    Num run real de 30 documentos o modelo previa 0,13 s/doc contra 0,6 s
    medidos, e o `mu` do resíduo — que existe para dispersão — passava a
    carregar o erro do ponto. O ponto tem de convergir sozinho.
    """
    calib = _calib(tmp_path)
    real = 0.9
    for _ in range(200):
        calib.observar(
            _obs(tipo="txt", mb=5e-5, n_chunks=1, tokens=20,
                 s_embed=real * 0.75, s_grava=real * 0.2, s_parse=real * 0.05)
        )
    previsto = calib.prever("txt", 5e-5, "maximo")
    assert previsto == pytest.approx(real, rel=0.45), (
        f"o ponto não convergiu: previu {previsto:.3f} s contra {real:.3f} s"
    )


def test_extrapolacao_longe_do_medido_encolhe_para_o_prior(tmp_path):
    """Sessenta documentos de 1 chunk não autorizam prever um de 767.

    Num run real isso previa 2 dias e meio contra ~8 h plausíveis: `c0`
    aprendido em documentos de um chunk, multiplicado por 767. O ajuste está
    certo no ponto medido; o que não se pode é extrapolar mil vezes além dele.
    """
    calib = _calib(tmp_path)
    for _ in range(60):  # todos de 1 chunk, e caros
        calib.observar(_obs(tipo="csv", mb=5e-5, n_chunks=1, tokens=20, s_embed=4.0))

    assert calib.maquina.confianca_em(1) == 1.0
    assert calib.maquina.confianca_em(8) == 1.0
    assert calib.maquina.confianca_em(767) < 0.02

    # dentro da faixa medida, o aprendido manda
    perto = calib.prever("csv", 5e-5, "maximo")
    assert perto > 3.0, "esqueceu o que aprendeu no ponto que mediu"

    # a 767 chunks, a previsão fica perto do prior, não 767× o aprendido
    m = calib.maquina
    tokens = 767 * 287
    so_aprendido = (m.c0 * 767 + m.c1 * tokens) * m.g("maximo")
    com_limite = m.custo_do_encoder(767, tokens, "maximo")
    do_prior = (m.PRIOR_C0 * 767 + m.PRIOR_C1 * tokens) * m.g("maximo")
    assert com_limite < so_aprendido / 10, 'seguiu extrapolando'
    # Fica na vizinhança do prior, não na da extrapolação. Não é igual ao prior:
    # sobra 1/767 de peso do aprendido, e sobre um valor enorme isso ainda soma
    # ~36%. É a mistura linear funcionando, não vazamento.
    assert do_prior <= com_limite < do_prior * 2


def test_faixa_medida_cresce_com_o_que_se_ve(tmp_path):
    """Quem indexa CSV grande passa a poder prever CSV grande."""
    calib = _calib(tmp_path)
    for _ in range(30):
        calib.observar(_obs(tipo="csv", mb=0.26, n_chunks=345, tokens=99_000, s_embed=90.0))
    assert calib.maquina.confianca_em(767) == 1.0
    assert calib.maquina.confianca_em(50_000) < 0.1


def test_a_suite_nunca_escreve_calibragem_real(calibracao_isolada, tmp_path):
    """O guarda da própria proteção.

    Sem ele, um teste futuro que chame `indexar()` volta a gravar em
    `%LOCALAPPDATA%` e ninguém percebe — o sintoma é um arquivo crescendo na
    máquina de quem roda a suíte, não um teste vermelho.
    """
    from segundocerebro.index.calibracao import diretorio_de_calibracao

    assert diretorio_de_calibracao() == calibracao_isolada
    assert "AppData" not in str(diretorio_de_calibracao()) or str(
        calibracao_isolada
    ) in str(diretorio_de_calibracao())

    # e o caminho de verdade: uma calibragem construída sem `diretorio` explícito
    # cai no isolado, não no real
    c = Calibracao("fp", "modelo", "base")
    c.observar(_obs())
    c.fechar()
    assert c.caminho.parent == calibracao_isolada
    assert c.caminho.exists()


def test_todo_caminho_barato_esta_declarado_num_lugar_so():
    """O merge com a `main` expôs esta classe, e o commit da v2 a previu.

    A v2 removeu `estimador.registrar(rel, tamanho, segundos)` de cinco call
    sites e centralizou a decisão. Enquanto isso, o modo de dois passes (R3.2)
    nasceu na `main` com um **sexto** call site usando a API antiga — e o Git
    mesclou sem conflito, porque a região era nova.

    O conjunto nomeado é o que faz a próxima situação ser acrescentada num lugar
    só. Este teste falha se alguém criar uma situação de caminho barato e
    esquecer de declará-la, o que a levaria a ser prevista e calibrada pelo
    modelo completo — ensinando que embeddar é grátis.
    """
    import inspect

    from segundocerebro.index import indexer
    from segundocerebro.index.calibracao import CAMINHOS_BARATOS

    assert {"inalterado", "revalidado", "texto"} <= CAMINHOS_BARATOS

    fonte = inspect.getsource(indexer)
    # nenhum call site pode ter voltado à assinatura antiga
    assert "estimador.registrar(arquivo.rel" not in fonte, (
        "voltou um call site com a API antiga: tempo de parede direto na calibragem"
    )
    # toda situação que o indexador declara tem de ser conhecida
    import re

    declaradas = set(re.findall(r'situacao="([a-z]+)"', fonte))
    conhecidas = CAMINHOS_BARATOS | {"novo", "mudado", "erro", "duplicado", "adiado"}
    assert declaradas <= conhecidas, f"situação não classificada: {declaradas - conhecidas}"


def test_caminho_barato_nao_alimenta_o_encoder(tmp_path):
    """Uma observação de caminho barato não pode mover `c0`/`c1`."""
    from segundocerebro.index.calibracao import CAMINHOS_BARATOS

    calib = _calib(tmp_path)
    for _ in range(30):
        calib.observar(_obs())
    antes = (calib.maquina.c0, calib.maquina.c1)
    for situacao in sorted(CAMINHOS_BARATOS):
        calib.observar(_obs(situacao=situacao, s_embed=999.0, n_chunks=500))
    assert (calib.maquina.c0, calib.maquina.c1) == antes
