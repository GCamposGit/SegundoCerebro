"""Identify allocation failures without importing optional native runtimes.

Q15.b, 2026-09-02: RapidOCR wraps ORT exceptions using ``raise ... from e``.
The type and allocation signal in that cause matter, not the wrapper traceback.
See docs/q15b-ocr-recursos.md for the pinned upstream sources.
"""

from __future__ import annotations

import re

_ORT_MODULE = "onnxruntime.capi.onnxruntime_pybind11_state"
_ORT_ALLOCATION = re.compile(
    r"\bbad allocation\s*$|\bstd::bad_alloc\b|"
    r"\bfailed to allocate memory for requested buffer\b|"
    r"\bavailable memory of \d+ is smaller than requested bytes of \d+\b|"
    r"\bout of memory\b",
    re.IGNORECASE,
)


def _memoria_nativa(erro: BaseException) -> bool:
    tipos = {(tipo.__module__, tipo.__name__) for tipo in type(erro).__mro__}
    if ("cv2", "error") in tipos:
        return getattr(erro, "code", None) == -4  # OpenCV StsNoMem
    if tipos & {(_ORT_MODULE, "RuntimeException"), (_ORT_MODULE, "Fail")}:
        return bool(_ORT_ALLOCATION.search(str(erro)))
    return False


def falha_de_memoria(erro: BaseException) -> bool:
    """Follow explicit causes (or unsuppressed contexts), with cycle protection.

    A generic RuntimeError containing 'bad allocation' is not sufficient.
    NumPy allocation errors already inherit MemoryError; native ORT and OpenCV
    need their own structured signals. Unknown native errors remain unknown.
    """
    vistos: set[int] = set()
    atual: BaseException | None = erro
    while atual is not None and id(atual) not in vistos:
        vistos.add(id(atual))
        if isinstance(atual, MemoryError) or _memoria_nativa(atual):
            return True
        if atual.__cause__ is not None:
            atual = atual.__cause__
        else:
            atual = None if atual.__suppress_context__ else atual.__context__
    return False
