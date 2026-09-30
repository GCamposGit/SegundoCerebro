"""CPU continua o padrão; CUDA só quando a placa e o runtime realmente servem."""

from __future__ import annotations

import pytest

from segundocerebro.index.cuda_runtime import (
    KERNEL_FALHOU,
    CUDA13,
    OK,
    DiagnosticoCuda,
    DispositivoCuda,
    EP_AUSENTE,
    aplicar_provider,
    provider_da_etapa,
    resolver_provider,
    selecionar_dispositivo,
    sondar_hardware,
)


def test_sem_runtime_cuda_continua_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(False, EP_AUSENTE, "sem ep"),
    )
    assert resolver_provider(None) == "cpu"


def test_cuda_entra_quando_a_placa_responde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(True, OK, "ok"),
    )
    assert resolver_provider(None) == "cuda"


def test_env_cpu_vence_mesmo_com_placa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cpu")
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(True, OK, "ok"),
    )
    assert resolver_provider(None) == "cpu"


def _gpu(indice: int, livre: int) -> dict[str, str]:
    return {
        "indice": str(indice),
        "name": f"GPU {indice}",
        "driver": "550.00",
        "compute": "8.6",
        "memoria": "8192 MiB",
        "memoria_livre": f"{livre} MiB",
    }


def test_cpu_only_never_selects_cuda_e_registra_kernel_cpu() -> None:
    executados: list[tuple[str, int | None]] = []

    def executar(provider: str, indice: int | None) -> tuple[bool, str]:
        executados.append((provider, indice))
        return provider == "CPUExecutionProvider", "sonda sintética"

    diag = sondar_hardware(
        gpus=[],
        versao_ort="1.23.2",
        providers=["CPUExecutionProvider"],
        executar_kernel=executar,
        cpu="CPU sintética",
    )

    assert not diag.ok
    assert diag.cpu == "CPU sintética"
    assert diag.providers_com_kernel == ("CPUExecutionProvider",)
    assert selecionar_dispositivo(diag) is None
    assert executados == [("CPUExecutionProvider", None)]


def test_provider_anunciado_com_kernel_cuda_quebrado_recusa_gpu() -> None:
    def executar(provider: str, _indice: int | None) -> tuple[bool, str]:
        return (provider == "CPUExecutionProvider", "cuDNN ausente")

    diag = sondar_hardware(
        gpus=[_gpu(0, 4096)],
        versao_ort="1.23.2",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        executar_kernel=executar,
    )

    assert not diag.ok
    assert diag.codigo == KERNEL_FALHOU
    assert diag.providers_anunciados[0] == "CUDAExecutionProvider"
    assert diag.providers_com_kernel == ("CPUExecutionProvider",)
    assert "cuDNN ausente" in diag.dispositivos[0].motivo


def test_incompatibilidade_ainda_relata_gpu_vram_e_build() -> None:
    diag = sondar_hardware(
        gpus=[
            {
                "indice": "0",
                "id_fisico": "0",
                "name": "GPU Maxwell sintética",
                "driver": "580.00",
                "compute": "5.2",
                "memoria": "8 GiB",
                "memoria_livre": "6 GiB",
            }
        ],
        versao_ort="1.27.0",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        executar_kernel=lambda provider, _indice: (provider == "CPUExecutionProvider", ""),
        build_ort="CUDA 13 sintético",
    )

    assert diag.codigo == CUDA13
    assert diag.build_ort == "CUDA 13 sintético"
    assert diag.dispositivos[0].nome == "GPU Maxwell sintética"
    assert diag.dispositivos[0].memoria_total_mb == 8192
    assert diag.dispositivos[0].memoria_livre_mb == 6144
    assert not diag.dispositivos[0].kernel_ok


def test_provedor_explicitamente_cuda_regride_para_cpu_com_motivo(monkeypatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    monkeypatch.setattr("segundocerebro.index.cuda_runtime.preparar", lambda: None)
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar_inicializacao",
        lambda: DiagnosticoCuda(False, KERNEL_FALHOU, "kernel CUDA falhou"),
    )

    assert aplicar_provider(None) == "cpu"
    assert __import__("os").environ["SEGUNDOCEREBRO_PROVIDER"] == "cpu"


def test_etapas_escolhem_gpus_conforme_vram_e_falham_em_cpu(monkeypatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    diag = DiagnosticoCuda(
        True,
        OK,
        "CUDA pronta",
        dispositivos=(
            DispositivoCuda(0, "GPU 0", "8.6", 8192, 1200, True),
            DispositivoCuda(1, "GPU 1", "8.6", 8192, 5000, True),
        ),
    )
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar_inicializacao", lambda: diag
    )

    assert selecionar_dispositivo(diag, memoria_minima_mb=768, indices_permitidos={0}).indice == 0
    assert selecionar_dispositivo(diag, memoria_minima_mb=3072).indice == 1
    assert selecionar_dispositivo(diag, memoria_minima_mb=6000) is None

    provider, indice, motivo = provider_da_etapa("embedding", memoria_minima_mb=6000)
    assert (provider, indice) == ("cpu", None)
    assert "6000 MB livres" in motivo


def test_kernel_minimo_declarado_roda_no_provider_solicitado() -> None:
    from segundocerebro.index.cuda_runtime import _executar_kernel_minimo

    ok, motivo = _executar_kernel_minimo("CPUExecutionProvider", None)

    assert ok, motivo
