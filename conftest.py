"""O que vale para as duas suítes — `tests/` e `eval/`.

Existe porque `pytest eval/` **não** carrega `tests/conftest.py`, e as duas
precisavam das mesmas duas coisas. A resposta anterior tinha sido copiar: o
`pytest_sessionstart` estava escrito duas vezes, linha por linha, em
`tests/conftest.py` e em `eval/conftest.py`. Cópia de guarda é a forma de defeito
que este repositório mais encontrou — a segunda cópia não falha quando diverge,
ela só deixa de guardar um dos lados, em silêncio.

Um `conftest.py` na raiz é carregado por qualquer invocação de pytest cujo
`rootdir` seja este (o `pyproject.toml` fixa isso), inclusive `pytest eval/`
sozinho. O que é específico de uma suíte continua no conftest dela: as fixtures
de GPU e de calibragem só fazem sentido para quem chama `indexar()`.
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
    alguém escrever sem lembrar de desfazer. Mora na raiz para valer também em
    `pytest eval/`, que não carrega o conftest de `tests/`.
    """
    # O pytest atualiza esta chave entre setup/call/teardown. Ela é um marcador
    # do próprio executor, não estado do produto que a fixture precise copiar.
    sentinel = "PYTEST_CURRENT_TEST"
    antes = {chave: valor for chave, valor in os.environ.items() if chave != sentinel}
    try:
        yield
    finally:
        atual = {chave: valor for chave, valor in os.environ.items() if chave != sentinel}
        for chave in atual.keys() - antes.keys():
            del os.environ[chave]
        for chave, valor in antes.items():
            if atual.get(chave) != valor:
                os.environ[chave] = valor
