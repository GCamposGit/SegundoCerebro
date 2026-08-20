"""Keep the default suite off the GPU pool.

This desktop has nvidia-smi and two cards. If SEGUNDOCEREBRO_PROVIDER=cuda is
in the user environment, every `indexar()` would spawn two encoder processes
and load e5-large. Tests never asked for that.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def sem_gpu_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("segundocerebro.index.indexer.contar_gpus", lambda: 0)
