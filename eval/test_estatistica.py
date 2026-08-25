"""Testes do pacote `E5` — bootstrap pareado e regra de adoção."""

from __future__ import annotations

import pytest

from .estatistica import (
    EMPATE,
    GANHA,
    N_MINIMO,
    PERDE,
    Delta,
    alinhar,
    ic_da_media,
    ic_do_delta,
)


def test_intervalo_contem_a_media() -> None:
    vals = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
    baixo, alto = ic_da_media(vals)
    assert baixo <= sum(vals) / len(vals) <= alto


def test_determinismo() -> None:
    """O intervalo entra em documento versionado — regenerar não pode mexer nele."""
    vals = [0.0, 1.0, 0.5, 0.25, 1.0, 0.0, 0.33]
    assert ic_da_media(vals) == ic_da_media(vals)
    assert ic_do_delta(vals, [v + 0.1 for v in vals]) == ic_do_delta(vals, [v + 0.1 for v in vals])


def test_amostra_sem_variacao_tem_intervalo_degenerado() -> None:
    baixo, alto = ic_da_media([0.7] * 20)
    assert baixo == alto == pytest.approx(0.7)


def test_n_maior_estreita_o_intervalo() -> None:
    """A razão de o `E5.3` existir: o mesmo efeito, com mais perguntas, decide."""
    padrao = [1.0, 0.0] * 6
    baixo_p, alto_p = ic_da_media(padrao)
    baixo_g, alto_g = ic_da_media(padrao * 10)
    assert (alto_g - baixo_g) < (alto_p - baixo_p)


class TestDelta:
    def test_ganho_grande_e_consistente_exclui_zero(self) -> None:
        antes = [0.0] * 40
        depois = [1.0] * 40
        d = ic_do_delta(antes, depois)
        assert d.valor == pytest.approx(1.0)
        assert d.exclui_zero and d.veredito == GANHA

    def test_perda_consistente_da_veredito_de_perda(self) -> None:
        d = ic_do_delta([1.0] * 40, [0.0] * 40)
        assert d.valor == pytest.approx(-1.0)
        assert d.exclui_zero and d.veredito == PERDE

    def test_ganho_de_uma_pergunta_em_onze_nao_exclui_zero(self) -> None:
        """O caso concreto que motivou o pacote.

        `reunião` tem 11 perguntas. Uma pergunta que passa a acertar move a média
        em 9 pontos — número que numa tabela de médias parece ganho, e cujo
        intervalo cruza zero com folga."""
        antes = [0.0] + [1.0, 0.0] * 5
        depois = [1.0] + [1.0, 0.0] * 5
        d = ic_do_delta(antes, depois)
        assert d.n == 11
        assert d.valor == pytest.approx(1 / 11)
        assert not d.exclui_zero
        assert d.veredito == EMPATE
        assert d.subdimensionado

    def test_empate_quando_nada_muda(self) -> None:
        vals = [1.0, 0.0, 0.5] * 15
        d = ic_do_delta(vals, vals)
        assert d.valor == 0.0
        assert d.baixo == d.alto == 0.0
        assert not d.exclui_zero and d.veredito == EMPATE

    def test_pareamento_detecta_o_que_a_media_agregada_esconde(self) -> None:
        """Duas amostras com **a mesma média** dos dois lados, e um ganho real.

        Metade das perguntas é fácil (1,0 nos dois braços) e metade é difícil.
        O braço novo acerta consistentemente um pouco mais nas difíceis. Comparar
        agregados afogaria isso na variância das fáceis; o pareado vê, porque a
        diferença por pergunta é quase constante."""
        antes = [1.0] * 20 + [0.1] * 20
        depois = [1.0] * 20 + [0.3] * 20
        d = ic_do_delta(antes, depois)
        assert d.exclui_zero and d.veredito == GANHA
        # O intervalo do delta é muito mais estreito que o de qualquer braço.
        largura_delta = d.alto - d.baixo
        b, a = ic_da_media(antes)
        assert largura_delta < (a - b)

    def test_recusa_bracos_de_tamanhos_diferentes(self) -> None:
        with pytest.raises(ValueError, match="pareado"):
            ic_do_delta([1.0, 0.0], [1.0, 0.0, 1.0])

    def test_vetores_vazios_nao_explodem(self) -> None:
        d = ic_do_delta([], [])
        assert d.n == 0 and d.veredito == EMPATE
        assert ic_da_media([]) == (0.0, 0.0)

    def test_uma_pergunta_so_nao_finge_intervalo(self) -> None:
        d = ic_do_delta([0.0], [1.0])
        assert d.n == 1 and d.baixo == d.alto == 1.0
        assert d.subdimensionado

    def test_formatacao_traz_sinal_nos_tres_numeros(self) -> None:
        assert str(Delta(0.011, -0.004, 0.028, 49)) == "+0.011 [-0.004, +0.028]"

    def test_piso_de_n_e_o_do_pacote(self) -> None:
        assert N_MINIMO == 30
        assert Delta(0.0, 0.0, 0.0, 29).subdimensionado
        assert not Delta(0.0, 0.0, 0.0, 30).subdimensionado


