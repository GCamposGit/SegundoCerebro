"""Registry mapping extension to parser.

A parser takes bytes and a file name and returns a ParsedDoc. It never touches
the filesystem — `reader.py` is the single gatekeeper for that, so the cloud
placeholder check cannot be bypassed by a new format being added here.
"""

from __future__ import annotations

from collections.abc import Callable

from ..document import ParsedDoc

Parser = Callable[[bytes, str], ParsedDoc]

_REGISTRY: dict[str, Parser] = {}


def register(*extensions: str) -> Callable[[Parser], Parser]:
    def decorator(fn: Parser) -> Parser:
        for ext in extensions:
            _REGISTRY[ext.lower()] = fn
        return fn

    return decorator


def parser_for(extension: str) -> Parser | None:
    _load_all()
    return _REGISTRY.get(extension.lower())


def supported_extensions() -> tuple[str, ...]:
    _load_all()
    return tuple(sorted(_REGISTRY))


_LOADED = False


def _load_all() -> None:
    """Import the parser modules so their @register calls run."""
    global _LOADED
    if _LOADED:
        return
    from . import pdf, sheets, slides, text, word  # noqa: F401

    _LOADED = True
