"""Where the checkout is — and whether the package is running from inside one.

Four modules used to compute this with `Path(__file__).resolve().parent` four
times over (`mcp/server.py`, `mcp/registrar.py`, `index/retomada.py`,
`painel/medir.py`). The expression is right while the package runs from a clone
and silently wrong once it is installed: from `site-packages/segundocerebro/mcp/`
the same four hops land on the environment root, and every path built on top of
it points at a directory that has no `eval/`, no `config.toml` and no `src/`.

That failure mode is the golden rule's, not a detail: the product is for someone
who ran `pip install` on a machine we have never seen. So the assumption gets a
name and a test instead of being retyped. `raiz` answers *where would the clone
be*; `em_checkout` answers *is one actually there* — and a caller that needs the
repository has to ask the second question before trusting the first.
"""

from __future__ import annotations

from pathlib import Path

_MARCAS = ("pyproject.toml", "eval")
"""What proves a clone rather than an install: the build file plus the evaluation
tree. `src/` alone is not enough — an editable install leaves it importable from
anywhere, and `eval/` is the part that is never packaged."""


def raiz() -> Path:
    """The directory a clone would put this package in.

    Same value the four hand-written expressions produced, so nothing that
    already worked changes. Whether that directory *is* a clone is
    `em_checkout`'s question.
    """
    return Path(__file__).resolve().parent.parent.parent


def em_checkout() -> bool:
    """True when the package is running from the repository, not from an install."""
    base = raiz()
    return all((base / marca).exists() for marca in _MARCAS)
