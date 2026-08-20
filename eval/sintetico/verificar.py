"""Confere um índice sintético sem reembeddar.

    py -m eval.sintetico.verificar --indice index-sintetico-gpu

A prova da F3.6: o `model_id` gravado é o mesmo nas duas máquinas
(`e5-large:1024:fastembed0.8.0`), e o número de chunks bate. Não carrega o
encoder — hardware não entra na conferência.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from segundocerebro.index.embeddings import MODELOS
from segundocerebro.index.store import Store
from segundocerebro.logger import get_logger

log = get_logger("eval.sintetico")

MODELO = "e5-large"
ESPERADOS_DOCS = 11
ESPERADOS_CHUNKS = 18


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.sintetico.verificar")
    parser.add_argument("--indice", type=Path, default=Path("index-sintetico-gpu"))
    args = parser.parse_args(argv)

    if not args.indice.exists():
        log.error("índice ausente em %s — copiar o pacote da F3.6 para esta pasta", args.indice)
        return 2

    dim = MODELOS[MODELO].dim
    store = Store(args.indice, dim)
    try:
        estat = store.estatisticas()
        consist = store.verificar_consistencia()
    finally:
        store.fechar()

    log.info(
        "índice %s · %s documentos · %s chunks · modelos %s",
        args.indice,
        estat["documentos"],
        estat["chunks"],
        estat.get("modelos"),
    )
    if consist.get("diferenca"):
        log.error(
            "inconsistente: %s vetores para %s chunks",
            consist.get("vetores"),
            consist.get("chunks"),
        )
        return 3
    if estat["chunks"] != ESPERADOS_CHUNKS or estat["documentos"] != ESPERADOS_DOCS:
        log.error(
            "esperado %s docs / %s chunks (e5-large no sintético); achado %s / %s",
            ESPERADOS_DOCS,
            ESPERADOS_CHUNKS,
            estat["documentos"],
            estat["chunks"],
        )
        return 3
    log.info("ok: sem reembeddar. Próximo: eval.rodar --modelo e5-large --indice %s", args.indice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
