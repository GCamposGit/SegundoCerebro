"""Put pip-vendored CUDA/cuDNN DLLs on this process PATH.

Does not change the machine PATH or the driver. Called from the smoke test
and from the embedder when the provider is cuda.
"""

from __future__ import annotations

import os
import site
from pathlib import Path

from ..logger import get_logger

log = get_logger("index.cuda_runtime")

_preparado = False


def pastas_nvidia() -> list[str]:
    saida: list[str] = []
    for raiz in site.getsitepackages():
        nvidia = Path(raiz) / "nvidia"
        if not nvidia.is_dir():
            continue
        for binario in nvidia.glob("*/bin"):
            if binario.is_dir():
                saida.append(str(binario))
    return saida


def preparar() -> None:
    """Idempotent. Safe to call on a machine with no GPU packages."""
    global _preparado
    if _preparado:
        return
    extras = pastas_nvidia()
    if extras:
        os.environ["PATH"] = os.pathsep.join(extras + [os.environ.get("PATH", "")])
        log.info("PATH deste processo += %d pastas nvidia/*/bin", len(extras))
    try:
        import onnxruntime as ort
    except ImportError:
        _preparado = True
        return
    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload()
        except Exception as erro:  # noqa: BLE001
            log.warning("preload_dlls() falhou: %s", erro)
    _preparado = True
