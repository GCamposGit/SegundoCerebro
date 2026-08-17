"""Logging setup shared by every module.

Handlers write to stderr on purpose: stdout is reserved for machine-readable
output (census report, and later the MCP stdio transport, where a stray print
would corrupt the protocol stream).
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False
_DEFAULT_LEVEL = "INFO"
_ENV_LEVEL = "SEGUNDOCEREBRO_LOG_LEVEL"


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get(_ENV_LEVEL, _DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    root = logging.getLogger("segundocerebro")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return the logger for a module. Never use print()."""
    _configure()
    return logging.getLogger(f"segundocerebro.{name}")
