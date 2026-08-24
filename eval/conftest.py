"""Eval recusa índice em escrita — o mesmo contrato de tests/conftest.py.

`pytest eval/` não carrega `tests/conftest.py`. Sem isto, `eval.rodar` e os
testes que abrem o índice real esperam a trava do SQLite em silêncio.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    config = Path("config.toml")
    if not config.exists():
        return
    try:
        from segundocerebro.config import carregar
        from segundocerebro.index.store import IndiceEmEscrita, recusar_se_indexando
    except Exception:  # noqa: BLE001
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
