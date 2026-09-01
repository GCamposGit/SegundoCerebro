"""O smoke da F3.6 não pode levantar só porque a máquina não tem GPU hoje."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from segundocerebro.index.cuda_runtime import (
    CUDA13,
    DRIVER,
    EP_AUSENTE,
    MINILM,
    SEM_GPU,
    SEM_ORT,
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
PROVIDER_INICIAL = os.environ.get("SEGUNDOCEREBRO_PROVIDER")
"""Valor herdado pela sessão; no Desktop é legitimamente ``cuda``."""


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


def test_sem_onnxruntime_recusa_em_portugues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Placa presente e o extra `[gpu]` ausente — o caso mais comum do leigo.

    Tinha mensagem e não tinha teste até 30/08/2026, e quem achou foi a guarda
    derivada abaixo, não uma leitura. É a diferença entre "a fase fechou" e "a
    fase fechou e alguém consegue provar".
    """
    # `_versao_ort` tem de ser dublado: nesta máquina o onnxruntime **está**
    # instalado (roda de CPU), então sem o dublê o diagnóstico cai no ramo
    # seguinte e o teste mediria outro caminho.
    monkeypatch.setattr("segundocerebro.index.cuda_runtime._versao_ort", lambda: None)
    diag = diagnosticar(gpus=MAXWELL, versao_ort=None, providers=None)
    assert not diag.ok
    assert diag.codigo == SEM_ORT
    assert "[gpu]" in diag.mensagem and "CPU" in diag.mensagem, diag.mensagem


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
    """O teste acima escreveu `cuda`; aqui o ambiente voltou ao valor herdado.

    É o caso concreto da classe que `tests/test_isolamento_da_suite.py` prova em
    geral, e mora aqui porque foi aqui que ela custou seis falhas. "Não é cuda"
    era uma guarda errada no próprio Desktop, cuja sessão começa em CUDA por
    configuração legítima; o contrato é não atravessar a mutação do teste.
    """
    assert os.environ.get("SEGUNDOCEREBRO_PROVIDER") == PROVIDER_INICIAL


def test_driver_590_no_maxwell_recusa_em_portugues() -> None:
    gpus = [{"name": "GTX 980 Ti", "driver": "590.26", "compute": "5.2", "memoria": "6 GiB"}]
    diag = diagnosticar(gpus=gpus, versao_ort="1.18.0")
    assert not diag.ok
    assert diag.codigo == DRIVER
    assert "590" in diag.mensagem
    assert "CPU" in diag.mensagem
    assert "sm_52" not in diag.mensagem


# --------------------------------------------------------------------------- #
# F6-C — toda recusa de GPU tem mensagem em português, e toda uma tem teste


def _motivos_declarados() -> dict[str, str]:
    """Motivo → mensagem, derivado do módulo. Motivo novo entra sozinho."""
    from segundocerebro.index import cuda_runtime as cr

    por_valor = {
        v: nome
        for nome, v in vars(cr).items()
        if nome.isupper() and not nome.startswith("MSG_") and isinstance(v, str) and v.islower()
    }
    return {v: nome for v, nome in por_valor.items() if f"MSG_{nome}" in vars(cr) or nome in {"OK"}}


def test_todo_motivo_de_recusa_tem_mensagem_em_portugues() -> None:
    """`F6-C`: numa máquina onde a GPU não serve, o produto **diz por quê**.

    A saída da fase é "com GPU incompatível o smoke recusa em português". A
    forma de errar isso não é não ter mensagem: é acrescentar um motivo novo e
    esquecer a mensagem, e aí a recusa sai como um código seco que não ajuda
    ninguém. A lista sai do módulo, então motivo novo nasce conferido.
    """
    from segundocerebro.index import cuda_runtime as cr

    faltando = []
    for valor, nome in _motivos_declarados().items():
        msg = getattr(cr, f"MSG_{nome}", None) or (cr.MSG_OK if nome == "OK" else None)
        if not msg or len(str(msg)) < 10:
            faltando.append(f"{nome}={valor!r}")
    assert not faltando, f"motivo de recusa sem mensagem: {faltando}"


def test_toda_recusa_alcancavel_tem_teste_proprio() -> None:
    """Cada motivo que `diagnosticar` pode devolver é exercitado neste arquivo.

    Derivado de `diagnosticar`, por AST: os `DiagnosticoCuda(...)` que ela
    constrói dizem quais motivos são alcançáveis. Se alguém acrescentar um ramo
    de recusa e não escrever o teste, isto reprova — que é a diferença entre
    "a fase fechou" e "a fase fechou e continua fechada".
    """
    import ast
    import inspect

    from segundocerebro.index import cuda_runtime as cr

    fonte = Path(inspect.getsourcefile(cr)).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    alvo = next(
        no for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef) and no.name == "diagnosticar"
    )
    # Só o **segundo** posicional: `DiagnosticoCuda(ok, codigo, mensagem)`, e o
    # que identifica a recusa é o código. Pegar os três também colhia a
    # mensagem e a lista saía com o dobro do tamanho, cheia de falso-positivo.
    alcancaveis = {
        no.args[1].id
        for no in ast.walk(alvo)
        if isinstance(no, ast.Call)
        and getattr(no.func, "id", "") == "DiagnosticoCuda"
        and len(no.args) >= 2
        and isinstance(no.args[1], ast.Name)
    }
    assert len(alcancaveis) >= 6, f"a varredura achou só {alcancaveis} — parou de ver"

    meu = Path(__file__).read_text(encoding="utf-8")
    sem_teste = [nome for nome in sorted(alcancaveis) if nome != "OK" and nome not in meu]
    assert not sem_teste, (
        f"motivo de recusa sem teste neste arquivo: {sem_teste}. A saída da `F6-C` é "
        "que a recusa saia em português — motivo novo precisa da prova junto."
    )


def test_sem_placa_a_suite_padrao_passa_e_o_produto_diz_cpu() -> None:
    """A outra metade da `F6-C`, e ela vale exatamente onde importa.

    "Numa máquina sem NVIDIA a indexação é CPU e a suíte padrão passa" — esta
    suíte é a prova, e este teste é a linha que a torna explícita: sem placa,
    `diagnosticar` recusa com a mensagem que manda usar CPU, e não levanta.
    """
    diag = diagnosticar(gpus=[], versao_ort=None, providers=None)
    assert diag.ok is False
    assert "cpu" in diag.mensagem.lower(), diag.mensagem
