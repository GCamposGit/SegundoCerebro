"""A suíte não entrega estado de um teste para o próximo.

Existe por um incidente com nome e número. Em 28/08/2026 o PR #48 acrescentou um
teste que chamava `aplicar_provider("cuda")` — código de produto, que escreve em
`os.environ`. O teste tinha `monkeypatch.delenv(..., raising=False)` antes, e
isso parece isolamento e não é: o monkeypatch restaura o que **ele** mexeu, e
sobre uma variável ausente ele não registra nada. `SEGUNDOCEREBRO_PROVIDER=cuda`
sobrevivia ao teste, ao módulo e à sessão inteira do pytest.

O sintoma aparecia em outro arquivo: as seis primeiras chamadas a `indexar()`
depois dele — todas em `tests/test_watcher.py`, que vem depois na ordem
alfabética — falhavam com `RuntimeError: Não achei placa NVIDIA`, enquanto o
arquivo passava verde quando rodado sozinho. E o modo de falha era assimétrico
entre os dois setups: no desktop, que tem placa, `diagnosticar()` diz `ok` e a
suíte inteira ficava verde. Quem só roda lá nunca via.

O que este arquivo prova é a **guarda**, não o caso: `ambiente_devolvido`, em
`tests/conftest.py`, tira uma foto de `os.environ` antes de cada teste e a
devolve depois. Os dois testes abaixo são deterministicamente ordenados — pytest
executa na ordem de definição dentro de um módulo — e é essa ordem que constitui
a prova: o primeiro suja, o segundo confere que a sujeira não chegou.
"""

from __future__ import annotations

import os

SENTINELA = "SEGUNDOCEREBRO_TESTE_VAZAMENTO"


def test_um_teste_escreve_no_ambiente_como_o_produto_escreveria() -> None:
    """Escrita direta em `os.environ`, sem monkeypatch — igual à do produto."""
    os.environ[SENTINELA] = "vazou"
    assert os.environ[SENTINELA] == "vazou"


def test_o_teste_seguinte_nao_recebe_o_que_o_anterior_escreveu() -> None:
    assert SENTINELA not in os.environ, (
        "a fixture `ambiente_devolvido` de tests/conftest.py parou de restaurar "
        "`os.environ` — sem ela, escrita de produção dentro de um teste envenena "
        "todos os que rodarem depois, e o sintoma aparece em outro arquivo"
    )
