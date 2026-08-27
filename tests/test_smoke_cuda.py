"""O smoke da F3.6 não pode levantar só porque a máquina não tem GPU hoje."""

from __future__ import annotations

from segundocerebro.index.cuda_runtime import (
    CUDA13,
    DRIVER,
    MINILM,
    SEM_GPU,
    diagnosticar,
)
from segundocerebro.index.smoke_cuda import (
    CANDIDATOS_RERANK,
    _gpus,
    _scores_finitos,
    passagens_rerank,
)

MAXWELL = [{"name": "GTX 980 Ti", "driver": "582.28", "compute": "5.2", "memoria": "6 GiB"}]


def test_gpus_devolve_lista() -> None:
    assert isinstance(_gpus(), list)


def test_passagens_rerank_tamanho() -> None:
    docs = passagens_rerank(CANDIDATOS_RERANK)
    assert len(docs) == CANDIDATOS_RERANK
    assert all(docs)
    assert passagens_rerank(1)[0] == docs[0]


def test_scores_finitos() -> None:
    assert _scores_finitos([0.1, -1.2, 3.0])
    assert not _scores_finitos([0.1, float("nan")])
    assert not _scores_finitos([float("inf")])
    assert not _scores_finitos([])


def test_sem_gpu_explica_cpu_em_portugues() -> None:
    diag = diagnosticar(gpus=[], versao_ort="1.18.0")
    assert not diag.ok
    assert diag.codigo == SEM_GPU
    assert "CPU" in diag.mensagem
    assert "NVIDIA" in diag.mensagem
    assert "F3.6" not in diag.mensagem
    assert "sm_52" not in diag.mensagem


def test_cuda13_no_maxwell_recusa_em_portugues() -> None:
    diag = diagnosticar(gpus=MAXWELL, versao_ort="1.27.0")
    assert not diag.ok
    assert diag.codigo == CUDA13
    assert "CUDA 13" in diag.mensagem
    assert "CPU" in diag.mensagem
    assert "sm_52" not in diag.mensagem


def test_cuda13_em_placa_nova_nao_e_recusa_por_si() -> None:
    """CUDA 13 largou Maxwell, não uma 4070. A recusa é a combinação."""
    gpus = [{"name": "RTX 4070", "driver": "560.0", "compute": "8.9", "memoria": "12 GiB"}]
    diag = diagnosticar(gpus=gpus, versao_ort="1.27.0", providers=["CUDAExecutionProvider"])
    assert diag.ok


def test_minilm_no_cuda_recusa_em_portugues() -> None:
    diag = diagnosticar(modelo="minilm", gpus=MAXWELL, versao_ort="1.18.0")
    assert not diag.ok
    assert diag.codigo == MINILM
    assert "NaN" in diag.mensagem
    assert "CPU" in diag.mensagem


def test_ort_118_no_maxwell_e_aceitavel() -> None:
    diag = diagnosticar(
        gpus=MAXWELL, versao_ort="1.18.0", providers=["CUDAExecutionProvider"]
    )
    assert diag.ok


def test_driver_590_no_maxwell_recusa_em_portugues() -> None:
    gpus = [{"name": "GTX 980 Ti", "driver": "590.26", "compute": "5.2", "memoria": "6 GiB"}]
    diag = diagnosticar(gpus=gpus, versao_ort="1.18.0")
    assert not diag.ok
    assert diag.codigo == DRIVER
    assert "590" in diag.mensagem
    assert "CPU" in diag.mensagem
    assert "sm_52" not in diag.mensagem
