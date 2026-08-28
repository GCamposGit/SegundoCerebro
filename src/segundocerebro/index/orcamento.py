"""Adaptive resource budget — a layperson's machine has to stay usable.

"It can take days" is only acceptable if the laptop remains a laptop. The
indexer used to take whatever was there; three days of a fan at 100% is how
the product gets uninstalled. This module derives workers, embed batch and
parse RAM from what the machine has *now*, and three presets a layperson can
pick: `automatico` / `noturno` / `discreto`.

Hardware never enters `model_id`. Nothing here changes index content
(`ARCHITECTURE.md` §4). The three canonical effort levels (`leve` / `normal` /
`maximo`) stay the internal vocabulary; the presets are aliases that a
layperson can type, plus `automatico` which starts as `normal` and yields to
sensors (active user, battery, free RAM).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..config import FRACAO_CPU, normalizar_perfil
from ..logger import get_logger

log = get_logger("index.orcamento")

PRESETS_LEIGO = ("automatico", "noturno", "discreto")
"""The only three names the product should offer a layperson."""

LIMIAR_RAM_LIVRE_MB = 512
"""Below this, shrink the embed batch. 512 MB is "the OS is already swapping"."""

JANELA_USUARIO_S = 30.0
"""Input within this window counts as "the user is at the keyboard"."""


@dataclass(frozen=True)
class Recursos:
    """What this machine has, right now. Tests pass a fake instead of probing."""

    nucleos: int
    ram_total_mb: int
    ram_livre_mb: int
    gpus: int = 0
    usuario_ativo: bool | None = None
    na_bateria: bool | None = None


@dataclass(frozen=True)
class Orcamento:
    """Numbers the indexer may use without asking the user to pick them."""

    preset: str
    perfil: str
    parse_workers: int
    lote_embed: int
    ram_parse_mb: int
    nucleos: int
    ram_livre_mb: int

    def como_json(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "perfil": self.perfil,
            "parse_workers": self.parse_workers,
            "lote_embed": self.lote_embed,
            "ram_parse_mb": self.ram_parse_mb,
            "nucleos": self.nucleos,
            "ram_livre_mb": self.ram_livre_mb,
        }


def preset_de(nome: str) -> str:
    """Layperson name if it is one, else the canonical effort level."""
    p = (nome or "normal").strip().lower()
    if p in PRESETS_LEIGO:
        return p
    return normalizar_perfil(p)


def perfil_de_preset(preset: str) -> str:
    """Map a layperson preset onto the effort levels `esforco.py` already applies.

    `automatico` starts as `normal` — sensors may drop it to `leve` later.
    `noturno` is everything. `discreto` is the minimum that still progresses.
    """
    p = preset_de(preset)
    if p == "noturno":
        return "maximo"
    if p == "discreto":
        return "leve"
    if p == "automatico":
        return "normal"
    return normalizar_perfil(p)


def medir(*, nucleos: int | None = None) -> Recursos:
    """Probe this process's view of the machine. Never raises."""
    n = nucleos if nucleos is not None else (os.cpu_count() or 4)
    total_mb, livre_mb = 0, 0
    try:
        import psutil

        mem = psutil.virtual_memory()
        total_mb = int(mem.total / (1024 * 1024))
        livre_mb = int(mem.available / (1024 * 1024))
    except Exception:  # noqa: BLE001 — psutil missing is not a reason not to index
        log.debug("psutil ausente ou recusou memória; orçamento usa semente")
    gpus = 0
    if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        try:
            from .gpu_pool import contar_gpus

            gpus = contar_gpus()
        except Exception:  # noqa: BLE001 — probe de GPU: ausente é zero, não aborta
            gpus = 0
    return Recursos(
        nucleos=max(1, int(n)),
        ram_total_mb=total_mb,
        ram_livre_mb=livre_mb,
        gpus=gpus,
        usuario_ativo=usuario_ativo(),
        na_bateria=_na_bateria(),
    )


def derivar(
    recursos: Recursos,
    preset: str = "automatico",
    *,
    lote_pedido: int | None = None,
) -> Orcamento:
    """Workers, batch and per-parse RAM from what is actually here.

    Formula, so a test can pin it without a real 8 GB box:

    - 8 GB total (or ≤2 GB free): 1 parse worker, embed batch 8, 256 MB per parse.
    - Otherwise: parse workers follow the effort fraction, batch stays at the
      caller's request (default 32), parse RAM is 1/8 of free RAM capped at 1 GB.
    """
    nome = preset_de(preset)
    perfil = perfil_de_preset(nome)
    if nome == "automatico":
        if recursos.usuario_ativo:
            perfil = "leve"
        elif recursos.na_bateria:
            perfil = "leve"
    n = max(1, int(recursos.nucleos))
    if perfil == "maximo":
        workers = n if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda" else 1
        workers = max(1, min(8, workers))
    elif os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        fracao = FRACAO_CPU.get(perfil, 0.5)
        workers = max(1, min(8, round(n * fracao)))
    else:
        workers = 1

    apertado = (recursos.ram_total_mb and recursos.ram_total_mb <= 8192) or (
        recursos.ram_livre_mb and recursos.ram_livre_mb <= 2048
    )
    if apertado:
        workers = 1
        lote = 8
        ram_parse = 256
    else:
        lote = lote_pedido if lote_pedido is not None else 32
        if recursos.ram_livre_mb and recursos.ram_livre_mb < LIMIAR_RAM_LIVRE_MB:
            lote = min(lote, 8)
        ram_parse = 1024
        if recursos.ram_livre_mb:
            ram_parse = max(256, min(1024, recursos.ram_livre_mb // 8 or 256))

    if lote_pedido is not None and not apertado:
        lote = min(lote, max(1, int(lote_pedido)))

    return Orcamento(
        preset=nome,
        perfil=perfil,
        parse_workers=max(1, int(workers)),
        lote_embed=max(1, int(lote)),
        ram_parse_mb=max(64, int(ram_parse)),
        nucleos=n,
        ram_livre_mb=recursos.ram_livre_mb,
    )


def teto_ram_pagina_ocr_mb(orcamento: Orcamento) -> int:
    """One OCR pixmap must fit in the parse budget. No new layperson preset.

    The page-by-page raster (F4-O.2) reads this instead of inventing a second
    ceiling. Tight machines already have `ram_parse_mb = 256`.
    """
    return max(64, int(orcamento.ram_parse_mb))


def ajustar_ao_vivo(orcamento: Orcamento, recursos: Recursos) -> Orcamento:
    """Re-derive from fresh sensors. `noturno` never yields; the others do.

    The acceptance "CPU drops >50% when the user is active" is this: automatico
    or discreto with `usuario_ativo` maps to `leve`, whose CPU fraction is 25%
    against normal's 50% — half the cores, below-normal priority, low I/O.
    """
    if orcamento.preset == "noturno":
        return orcamento
    return derivar(recursos, orcamento.preset, lote_pedido=orcamento.lote_embed)


def usuario_ativo(janela_s: float = JANELA_USUARIO_S) -> bool | None:
    """`True` if the user typed or moved the mouse recently. `None` if unknown."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        agora = ctypes.windll.kernel32.GetTickCount()
        ocioso_ms = int(agora - info.dwTime) & 0xFFFFFFFF
        return ocioso_ms < int(janela_s * 1000)
    except Exception:  # noqa: BLE001 — a sensor must not stop indexing
        return None


def _na_bateria() -> bool | None:
    try:
        from .esforco import na_bateria

        return na_bateria()
    except Exception:  # noqa: BLE001 — probe de bateria: sensor ausente não pára
        return None
