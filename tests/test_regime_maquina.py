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
    topologia,
)


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
