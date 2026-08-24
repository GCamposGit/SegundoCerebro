"""Keep the default suite off the GPU pool.

This desktop has nvidia-smi and two cards. If SEGUNDOCEREBRO_PROVIDER=cuda is
in the user environment, every `indexar()` would spawn two encoder processes
and load e5-large. Tests never asked for that.
"""

from __future__ import annotations

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
    except Exception:  # noqa: BLE001
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
def sem_gpu_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("segundocerebro.index.indexer.contar_gpus", lambda: 0)
    monkeypatch.setattr("segundocerebro.index.indexer.dispositivos_embed", lambda **_k: [])
    monkeypatch.setattr("segundocerebro.index.esforco.listar_gpus", lambda: [])
