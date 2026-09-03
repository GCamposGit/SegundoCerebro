"""F4-O.3: OCR the digitized queue without loading the encoder in the child.

The 28/08 block was spawn-from-indexer: the child reimported `indexer` and
`embeddings`, then OpenBLAS died. `ram_parse_mb=1024` on `indexer --ocr` still
kills RapidOCR as `recurso` here — measured 02/09/2026, one page, 0.26 MB.
This module is a light `__main__` so `parse_isolado` spawn stays light; the
encoder loads in the parent only after parse, to embed. Does not change
`indexer.py` (desktop).
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

from segundocerebro.config import carregar
from segundocerebro.ingest.chunking import CHUNKER_VERSION, chunk_document
from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.ocr import VERSAO as OCR_VERSAO
from segundocerebro.index.isolamento import parse_isolado
from segundocerebro.index.repesca import _parser_gravado, preservar_no_erro_de_ocr
from segundocerebro.index.store import Store
from segundocerebro.index.trava import TravaDeIndice
from segundocerebro.logger import get_logger

log = get_logger("eval.ocr_fila")

DIM_E5 = 1024


def _sem_encoder_no_modulo(fonte: str) -> None:
    """The 28/08 class: spawn reimports this file; module-level must stay light."""
    tree = ast.parse(fonte)
    for node in tree.body:
        nomes: list[str] = []
        if isinstance(node, ast.ImportFrom):
            nomes.append(node.module or "")
        elif isinstance(node, ast.Import):
            nomes.extend(alias.name for alias in node.names)
        for mod in nomes:
            if "embeddings" in mod or mod.endswith("indexer"):
                raise AssertionError(f"import de encoder/indexer no módulo: {mod}")


def _abs(root_path: Path, rel: str) -> str:
    return str(root_path / rel.replace("/", os.sep))


def rodar(config: Path, *, limite: int | None = None, gravar: bool = True) -> dict[str, int]:
    """OCR the `digitalizado` queue. Counts only — never document paths."""
    cfg = carregar(config)
    base = cfg.bases[0]
    indice = Path(base.indice)
    raizes = {r.name: Path(r.path) for r in base.raizes}
    store = Store(indice, DIM_E5)
    fila = store.documentos_para_ocr(OCR_VERSAO)
    if limite is not None:
        fila = fila[: max(0, int(limite))]
    contagem = {"fila": len(fila), "ok": 0, "chars": 0, "falha": 0, "preservado": 0}
    if not gravar:
        return contagem

    embedder = None
    trava = TravaDeIndice(indice)
    with trava:
        for rel, raiz_nome in fila:
            root = raizes.get(raiz_nome) or next(iter(raizes.values()))
            abs_path = _abs(root, rel)
            if not os.path.isfile(abs_path):
                contagem["falha"] += 1
                continue
            # No ram_mb: 1024 MB Job Object turned RapidOCR into recurso on a 1-page PDF.
            resultado = parse_isolado(abs_path, ocr=True, retries=1, espera=0.5)
            estado = store.estado_documento(rel)
            if not resultado.ok or resultado.doc is None:
                if estado is not None and estado.n_chunks > 0:
                    class _Prog:
                        quarentena = 0

                    if preservar_no_erro_de_ocr(store, _Prog(), rel, estado, resultado):
                        contagem["preservado"] += 1
                        continue
                contagem["falha"] += 1
                continue
            chunks = chunk_document(resultado.doc, rel)
            if not chunks:
                contagem["falha"] += 1
                continue
            if embedder is None:
                from segundocerebro.index.embeddings import Embedder

                embedder = Embedder("e5-large", lazy=False)
            vetores = embedder.embed_passagens(
                [c.embedding_text for c in chunks], batch_size=32, ritmo=1.0
            )
            st = os.stat(abs_path)
            store.remover_documento(rel)
            store.gravar_chunks(chunks, vetores, st.st_mtime, embedder.model_id)
            store.registrar_documento(
                path=rel,
                raiz=raiz_nome,
                tamanho=st.st_size,
                mtime=st.st_mtime,
                sha256=resultado.sha256,
                status=ParseStatus.OK.value,
                n_chunks=len(chunks),
                model_id=embedder.model_id,
                chunker=CHUNKER_VERSION,
                parser=_parser_gravado(resultado, rel),
                natureza=resultado.natureza,
            )
            store.commit()
            contagem["ok"] += 1
            contagem["chars"] += sum(len(c.text) for c in chunks)
    return contagem


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F4-O.3: OCR da fila digitalizado, main leve")
    ap.add_argument("--config", type=Path, default=Path("config.toml"))
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--so-contar", action="store_true")
    a = ap.parse_args(argv)
    _sem_encoder_no_modulo(Path(__file__).read_text(encoding="utf-8"))
    saida = rodar(a.config, limite=a.limite, gravar=not a.so_contar)
    print(saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
