"""O que é só de `tests/`: dublê de GPU, isolamento da calibragem, e o `store`.

As fixtures aqui existem para quem chama `indexar()`, e `eval/` não indexa. O
que vale para as duas suítes — a recusa de índice em escrita e a devolução de
`os.environ` — mora no `conftest.py` da raiz, que `pytest eval/` também carrega.

`store` chegou em 30/08/2026 pelo `Q17`: ela estava escrita **duas vezes**, uma
em `test_index.py` e outra em `test_grafo.py`, textualmente iguais a menos de
uma linha em branco. Fixture compartilhada mora em conftest; os dublês que são
classe e função moram em `tests/falsos.py`, porque conftest não se importa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.index.store import Store

from tests.falsos import DIM


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


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "indice", DIM)
    yield s
    s.fechar()
