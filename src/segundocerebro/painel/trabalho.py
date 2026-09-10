"""Um job caro por base, fora do event loop do painel (FND-05).

Exportar e medir bloqueavam GET /api/estado: rodam no loop e abrem Store.
O worker cria/fecha a conexão; o slot só solta quando o trabalho nativo acaba.
Cancelar o request não finge que a escrita parou.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

import anyio

T = TypeVar("T")


class Ocupado(Exception):
    """Já há export/medição nesta base. Não é cancelamento."""

    codigo = "ocupado"

    def __init__(self, base_id: str) -> None:
        super().__init__(
            f"a base '{base_id}' já tem uma operação em andamento. Espere terminar."
        )
        self.base_id = base_id


class TrabalhoCaro:
    """Limite de um job caro por id de base, neste processo do painel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ocupadas: set[str] = set()

    def ocupar(self, base_id: str) -> bool:
        with self._lock:
            if base_id in self._ocupadas:
                return False
            self._ocupadas.add(base_id)
            return True

    def soltar(self, base_id: str) -> None:
        with self._lock:
            self._ocupadas.discard(base_id)

    def ocupada(self, base_id: str) -> bool:
        with self._lock:
            return base_id in self._ocupadas


TRABALHO = TrabalhoCaro()


def _proteger(base_id: str, fn: Callable[[], T], iniciou: list[bool]) -> T:
    iniciou.append(True)
    try:
        return fn()
    finally:
        TRABALHO.soltar(base_id)


async def executar(base_id: str, fn: Callable[[], T]) -> T:
    """Roda `fn` numa thread. O slot só libera no finally do worker."""
    if not TRABALHO.ocupar(base_id):
        raise Ocupado(base_id)
    iniciou: list[bool] = []
    try:
        return await anyio.to_thread.run_sync(
            _proteger, base_id, fn, iniciou, abandon_on_cancel=False,
        )
    except BaseException:
        if not iniciou:
            TRABALHO.soltar(base_id)
        raise
