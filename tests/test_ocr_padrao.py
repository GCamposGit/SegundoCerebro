"""OCR is part of indexing. A scan that stays empty without a try is a defect."""

from __future__ import annotations

import ast
from pathlib import Path

from segundocerebro.config import Indexacao
from segundocerebro.index.cli import construir_parser

RAIZ = Path(__file__).resolve().parent.parent / "src" / "segundocerebro"


def _imports_de_modulo(rel: str) -> list[str]:
    tree = ast.parse((RAIZ / rel).read_text(encoding="utf-8"))
    nomes: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            nomes.append(node.module or "")
        elif isinstance(node, ast.Import):
            nomes.extend(a.name for a in node.names)
    return nomes


def test_cli_nao_importa_embeddings_no_modulo() -> None:
    """Spawn reimports indexer → cli. embeddings.py imports fastembed at top."""
    assert not any("embeddings" in m for m in _imports_de_modulo("index/cli.py"))


def test_indexer_nao_importa_embeddings_no_modulo() -> None:
    assert not any("embeddings" in m for m in _imports_de_modulo("index/indexer.py"))


def test_fase_ocr_nao_passa_ram_mb() -> None:
    """1024 MB Job Object made RapidOCR recurso on a 1-page PDF (F4-O.3)."""
    fonte = (RAIZ / "index/indexer.py").read_text(encoding="utf-8")
    assert "ocr=True" in fonte
    assert "ram_mb=ram_parse_mb" not in fonte.split("if ocr and not progresso.interrompido:")[1]


def test_ocr_e_o_padrao() -> None:
    assert Indexacao().ocr is True
    ap = construir_parser()
    nomes = {a.dest for a in ap._actions}
    assert "sem_ocr" in nomes
