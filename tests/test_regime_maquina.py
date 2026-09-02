"""F4-R.1: the product can observe and set the scheduling regime.

These tests do not measure encoder throughput and do not load a model. They
prove the class: a speed number without battery + EcoQoS + topology is the
defect that produced the 16.1 retraction. The slow/fast pair itself is in
`docs/afinidade-e-estado-de-maquina.md`, measured on this machine.
"""

from __future__ import annotations

import os

import pytest

from segundocerebro.index.esforco import observar_regime
from segundocerebro.index.regime_maquina import (
    aplicar_ecoqos,
    ecoqos_ativo,
    mascara_afinidade,
    mascara_mista,
    topologia,
)

# The 1355U package that discovered the class: first-N mixes 4 P + 2 E.
TOPO_1355U = {"p": [0, 1, 2, 3], "e": list(range(4, 12)), "regra": "smt", "logicos": 12}
# This 14700HX: first-N is P-only. Copying [0,2,4,5,6,7] would still be all P.
TOPO_14700HX = {"p": list(range(16)), "e": list(range(16, 28)), "regra": "smt", "logicos": 28}


def test_observar_regime_sempre_traz_as_chaves() -> None:
    dados = observar_regime()
    for chave in ("tomada", "ecoqos", "topologia", "bateria_pct"):
        assert chave in dados, chave
    assert dados["tomada"] in (True, False, None)
    assert dados["ecoqos"] in (True, False, None)


def test_topologia_particiona_os_logicos() -> None:
    t = topologia()
    assert t["regra"] in {"smt", "homogeneo", "desconhecido"}
    p, e = set(t["p"]), set(t["e"])
    assert not (p & e)
    assert t["logicos"] == len(p) + len(e)
    if t["regra"] != "desconhecido":
        assert p | e == set(range(t["logicos"]))


@pytest.mark.skipif(os.name != "nt", reason="EcoQoS is a Windows process information class")
def test_ecoqos_liga_e_desliga_e_devolve_o_processo() -> None:
    """The trigger of R.1 is a command, not a window of luck.

    Restores the previous state: leaving EcoQoS on would slow the rest of the
    suite by the same ratio the package exists to record.
    """
    antes = ecoqos_ativo()
    try:
        assert aplicar_ecoqos(True) is True
        assert ecoqos_ativo() is True
        assert aplicar_ecoqos(False) is False
        assert ecoqos_ativo() is False
    finally:
        if antes is not None:
            aplicar_ecoqos(antes)


@pytest.mark.skipif(os.name == "nt", reason="POSIX has no EcoQoS API")
def test_ecoqos_ausente_no_posix_nao_mente() -> None:
    assert ecoqos_ativo() is None
    assert aplicar_ecoqos(True) is None


def test_r3_candidato_no_1355u_e_o_que_os_numeros_sugeriram() -> None:
    """First-N is the defect. The mix candidate is [0,2,4,5,6,7], not a copied list."""
    assert mascara_mista(6, TOPO_1355U) == [0, 2, 4, 5, 6, 7]
    assert mascara_mista(6, TOPO_1355U) != list(range(6))
    e = set(TOPO_1355U["e"])
    assert len(set(range(6)) & e) == 2
    assert len(set(mascara_mista(6, TOPO_1355U)) & e) == 4


def test_r3_candidato_no_14700hx_mistura_e_core() -> None:
    """On this CPU first-N is all P-core. The mix still takes E-cores — and lost."""
    cand = mascara_mista(6, TOPO_14700HX)
    assert cand == [0, 2, 16, 17, 18, 19]
    assert cand != list(range(6))
    assert set(cand) & set(TOPO_14700HX["e"])
    assert set(cand) & set(TOPO_14700HX["p"])


def test_r3_produto_e_so_p_core() -> None:
    """The mix lost (1.76× vs P-only). Product never pads with E-cores."""
    assert mascara_afinidade(6, TOPO_1355U) == [0, 1, 2, 3]
    assert 4 not in mascara_afinidade(6, TOPO_1355U)
    assert mascara_afinidade(6, TOPO_14700HX) == [0, 1, 2, 3, 4, 5]
    assert not (set(mascara_afinidade(14, TOPO_14700HX)) & set(TOPO_14700HX["e"]))
    assert mascara_afinidade(28, TOPO_14700HX) == list(range(16))


def test_r3_homogeneo_fica_com_os_primeiros_n() -> None:
    topo = {"p": list(range(8)), "e": [], "regra": "homogeneo", "logicos": 8}
    assert mascara_afinidade(6, topo) == [0, 1, 2, 3, 4, 5]
    assert mascara_mista(6, topo) == [0, 1, 2, 3, 4, 5]


def test_r3_mascara_cabe_na_maquina() -> None:
    for fn in (mascara_afinidade, mascara_mista):
        for topo in (TOPO_1355U, TOPO_14700HX):
            n_log = topo["logicos"]
            for n in (1, 2, 6, n_log // 2, n_log):
                mask = fn(n, topo)
                assert mask, fn.__name__
                assert len(set(mask)) == len(mask)
                assert min(mask) >= 0
                assert max(mask) < n_log
                assert set(mask) <= set(topo["p"]) | set(topo["e"])
