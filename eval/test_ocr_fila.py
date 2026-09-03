"""F4-O.3 instrument: the child that OCRs must not load the encoder."""

from __future__ import annotations

from pathlib import Path

from eval.ocr_fila import _sem_encoder_no_modulo


def test_modulo_nao_importa_encoder_nem_indexer() -> None:
    fonte = Path("eval/ocr_fila.py").read_text(encoding="utf-8")
    _sem_encoder_no_modulo(fonte)


def test_parse_isolado_nao_passa_ram_mb() -> None:
    """1024 MB Job Object made RapidOCR recurso on a 1-page PDF (02/09/2026)."""
    fonte = Path("eval/ocr_fila.py").read_text(encoding="utf-8")
    assert "parse_isolado(abs_path, ocr=True, retries=1, espera=0.5)" in fonte
    assert "parse_isolado(" in fonte
    assert "ram_mb=" not in fonte


