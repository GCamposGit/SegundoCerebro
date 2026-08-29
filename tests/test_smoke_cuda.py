"""O smoke da F3.6 não pode levantar só porque a máquina não tem GPU hoje."""

from __future__ import annotations

import os

import pytest

from segundocerebro.index.cuda_runtime import (
    CUDA13,
    DRIVER,
    EP_AUSENTE,
    MINILM,
    SEM_GPU,
    aplicar_provider,
    diagnosticar,
    resolver_provider,
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


def test_ort_cpu_tampando_gpu_nao_e_cuda13() -> None:
    """fastembed puxa onnxruntime 1.29 CPU e o extra [gpu] some. Não é CUDA 13."""
    diag = diagnosticar(
        gpus=MAXWELL,
        versao_ort="1.29.0",
        providers=["CPUExecutionProvider", "AzureExecutionProvider"],
    )
    assert not diag.ok
    assert diag.codigo == EP_AUSENTE
    assert "onnxruntime" in diag.mensagem
    assert "CUDA 13" not in diag.mensagem


def test_resolver_provider_config_vale_com_env_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pergunta "qual provider vence" não precisa escrever em lugar nenhum.

    Este teste chamava `aplicar_provider`, que escreve em `os.environ` — e o
    `monkeypatch.delenv` acima não desfazia, porque monkeypatch só restaura o que
    ele mesmo mexeu e a variável nem existia. `SEGUNDOCEREBRO_PROVIDER=cuda`
    sobrevivia à sessão e derrubava seis testes de `tests/test_watcher.py`.
    """
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    assert resolver_provider("cuda") == "cuda"
    assert os.environ.get("SEGUNDOCEREBRO_PROVIDER") is None, "resolver não escreve"


def test_resolver_provider_env_vence_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cpu")
    assert resolver_provider("cuda") == "cpu"


def test_aplicar_provider_publica_para_os_filhos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quem escreve é `aplicar_provider`, e só o `main()` de um processo a chama.

    A escrita é o mecanismo — os processos de embed herdam o ambiente —, então ela
    continua sendo testada. O que mudou é que agora o teste declara a variável
    antes, para o monkeypatch ter o que restaurar; e a fixture `ambiente_devolvido`
    de `tests/conftest.py` fecha a classe mesmo quando alguém esquecer.
    """
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "")
    assert aplicar_provider("cuda") == "cuda"
    assert os.environ["SEGUNDOCEREBRO_PROVIDER"] == "cuda"


def test_o_provider_nao_atravessa_para_o_teste_seguinte() -> None:
    """O teste acima escreveu `cuda` no ambiente; aqui já não está.

    É o caso concreto da classe que `tests/test_isolamento_da_suite.py` prova em
    geral, e mora aqui porque foi aqui que ela custou seis falhas.
    """
    assert (os.environ.get("SEGUNDOCEREBRO_PROVIDER") or "").lower() != "cuda"


def test_driver_590_no_maxwell_recusa_em_portugues() -> None:
    gpus = [{"name": "GTX 980 Ti", "driver": "590.26", "compute": "5.2", "memoria": "6 GiB"}]
    diag = diagnosticar(gpus=gpus, versao_ort="1.18.0")
    assert not diag.ok
    assert diag.codigo == DRIVER
    assert "590" in diag.mensagem
    assert "CPU" in diag.mensagem
    assert "sm_52" not in diag.mensagem
