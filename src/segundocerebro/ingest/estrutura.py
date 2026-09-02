"""Versioned citation coordinates, shared by persistence and document readers."""

from __future__ import annotations

import re
from typing import Any

from .canonico import BlocoCanonico, ParseCanonico

VERSAO_ESTRUTURA = "blocos:1"


def validar(canonico: ParseCanonico) -> None:
    """Reject invalid spans instead of silently clipping Python slices.

    Gaps are legal: rendering inserts headings and separators outside blocks.
    Zero-length blocks are legal but cannot anchor a text quotation. Offsets
    count Unicode code points, never bytes, UTF-16 units or original-file bytes.
    """
    if (not isinstance(canonico.markdown, str)
            or not isinstance(canonico.blocos, tuple)
            or not isinstance(canonico.meta, dict)
            or not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in canonico.meta.items())):
        raise ValueError("estrutura canônica inválida")
    anterior = 0
    for bloco in canonico.blocos:
        if (not isinstance(bloco, BlocoCanonico)
                or type(bloco.inicio) is not int or type(bloco.fim) is not int
                or not anterior <= bloco.inicio <= bloco.fim <= len(canonico.markdown)
                or not isinstance(bloco.trilha, tuple)
                or not all(isinstance(t, str) for t in bloco.trilha)
                or not isinstance(bloco.kind, str) or not isinstance(bloco.locator, str)):
            raise ValueError("bloco canônico inválido")
        anterior = bloco.fim


def contrato() -> dict[str, str | int]:
    """Describe coordinates without asserting provenance the parser lacks."""
    return {"versao": VERSAO_ESTRUTURA, "referencial": "markdown_canonico",
            "unidade": "caracteres_unicode", "base": 0, "intervalo": "[inicio,fim)",
            "ordinal_base": 0, "pagina_base": 1, "slide_base": 1}


def citar(bloco: BlocoCanonico, ordinal: int) -> dict[str, Any]:
    """Keep original locators separate from spans in rendered Markdown.

    Only exact parser conventions become numeric pages/slides. A heading named
    'Page 3', a Word table, a sheet range or a timestamp is not a physical page.
    Ordinals are document-global and only stable within the response version.
    """
    pagina = re.fullmatch(r"p\. ([1-9][0-9]{0,8})", bloco.locator)
    slide = re.fullmatch(r"slide ([1-9][0-9]{0,8})(?: \(notas\))?", bloco.locator)
    return {"ordinal": ordinal, "inicio": bloco.inicio, "fim": bloco.fim,
            "onde": bloco.locator, "tipo": bloco.kind, "trilha": list(bloco.trilha),
            "pagina": int(pagina[1]) if pagina else None,
            "slide": int(slide[1]) if slide else None}