class TestAlinhar:
    def test_casa_por_id_e_nao_por_ordem(self) -> None:
        antes = {"g002": 0.0, "g001": 1.0}
        depois = {"g001": 0.5, "g002": 0.25}
        a, d, ids = alinhar(antes, depois)
        assert ids == ["g001", "g002"]
        assert a == [1.0, 0.0] and d == [0.5, 0.25]

    def test_id_de_um_lado_so_fica_de_fora_e_aparece_na_contagem(self) -> None:
        a, d, ids = alinhar({"g001": 1.0, "g009": 1.0}, {"g001": 0.0})
        assert ids == ["g001"]
        assert len(a) == len(d) == 1


# --- calibração: o instrumento contra uma referência independente -------------


def test_bate_com_o_intervalo_analitico_quando_a_normal_vale() -> None:
    """Com n grande e uma proporção, o bootstrap tem de reproduzir `p ± 1,96·EP`.

    É a conferência que separa "implementei um bootstrap" de "implementei o
    bootstrap certo": no regime em que existe resposta fechada, os dois têm de
    coincidir. Fora desse regime — que é onde este projeto vive, com n=11 — só o
    bootstrap continua valendo, e é por isso que ele é o instrumento escolhido.
    """
    import numpy as np

    amostra = (np.random.default_rng(1).random(4000) < 0.30).astype(float)
    baixo, alto = ic_da_media(amostra)

    p = float(amostra.mean())
    erro = 1.96 * (p * (1 - p) / len(amostra)) ** 0.5
    assert baixo == pytest.approx(p - erro, abs=0.005)
    assert alto == pytest.approx(p + erro, abs=0.005)


def test_a_regra_de_adocao_erra_perto_de_5_por_cento_sob_hipotese_nula() -> None:
    """Dois braços idênticos por construção: a regra deve adotar ~5% das vezes.

    Sem esta conferência, `exclui_zero` poderia ser generosa e ninguém veria — o
    sintoma seria o projeto adotando ruído com um carimbo de rigor, que é pior
    que a média seca de antes, porque a média seca não finge.

    O limite é 20 de 200 (10%) e não 5%: o próprio número de falsos positivos é
    uma variável aleatória, e com 200 experimentos o desvio esperado já é de ~1,5
    pontos. Um teste que exigisse exatamente 5% piscaria vermelho sozinho."""
    import numpy as np

    falsos = 0
    for s in range(200):
        rng = np.random.default_rng(100 + s)
        antes = (rng.random(49) < 0.55).astype(float)
        depois = (rng.random(49) < 0.55).astype(float)
        if ic_do_delta(antes, depois).exclui_zero:
            falsos += 1

    assert falsos <= 20, (
        f"{falsos}/200 falsos positivos sob H0 — a regra de adoção estaria otimista "
        "e adotaria ruído com carimbo de rigor"
    )
