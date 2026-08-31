"""Só o que é de `eval/`. O que vale para as duas suítes está no `conftest.py` da raiz.

Este arquivo guardava uma cópia linha a linha do `pytest_sessionstart` de
`tests/conftest.py`, porque `pytest eval/` não carrega o conftest de `tests/`. A
premissa estava certa e a solução era a errada: um `conftest.py` na raiz é
carregado pelas duas invocações, e não precisa ser copiado para continuar valendo.

Hoje não há nada específico de `eval/`. O arquivo fica porque a próxima fixture
que for só daqui tem onde nascer — e porque apagar o arquivo tornaria invisível a
razão de ele já não ter o `pytest_sessionstart`.
"""

from __future__ import annotations
