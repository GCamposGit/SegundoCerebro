"""R5.2: the budget comes from the machine in front of us, not a magic number."""

from __future__ import annotations

from dataclasses import replace

from segundocerebro.config import carregar, nucleos_para
from segundocerebro.index.orcamento import Recursos, ajustar_ao_vivo, derivar, perfil_de_preset, preset_de

SEM_AMBIENTE: dict[str, str] = {}


def test_preset_leigo_mapeia_para_esforco() -> None:
    assert preset_de("discreto") == "discreto"
    assert perfil_de_preset("discreto") == "leve"
    assert perfil_de_preset("noturno") == "maximo"
    assert perfil_de_preset("automatico") == "normal"


def test_maquina_de_8gb_encolhe_lote_e_workers() -> None:
    """Acceptance: an 8 GB box gets a complete wave without OOM — by not grabbing 32×1024d.

    The Job Object in the dossie is the test harness; the product's job is to
    derive a budget that fits. Pin the formula, not a live 8 GB machine.
    """
    orc = derivar(
        Recursos(nucleos=4, ram_total_mb=8192, ram_livre_mb=2048, gpus=0),
        "automatico",
        lote_pedido=32,
    )
    assert orc.parse_workers == 1
    assert orc.lote_embed == 8
    assert orc.ram_parse_mb == 256


def test_usuario_ativo_no_automatico_cai_para_leve() -> None:
    """Acceptance: active user → the process yields. Mechanism, not a 30 s CPU sample.

    `leve` is 25% of the cores against `normal` at 50% — half the budget — plus
    BELOW_NORMAL that `esforco.aplicar` already knows. Measuring live CPU in CI
    is how a flaky test ships and a real regression hides.
    """
    folgado = Recursos(nucleos=8, ram_total_mb=32768, ram_livre_mb=16000, gpus=0, usuario_ativo=False)
    ocioso = derivar(folgado, "automatico")
    ativo = derivar(replace(folgado, usuario_ativo=True), "automatico")
    assert ocioso.perfil == "normal"
    assert ativo.perfil == "leve"
    assert nucleos_para(ativo.perfil, 8) <= nucleos_para(ocioso.perfil, 8) / 2


def test_noturno_nao_cede_ao_usuario() -> None:
    folgado = Recursos(nucleos=8, ram_total_mb=32768, ram_livre_mb=16000, gpus=0, usuario_ativo=True)
    orc = derivar(folgado, "noturno")
    assert orc.perfil == "maximo"
    assert ajustar_ao_vivo(orc, folgado).perfil == "maximo"


def test_ram_justa_encolhe_o_lote_mesmo_em_maquina_grande() -> None:
    folgado = Recursos(nucleos=8, ram_total_mb=32768, ram_livre_mb=400, gpus=0)
    orc = derivar(folgado, "normal", lote_pedido=32)
    assert orc.lote_embed == 8


def test_config_aceita_presets_do_leigo(tmp_path) -> None:  # noqa: ANN001
    caminho = tmp_path / "config.toml"
    caminho.write_text('[maquina]\nperfil = "automatico"\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente=SEM_AMBIENTE).maquina.perfil == "automatico"
    caminho.write_text('[maquina]\nperfil = "discreto"\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente=SEM_AMBIENTE).maquina.perfil == "leve"
    caminho.write_text('[maquina]\nperfil = "noturno"\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente=SEM_AMBIENTE).maquina.perfil == "maximo"
