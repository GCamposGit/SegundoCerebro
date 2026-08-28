"""O instrumento de vazão por regime — o que ele tem de recusar.

Estes testes não medem velocidade e não carregam modelo. Eles provam que o
módulo torna impossível o defeito de método que produziu a retratação do achado
16.1: bloco por braço em vez de intercalado, uma réplica tratada como contraste,
e regime de máquina fora do relato.
"""

from __future__ import annotations

import pytest

from eval.regime import (
    REPLICAS_MINIMAS,
    Observacao,
    contraste,
    ordem_intercalada,
    plano_de_bracos,
    rodar,
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

    def test_sem_mudanca_nao_tem_ressalva(self) -> None:
        saida = contraste([_obs("livre", [0.2, 0.2]), _obs("livre", [0.2, 0.2])])
        assert saida["ressalva"] is None


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
