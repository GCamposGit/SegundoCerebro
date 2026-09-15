"""The one method every retriever implements, and the shape of what it returns.

This lived in `eval/harness.py` until 29/08/2026, and `retrieve/hybrid.py` reached
into it — `from eval.harness import Hit`, inside `BuscaHibrida.search`. That import
works from a clone and only from a clone: `pyproject.toml` packages `src/` alone, so
`eval` does not exist for anyone who ran `pip install segundocerebro`. The whole
historical series (F0 → F4 was measured on `search`) raised `ModuleNotFoundError` on
an installed package, and the panel's "Medir" button raised it too
(`painel/medir.py`).

The direction was backwards, not just the location. The harness is a *consumer* of
retrieval: it plugs the F0 baseline, the F1 hybrid and the F2 reranked pipeline into
the same table so the numbers stay comparable across phases. A consumer defines
nothing that the thing it consumes has to import. `eval.harness` re-exports both
names, so every call site there keeps working and the diff stays honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Hit:
    """One retrieved document. `path` is relative to the root, with '/'."""

    path: str
    score: float = 0.0
    trecho: str = ""
    anteriores: tuple[str, ...] = ()
    formatos: tuple[str, ...] = ()
    versoes: int = 1
    root_id: str = ""
    ocorrencia_id: str = ""


@dataclass(frozen=True)
class ChunkAcerto:
    chunk_id: str
    path: str
    score: float
    trilha: str
    locator: str
    texto: str
    origem: str
    """Which rankers found it: `denso`, `lexical` or `denso+lexical`."""
    antes: str = ""
    depois: str = ""
    """Vizinhos do mesmo documento, quando o cliente pede contexto.

    Ficam fora de texto de propósito. O chunk que casou com a consulta é o
    que tem procedência. Misturar o vizinho no mesmo campo faria o cliente
    citar como achado um texto que o ranqueador nunca pontuou.
    """
    anteriores: tuple[str, ...] = ()
    formatos: tuple[str, ...] = ()
    versoes: int = 1
    root_id: str = ""
    ocorrencia_id: str = ""


class Retriever(Protocol):
    nome: str

    def search(self, consulta: str, k: int) -> list[Hit]: ...
