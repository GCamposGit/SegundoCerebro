"""O instrumento de vazão por regime — o que ele tem de recusar.

Estes testes não medem velocidade e não carregam modelo. Eles provam que o
módulo torna impossível o defeito de método que produziu a retratação do achado
16.1: bloco por braço em vez de intercalado, uma réplica tratada como contraste,
e regime de máquina fora do relato.
"""

from __future__ import annotations

import os

import pytest

from eval.regime import (
    REPLICAS_MINIMAS,
    Observacao,
    contraste,
    estado,
    ordem_intercalada,
    plano_de_bracos,
    plano_ecoqos,
    plano_mascara,
    rodar,
    veredito_r3,
)


def _obs(braco: str, tempos: list[float], *, tomada_antes=True, tomada_depois=True) -> Observacao:
    return Observacao(
        braco=braco,
        s_chunk=tempos,
        estado_antes={"tomada": tomada_antes, "maquina": "teste"},
        estado_depois={"tomada": tomada_depois, "maquina": "teste"},
    )


class TestOrdemIntercalada:
    def test_alterna_em_vez_de_bloquear(self) -> None:
        """AA/BB é o que produziu causa falsa: o regime muda entre os blocos."""
        assert ordem_intercalada(["a", "b"], 3) == ["a", "b", "a", "b", "a", "b"]

    def test_recusa_zero_replicas(self) -> None:
        with pytest.raises(ValueError):
            ordem_intercalada(["a", "b"], 0)


class TestContrasteRecusa:
    def test_uma_replica_por_braco_e_recusada(self) -> None:
        """Uma réplica mede a janela. Recusar é a entrega; devolver razão seria o defeito."""
        saida = contraste([_obs("livre", [0.2]), _obs("contiguo", [3.1])])
        assert saida["veredito"] == "recusado"
        assert "réplicas por braço" in str(saida["motivo"])
        assert "bracos" not in saida

    def test_ecoqos_nao_aplicado_e_recusado(self) -> None:
        """ctypes sem argtypes 'rodava' e devolveva 1,1× — número plausível, gatilho morto."""
        morto = [
            Observacao(
                braco=nome,
                s_chunk=[0.2, 0.2],
                estado_antes={"tomada": True, "ecoqos": None},
                estado_depois={"tomada": True, "ecoqos": None},
            )
            for nome in ("contiguo_off", "contiguo_on", "contiguo_off", "contiguo_on")
        ]
        saida = contraste(morto)
        assert saida["veredito"] == "recusado"
        assert "EcoQoS" in str(saida["motivo"])

    def test_razao_contra_off_quando_o_gatilho_aplicou(self) -> None:
        pares = []
        for _ in range(2):
            pares.append(
                Observacao(
                    braco="contiguo_off",
                    s_chunk=[0.0365, 0.0365],
                    estado_antes={"tomada": True, "ecoqos": False},
                    estado_depois={"tomada": True, "ecoqos": False},
                )
            )
            pares.append(
                Observacao(
                    braco="contiguo_on",
                    s_chunk=[0.1357, 0.1357],
                    estado_antes={"tomada": True, "ecoqos": True},
                    estado_depois={"tomada": True, "ecoqos": True},
                )
            )
        saida = contraste(pares)
        assert saida["veredito"] == "medido"
        assert saida["bracos"]["contiguo_on"]["razao_contra_off"] == 3.72

    def test_um_braco_magro_derruba_o_contraste_inteiro(self) -> None:
        saida = contraste(
            [_obs("livre", [0.2]), _obs("livre", [0.21]), _obs("contiguo", [3.1])]
        )
        assert saida["veredito"] == "recusado"
        assert "contiguo" in str(saida["motivo"])


class TestContrasteMede:
    def test_razao_contra_livre_com_replicas_suficientes(self) -> None:
        saida = contraste(
            [
                _obs("livre", [0.20, 0.20, 0.20]),
                _obs("contiguo", [3.00, 3.00, 3.00]),
                _obs("livre", [0.20, 0.20, 0.20]),
                _obs("contiguo", [3.00, 3.00, 3.00]),
            ]
        )
        assert saida["veredito"] == "medido"
        assert saida["bracos"]["livre"]["razao_contra_livre"] == 1.0
        assert saida["bracos"]["contiguo"]["razao_contra_livre"] == 15.0

    def test_replicas_minimas_e_o_limite_declarado(self) -> None:
        obs = [_obs("livre", [0.2]) for _ in range(REPLICAS_MINIMAS)]
        assert contraste(obs)["veredito"] == "medido"


