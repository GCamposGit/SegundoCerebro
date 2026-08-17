"""Deliberately dumb baseline: search the file name and folder path.

This is the number every later phase has to beat. It is not a straw man — in a
corporate corpus the file name carries the contract code, the supplier and the
version, so path matching is a genuinely competitive starting point. Measured:
recall@1 = 0,549, against 0,431 for BM25 over chunk text.

It reads no file content, which is exactly why it fails on the trap questions in
the golden set (a supplier that appears only inside the document, an acronym
misspelled in the file name).

The scoring itself lives in `segundocerebro.retrieve.nomes`, shared with the
ranker that feeds the hybrid fusion. Two copies would mean comparing two scorers
instead of measuring the value of the signal.
"""

from __future__ import annotations

from collections.abc import Iterable

from segundocerebro.census import Config, RootSpec, iter_files
from segundocerebro.retrieve.nomes import (  # noqa: F401 — reexportado por compatibilidade
    DocumentoIndexado,
    PALAVRAS_VAZIAS,
    indexar_caminhos,
    normalizar,
    pontuar,
    tokenizar,
)

from .harness import Hit


class BuscaPorNomeDeArquivo:
    """Token overlap against the file name (weight 2) and folders (weight 1)."""

    nome = "baseline: nome de arquivo"

    def __init__(self, documentos: Iterable[DocumentoIndexado]) -> None:
        self.documentos = list(documentos)

    @classmethod
    def a_partir_de(
        cls, roots: list[RootSpec], cfg: Config, prefixo: str | None = None
    ) -> "BuscaPorNomeDeArquivo":
        """`prefixo` restringe a subárvore, do mesmo jeito que no indexador.

        Existe para que o baseline e a busca sobre o índice ranqueiem o **mesmo
        universo** de documentos. Sem ele, comparar os dois compara duas coisas
        ao mesmo tempo — a qualidade do ranqueador e o tamanho do acervo — e a
        escala sozinha move recall@1 em 16% (`docs/escala-f0.md`).

        Filtra, não re-enraíza: o caminho gravado continua relativo à raiz do
        `census.toml`, que é como o conjunto dourado referencia as fontes.
        """
        caminhos = [
            f.rel
            for root in roots
            for f in iter_files(root, cfg)
            if not prefixo or f.rel.startswith(prefixo)
        ]
        return cls(indexar_caminhos(caminhos))

    @property
    def universo(self) -> set[str]:
        return {d.rel for d in self.documentos}

    def search(self, consulta: str, k: int) -> list[Hit]:
        return [Hit(path=rel, score=score) for rel, score in pontuar(self.documentos, consulta)[:k]]
