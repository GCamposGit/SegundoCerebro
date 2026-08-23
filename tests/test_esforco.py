"""Plano de esforço: fração do hardware desta máquina, não número mágico."""

from __future__ import annotations

from pathlib import Path

from segundocerebro.config import nucleos_para
from segundocerebro.index.esforco import GpuInfo, PERFIS_DE_ESFORCO, ler_pedido, pedir, planar


def test_cpu_leve_e_normal_nunca_sao_100_por_cento() -> None:
    for n in (2, 4, 8, 12, 16, 20, 28):
        assert nucleos_para("leve", n) < n
        assert nucleos_para("normal", n) < n
        assert nucleos_para("maximo", n) == n
    assert nucleos_para("leve", 1) == 1
    assert nucleos_para("normal", 20) == 10  # i7 14ª geração, 20 fios
    assert nucleos_para("leve", 20) == 5


def test_uma_gpu_leve_e_normal_nao_vao_a_100() -> None:
    gpus = [GpuInfo("0", "NVIDIA GeForce RTX 4070", display=True)]
    leve = planar("leve", nucleos=20, gpus=gpus)
    normal = planar("normal", nucleos=20, gpus=gpus)
    maximo = planar("maximo", nucleos=20, gpus=gpus)
    assert leve.gpus[0].ativo and leve.gpus[0].percentual < 100
    assert normal.gpus[0].ativo and normal.gpus[0].percentual < 100
    assert maximo.gpus[0].percentual == 100


def test_duas_gpus_normal_nao_crava_gpu0() -> None:
    gpus = [
        GpuInfo("0", "GTX 980 Ti", display=True),
        GpuInfo("1", "GTX 980 Ti", display=False),
    ]
    normal = planar("normal", nucleos=16, gpus=gpus)
    por = {g.indice: g for g in normal.gpus}
    assert por["0"].percentual < 100
    assert por["0"].percentual < por["1"].percentual
    assert por["1"].ativo

    leve = planar("leve", nucleos=16, gpus=gpus)
    por_l = {g.indice: g for g in leve.gpus}
    assert not por_l["0"].ativo
    assert por_l["1"].ativo and por_l["1"].percentual < 100

    maximo = planar("maximo", nucleos=16, gpus=gpus)
    assert all(g.percentual == 100 for g in maximo.gpus)


def test_sem_gpu_o_plano_so_tem_cpu() -> None:
    plano = planar("normal", nucleos=8, gpus=[])
    assert plano.gpus == ()
    assert plano.cpu_percentual == 50
    assert plano.cpu_nucleos == 4


def test_pedido_ao_vivo_grava_e_le(tmp_path: Path) -> None:
    assert ler_pedido(tmp_path) is None
    pedir(tmp_path, "maximo")
    assert ler_pedido(tmp_path) == "maximo"
    pedir(tmp_path, "leve")
    assert ler_pedido(tmp_path) == "leve"


def test_perfis_canonicos_sao_tres() -> None:
    assert PERFIS_DE_ESFORCO == ("leve", "normal", "maximo")