class TestRegimeNoRelato:
    def test_mudanca_de_tomada_no_meio_vira_ressalva(self) -> None:
        """22× de variação por regime: número medido a cavalo de uma troca não vale."""
        saida = contraste(
            [
                _obs("livre", [0.2, 0.2]),
                _obs("livre", [0.2, 0.2], tomada_antes=True, tomada_depois=False),
            ]
        )
        assert saida["veredito"] == "medido_com_ressalva"
        assert "livre" in str(saida["ressalva"])

    def test_mudanca_de_ecoqos_no_meio_vira_ressalva(self) -> None:
        a = Observacao(
            braco="contiguo",
            s_chunk=[0.2, 0.2],
            estado_antes={"tomada": True, "ecoqos": False},
            estado_depois={"tomada": True, "ecoqos": True},
        )
        b = Observacao(
            braco="contiguo",
            s_chunk=[0.2, 0.2],
            estado_antes={"tomada": True, "ecoqos": False},
            estado_depois={"tomada": True, "ecoqos": False},
        )
        saida = contraste([a, b])
        assert saida["veredito"] == "medido_com_ressalva"
        assert "contiguo" in str(saida["ressalva"])

    def test_sem_mudanca_nao_tem_ressalva(self) -> None:
        saida = contraste([_obs("livre", [0.2, 0.2]), _obs("livre", [0.2, 0.2])])
        assert saida["ressalva"] is None

    def test_estado_traz_ecoqos_e_tomada(self) -> None:
        dados = estado()
        assert "tomada" in dados
        assert "ecoqos" in dados
        assert "topologia" in dados


class TestPlanoDeBracos:
    def test_derivado_da_topologia_e_nao_cravado(self) -> None:
        """O produto roda em máquina desconhecida: 12 lógicos não pode estar no código."""
        p = plano_de_bracos(12, 6)
        assert p["livre"] is None
        assert p["contiguo"] == [0, 1, 2, 3, 4, 5]
        assert p["espalhado"] == [0, 2, 4, 6, 8, 10]
        assert p["altos"] == [6, 7, 8, 9, 10, 11]

    def test_altos_difere_de_contiguo_e_e_o_par_que_achou_o_mecanismo(self) -> None:
        p = plano_de_bracos(12, 6)
        assert p["altos"] != p["contiguo"]

    @pytest.mark.parametrize("n_log,n_braco", [(1, 1), (2, 1), (4, 2), (8, 6), (12, 6), (20, 10)])
    def test_toda_mascara_cabe_na_maquina(self, n_log: int, n_braco: int) -> None:
        for nome, mascara in plano_de_bracos(n_log, n_braco).items():
            if mascara is None:
                continue
            assert mascara, nome
            assert min(mascara) >= 0, nome
            assert max(mascara) < n_log, nome
            assert len(set(mascara)) == len(mascara), nome


class TestPlanoEcoqos:
    def test_mesma_mascara_nos_dois_bracos(self) -> None:
        bracos, flags = plano_ecoqos(12, 6)
        assert bracos["contiguo_off"] == bracos["contiguo_on"] == [0, 1, 2, 3, 4, 5]
        assert flags == {"contiguo_off": False, "contiguo_on": True}


class TestPlanoMascara:
    def test_candidato_no_1355u_nao_e_os_primeiros_n(self) -> None:
        topo = {"p": [0, 1, 2, 3], "e": list(range(4, 12)), "regra": "smt", "logicos": 12}
        p = plano_mascara(12, 6, topo)
        assert p["livre"] is None
        assert p["contiguo"] == [0, 1, 2, 3, 4, 5]
        assert p["candidato"] == [0, 2, 4, 5, 6, 7]

    def test_candidato_no_14700hx_nao_copia_a_lista_do_1355u(self) -> None:
        topo = {"p": list(range(16)), "e": list(range(16, 28)), "regra": "smt", "logicos": 28}
        p = plano_mascara(28, 6, topo)
        assert p["candidato"] == [0, 2, 16, 17, 18, 19]
        assert p["candidato"] != [0, 2, 4, 5, 6, 7]


