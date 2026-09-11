"""Valid use of the index lock — pyright must accept this file."""

from __future__ import annotations

from pathlib import Path

from segundocerebro.index.trava import TravaDeIndice

trava = TravaDeIndice(Path("indice"))
ocupada: bool = trava.ocupada()
marca: str = trava.marca()
assert ocupada is False or ocupada is True
assert isinstance(marca, str)
