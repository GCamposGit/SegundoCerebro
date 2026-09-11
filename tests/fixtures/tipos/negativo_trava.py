"""Deliberate lock-contract break — must NOT live in src. Pyright must reject this."""

from __future__ import annotations

from pathlib import Path

from segundocerebro.index.trava import TravaDeIndice

TravaDeIndice("nao-e-path")


def devolve_int() -> int:
    return TravaDeIndice(Path("indice")).marca()
