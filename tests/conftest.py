"""Keep the default suite off the GPU pool.

This desktop has nvidia-smi and two cards. If SEGUNDOCEREBRO_PROVIDER=cuda is
in the user environment, every `indexar()` would spawn two encoder processes
and load e5-large. Tests never asked for that.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    """Recusa em milissegundos se uma passada estiver escrevendo o índice real.

    Sem isto a suíte espera `busy_timeout` do SQLite por consulta, sem linha de
    saída — 40 min no notebook com a passada de Meetings/ viva. CI não vê:
    clone fresco não tem `config.toml` nem índice.
    """
    config = Path("config.toml")
    if not config.exists():
        return
    try:
        from segundocerebro.config import carregar
        from segundocerebro.index.store import IndiceEmEscrita, recusar_se_indexando
    except Exception:  # noqa: BLE001 — suíte de ingestão sem o pacote completo
        return
    try:
        conf = carregar(config, validar=False)
    except Exception:  # noqa: BLE001 — config.toml local ilegível não aborta a suíte
        return
    ocupados = []
    for base in conf.bases:
        try:
            recusar_se_indexando(Path(base.indice))
        except IndiceEmEscrita as erro:
            ocupados.append(str(erro))
    if ocupados:
        pytest.exit("indexação viva — pause com comando.txt:\n" + "\n".join(ocupados), returncode=4)


@pytest.fixture(autouse=True)
def ambiente_devolvido() -> Iterator[None]:
    """Nenhum teste entrega `os.environ` alterado ao próximo — nem via produção.

    `monkeypatch.setenv/delenv` desfaz o que **o monkeypatch** fez. Escrita que
    veio do código de produto dentro do teste não é rastreada, e
    `monkeypatch.delenv(..., raising=False)` sobre variável ausente não registra
    nem sequer um valor a restaurar. Medido em 29/08/2026:
    `test_aplicar_provider_config_preenche_env_vazio` deixava
    `SEGUNDOCEREBRO_PROVIDER=cuda` no processo, e as seis primeiras chamadas a
    `indexar()` depois dele — todas em `tests/test_watcher.py`, que vem depois na
    ordem alfabética — falhavam com `RuntimeError: Não achei placa NVIDIA`. O
    mesmo arquivo passava verde sozinho, e no desktop, que tem placa, a suíte
    inteira passava: o modo de falha era assimétrico entre os dois setups.

    A foto aqui fecha a classe, e não o caso: vale para `CUDA_VISIBLE_DEVICES`,
    para `PATH` (que `cuda_runtime.preparar()` prepende) e para o próximo que
    alguém escrever sem lembrar de desfazer.
    """
    antes = dict(os.environ)
    try:
        yield
    finally:
        if os.environ != antes:
            os.environ.clear()
            os.environ.update(antes)


@pytest.fixture(autouse=True)
def sem_gpu_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("segundocerebro.index.gpu_pool.contar_gpus", lambda: 0)
    monkeypatch.setattr("segundocerebro.index.indexer.dispositivos_embed", lambda **_k: [])
    monkeypatch.setattr("segundocerebro.index.esforco.listar_gpus", lambda: [])


@pytest.fixture(autouse=True)
def calibracao_isolada(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    r"""A calibragem da máquina **nunca** é a real durante a suíte.

    `indexar()` grava coeficientes aprendidos em `%LOCALAPPDATA%\segundocerebro`,
    de propósito: é o que faz a segunda base indexar já calibrada. Mas a suíte
    roda `indexar()` com dublês de encoder, e sem isto ela escrevia estado real
    do usuário — 53 kB medidos em 27/08/2026, com três perfis de máquina
    (`falso:8`, `modelo-a:8`, `modelo-b:8`), sete linhas de formato com
    `base_id` de diretório temporário e 267 linhas na tabela do autoteste.

    O `model_id` entra na impressão da máquina, então o dublê não corrompia
    previsão de `e5-large` — foi sorte de projeto, não de teste. Isolar aqui, uma
    vez e para toda a suíte, é o que fecha a classe: teste novo que chame
    `indexar()` já nasce isolado sem ninguém lembrar.
    """
    destino = tmp_path_factory.mktemp("calibracao")
    monkeypatch.setenv("SEGUNDOCEREBRO_CALIBRACAO", str(destino))
    return destino
