"""Queue protocol of the dual-GPU embed pool — no CUDA, no encoder."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.index.gpu_pool import EmbedFila, _worker_eco, contar_gpus


def test_contar_gpus_sem_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    def some(*_a, **_k):  # noqa: ANN002, ANN003
        raise FileNotFoundError

    monkeypatch.setattr("segundocerebro.index.gpu_pool.subprocess.run", some)
    assert contar_gpus() == 0


def test_contar_gpus_conta_linhas(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bruto:
        returncode = 0
        stdout = "0, Enabled\n1, Disabled\n"

    monkeypatch.setattr(
        "segundocerebro.index.gpu_pool.subprocess.run", lambda *_a, **_k: Bruto()
    )
    assert contar_gpus() == 2


def test_dispositivos_embed_pula_display_so_no_perfil_leve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from segundocerebro.index.gpu_pool import dispositivos_embed

    class Bruto:
        returncode = 0
        stdout = "0, Enabled\n1, Disabled\n"

    monkeypatch.setattr(
        "segundocerebro.index.gpu_pool.subprocess.run", lambda *_a, **_k: Bruto()
    )
    assert dispositivos_embed() == ["0", "1"]
    assert dispositivos_embed(reservar_display=True) == ["1"]


def test_dispositivos_embed_mantem_tudo_se_todas_tem_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from segundocerebro.index.gpu_pool import dispositivos_embed

    class Bruto:
        returncode = 0
        stdout = "0, Enabled\n1, Enabled\n"

    monkeypatch.setattr(
        "segundocerebro.index.gpu_pool.subprocess.run", lambda *_a, **_k: Bruto()
    )
    assert dispositivos_embed() == ["0", "1"]


def test_embed_fila_exige_ao_menos_uma_gpu(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="1 GPU"):
        EmbedFila(0, modelo="falso", cache=tmp_path)


def test_fila_round_robin_com_eco(tmp_path: Path) -> None:
    fila = EmbedFila(2, modelo="falso", cache=tmp_path, alvo=_worker_eco)
    try:
        j1 = fila.submit(["aa", "bbb"])
        j2 = fila.submit(["c"])
        vistos: dict[int, list] = {}
        for _ in (j1, j2):
            got = fila.receber()
            assert got is not None
            jid, vetores = got
            vistos[jid] = vetores
        assert set(vistos) == {j1, j2}
        assert len(vistos[j1]) == 2
        assert float(vistos[j1][0][0]) == 2.0
        assert float(vistos[j2][0][0]) == 1.0
    finally:
        fila.fechar()
