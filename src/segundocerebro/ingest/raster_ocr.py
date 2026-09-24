"""OCR of embedded PNG/JPEG. Runs only when a CUDA kernel actually works.

CPU OCR of every picture in a deck was measured at hours. The same sample on
a working GPU was about ten times faster, so the product reads those rasters
only in that case. EMF, WMF, WDP and SVG stay declared, not silently empty.
A failure on one picture does not drop text the structured parser already
emitted.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ..logger import get_logger
from .document import Block

log = get_logger("ingest.raster_ocr")

RASTERS = frozenset({".png", ".jpg", ".jpeg"})
NAO_LIDOS = frozenset({".emf", ".wmf", ".emz", ".wdp", ".svg"})
PISO_LADO = 100
TETO_PIXELS = 2_000_000
TETO_BYTES = 1_500_000


def _normalizar(texto: str) -> str:
    return " ".join(texto.split()).casefold()


def _partes(dados: bytes) -> tuple[list[str], list[str]]:
    """Raster members inside the measured band, and suffixes we do not read."""
    rasters: list[str] = []
    ignorados: list[str] = []
    try:
        pacote = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        return [], []
    with pacote:
        for info in pacote.infolist():
            nome = info.filename.replace("\\", "/")
            if "/media/" not in nome.lower():
                continue
            sufixo = Path(nome).suffix.lower()
            if sufixo in NAO_LIDOS:
                ignorados.append(sufixo.lstrip("."))
            elif sufixo in RASTERS and info.file_size <= TETO_BYTES:
                rasters.append(nome)
    return rasters, ignorados


def _imagem(pacote: zipfile.ZipFile, nome: str) -> object | None:
    from PIL import Image

    try:
        bruto = pacote.read(nome)
    except OSError:
        return None
    try:
        with Image.open(io.BytesIO(bruto)) as img:
            largura, altura = img.size
            if min(largura, altura) < PISO_LADO or largura * altura > TETO_PIXELS:
                return None
            return img.convert("RGB").copy()
    except OSError:
        return None


def _motor() -> object | None:
    from .ocr import gpu_para_ocr, motor_imagem

    if motor_imagem is not None:
        return motor_imagem
    if not gpu_para_ocr():
        return None
    from .ocr import _texto_rapidocr

    return _texto_rapidocr


def acrescentar_rasters(dados: bytes, blocos: list[Block]) -> dict[str, str]:
    """Append picture text. Returns meta; never removes blocks already present."""
    if not dados.startswith(b"PK"):
        return {}
    nomes, ignorados = _partes(dados)
    meta: dict[str, str] = {}
    if ignorados:
        meta["imagem_nao_lida"] = ",".join(sorted(set(ignorados)))
    if not nomes:
        return meta
    motor = _motor()
    if motor is None:
        meta["ocr_raster"] = "sem_gpu"
        return meta
    coberto = _normalizar("\n".join(b.text for b in blocos))
    try:
        pacote = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        return meta
    leu = False
    with pacote:
        for nome in nomes:
            imagem = _imagem(pacote, nome)
            if imagem is None:
                continue
            leu = True
            texto = _ler(motor, imagem)
            chave = _normalizar(texto)
            if not chave or chave in coberto:
                continue
            blocos.append(Block(heading_path=(), text=texto, locator="imagem"))
            coberto += " " + chave
    if leu:
        meta["ocr_raster"] = "gpu"
    return meta


def _ler(motor, imagem) -> str:  # noqa: ANN001 — hook de teste ou RapidOCR
    import numpy as np

    try:
        arr = np.array(imagem)
        return (motor(arr) or "").strip()
    except Exception as erro:  # noqa: BLE001 — falha de OCR numa imagem não apaga o texto do slide
        log.warning("OCR de imagem embutida falhou: %s", erro)
        return ""