class TestVereditoR3:
    @staticmethod
    def _bloco(livre: float, contig: float, cand: float) -> dict:
        def braco(v: float) -> dict:
            return {"medianas": [v, v], "mediana_das_replicas": v, "regime_mudou": False}

        return {
            "veredito": "medido",
            "bracos": {"livre": braco(livre), "contiguo": braco(contig), "candidato": braco(cand)},
        }

    def test_adota_quando_ganha_no_lento_e_nao_regressa_no_benigno(self) -> None:
        saida = veredito_r3(self._bloco(1.0, 8.0, 1.2), self._bloco(1.0, 1.0, 1.05))
        assert saida["decisao"] == "adotar_candidato"
        assert saida["passa_lento"] is True
        assert saida["passa_benigno"] is True

    def test_empate_no_lento_remove_a_mascara(self) -> None:
        """Hypothesis refuted: the mix did not separate from first-N."""
        saida = veredito_r3(self._bloco(1.0, 1.3, 1.3), self._bloco(1.0, 1.0, 1.0))
        assert saida["decisao"] == "remover_mascara"
        assert saida["empate_lento"] is True

    def test_estoura_teto_lento_remove(self) -> None:
        saida = veredito_r3(self._bloco(1.0, 8.0, 2.0), self._bloco(1.0, 1.0, 1.0))
        assert saida["passa_lento"] is False
        assert saida["decisao"] == "remover_mascara"

    def test_estoura_teto_benigno_remove(self) -> None:
        saida = veredito_r3(self._bloco(1.0, 8.0, 1.2), self._bloco(1.0, 1.0, 1.3))
        assert saida["passa_benigno"] is False
        assert saida["decisao"] == "remover_mascara"

    def test_recusa_propaga(self) -> None:
        saida = veredito_r3({"veredito": "recusado", "motivo": "EcoQoS"}, self._bloco(1, 1, 1))
        assert saida["veredito"] == "recusado"


class TestRodar:
    def test_intercala_e_rotula_cada_observacao(self) -> None:
        vistos: list[str] = []

        def executor(nome, mascara):  # noqa: ANN001, ANN202
            vistos.append(nome)
            return Observacao(
                braco="", s_chunk=[0.2], estado_antes={}, estado_depois={}, mascara=mascara or []
            )

        obs = rodar({"livre": None, "contiguo": [0, 1]}, replicas=2, executor=executor)
        assert vistos == ["livre", "contiguo", "livre", "contiguo"]
        assert [o.braco for o in obs] == ["livre", "contiguo", "livre", "contiguo"]

    def test_contraste_ecoqos_intercala_off_on(self) -> None:
        vistos: list[str] = []

        def executor(nome, mascara):  # noqa: ANN001, ANN202
            vistos.append(nome)
            return Observacao(
                braco="", s_chunk=[0.2], estado_antes={}, estado_depois={}, mascara=mascara or []
            )

        bracos, _flags = plano_ecoqos(8, 6)
        obs = rodar(bracos, replicas=2, executor=executor)
        assert vistos == ["contiguo_off", "contiguo_on", "contiguo_off", "contiguo_on"]
        assert [o.braco for o in obs] == vistos


@pytest.mark.skipif(os.name != "nt", reason="EcoQoS is Windows")
def test_sonda_grava_ecoqos_sem_carregar_encoder() -> None:
    """The on-demand path records the trigger. Restores affinity and EcoQoS."""
    import psutil

    from eval.regime import medir_neste_processo
    from segundocerebro.index.regime_maquina import aplicar_ecoqos, ecoqos_ativo

    proc = psutil.Process()
    afinidade = proc.cpu_affinity()
    antes = ecoqos_ativo()
    try:
        obs = medir_neste_processo([0], 1, 1, ecoqos=True, sonda=True)
        assert obs.estado_antes.get("ecoqos") is True
        assert obs.estado_depois.get("ecoqos") is True
        assert 0 in obs.mascara
        obs_off = medir_neste_processo([0], 1, 1, ecoqos=False, sonda=True)
        assert obs_off.estado_antes.get("ecoqos") is False
    finally:
        proc.cpu_affinity(afinidade)
        if antes is not None:
            aplicar_ecoqos(antes)
