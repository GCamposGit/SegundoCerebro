"""OCR of scanned PDFs — a second pass, never inline with the cheap parse.

The PDF parser already marks `digitalizado` and returns no blocks. That is
the first-day path: text files stay searchable while scans wait. This module
turns those scans into pages of text. RapidOCR ships with the default install.

Backends, in order:
1. RapidOCR (ONNX) — a main dependency, not an extra.
2. Tesseract, if `tesseract` is on PATH and `pytesseract` imports.
3. Nothing — `None`, and the indexer treats that as an error, not a no-op.

Parsers still receive bytes. Rendering is pymupdf, which already opens PDFs.
The indexer owns *when* this runs (after the four text waves).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from ..logger import get_logger
from .document import Block, BlockKind, FalhaDeAmbiente, ParsedDoc, ausencia_declarada
from .ocr_recursos import falha_de_memoria

log = get_logger("ingest.ocr")

VERSAO = "ocr:1"
"""Own parser_version so an OCR engine change re-parses scans, not text PDFs."""

# Test hook: (numpy image) -> text. Survives missing RapidOCR in the standard suite.
motor_imagem: Callable | None = None


@dataclass(frozen=True)
class PaginaTexto:
    numero: int
    texto: str


def _probe(modulo: str) -> bool:
    """O extra está instalado? Ausência é `False`; falha de ambiente **levanta**.

    `Q15`, 30/08/2026. Antes era `except Exception: pass`, e isso lia pressão de
    memória como "o extra não está aqui" — o recurso se desligava sozinho, em
    silêncio, exatamente quando a máquina estava apertada.
    """
    try:
        __import__(modulo)
    except Exception as exc:  # BLE001 — probe: qualquer falha que não seja ausência
        if ausencia_declarada(exc, modulo):
            return False
        raise FalhaDeAmbiente(f"{modulo} está instalado e não carregou: {exc}") from exc
    return True


def backend_disponivel() -> str | None:
    """Which engine would run. `None` = OCR is a no-op this install."""
    if motor_imagem is not None or _fake_de_teste() is not None:
        return "teste"
    if _probe("rapidocr_onnxruntime"):
        return "rapidocr"
    import shutil

    if shutil.which("tesseract"):
        return "tesseract" if _probe("pytesseract") else None
    return None


def motor_de_ocr() -> str | None:
    """`backend_disponivel()` que não derruba quem o chama — `Q15`, 30/08/2026.

    O probe passou a **levantar** quando o extra está instalado e não carrega,
    que é o conserto do `Q15`. Só que o indexador o chama depois das quatro
    ondas de texto: sem envelope, a passada inteira morreria com traceback
    tendo já feito o trabalho caro — pior que o defeito consertado. Quem
    precisa do veredito cru usa `backend_disponivel`; quem está no meio de uma
    passada usa este.
    """
    try:
        return backend_disponivel()
    except FalhaDeAmbiente as erro:
        log.error("OCR indisponível nesta passada: %s", erro)
        return None


DPI_OCR = 144
"""Production raster: 72 × 2. F4-O.2b: a 10 pt identifier is read at 72 dpi
too, so 200 dpi is not the lever — keep the current matrix."""


def _teto_ocr_mb() -> int:
    from ..index.orcamento import derivar, medir, teto_ram_pagina_ocr_mb

    return teto_ram_pagina_ocr_mb(derivar(medir()))


def _dpi_cabivel(pagina, teto_mb: int, dpi_alvo: float = DPI_OCR) -> float:  # noqa: ANN001
    """Drop dpi so one pixmap fits in the parse budget. Never below 72."""
    rect = pagina.rect
    bytes_a_1dpi = max(1.0, (float(rect.width) / 72.0) * (float(rect.height) / 72.0) * 3.0)
    teto = max(1, int(teto_mb)) * 1024 * 1024
    max_dpi = (teto / bytes_a_1dpi) ** 0.5
    return max(72.0, min(float(dpi_alvo), max_dpi))


def _iter_rasters(dados: bytes, *, teto_mb: int | None = None):  # noqa: ANN202 — retorno concreto vive no corpo, não na assinatura
    """Yield `(page_number, rgb_array)` for pages that need OCR, one at a time.

    The list form copied every pixmap; an 80-page scan at 200 dpi is ~1 GB.
    """
    import numpy as np
    import pymupdf

    from .parsers.pdf import pagina_precisa_ocr

    teto = teto_mb if teto_mb is not None else _teto_ocr_mb()
    documento = pymupdf.open(stream=dados, filetype="pdf")
    try:
        for i, pagina in enumerate(documento, start=1):
            texto = pagina.get_text() or ""
            if not pagina_precisa_ocr(pagina, texto):
                continue
            dpi = _dpi_cabivel(pagina, teto)
            pix = pagina.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n).copy()
            pix = None
            yield i, arr
    finally:
        documento.close()


def _imagens_das_paginas(dados: bytes):  # noqa: ANN202 — retorno concreto vive no corpo, não na assinatura
    """Materialise rasters. One-page tests still use this; production iterates."""
    return [arr for _, arr in _iter_rasters(dados)]


_rapid: object | None = None


def _texto_rapidocr(imagem) -> str:  # noqa: ANN001
    global _rapid
    from rapidocr_onnxruntime import RapidOCR

    if _rapid is None:
        _rapid = RapidOCR()
    # rapidocr-onnxruntime 1.3–1.4: (linhas, elapsed).
    # linhas = [[box, text, confidence], ...] | None. Pinned by
    # tests/test_ocr_motor.py (marker `ocr`). A v2 of the extra is out of the
    # pin (`<2` in pyproject); a silent shape change breaks that test, not
    # a 10 GB corpus.
    saida = _rapid(imagem)
    linhas = saida[0] if isinstance(saida, tuple) else saida
    if not linhas:
        return ""
    partes: list[str] = []
    for item in linhas:
        if isinstance(item, dict) and item.get("text"):
            partes.append(str(item["text"]))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            partes.append(str(item[1]))
    return "\n".join(p for p in partes if p.strip())


def _texto_tesseract(imagem) -> str:  # noqa: ANN001
    import pytesseract
    from PIL import Image

    pil = Image.fromarray(imagem)
    return (pytesseract.image_to_string(pil, lang="por+eng") or "").strip()


VARIAVEL_FAKE = "SEGUNDOCEREBRO_OCR_FAKE"


def _fake_de_teste() -> str | None:
    """O texto fixo do dublê, e **só sob pytest** — `Q14`, 30/08/2026.

    A variável desviava o motor de OCR sem nenhuma guarda: herdada de uma sessão
    de shell, ela mudava o comportamento do produto sem uma linha no log dizendo
    que o motor era falso. Um acervo inteiro sairia indexado com a mesma frase.

    Duas defesas, porque uma delas some quando alguém roda o produto de dentro de
    um teste: só vale sob `PYTEST_CURRENT_TEST`, **e** avisa em toda passada com
    o texto que está injetando. Fora de teste a variável é ignorada, e o aviso
    diz isso — silêncio aqui seria a mesma classe do `Q15` noutra roupa.
    """
    fake = os.environ.get(VARIAVEL_FAKE)
    if fake is None:
        return None
    if "PYTEST_CURRENT_TEST" not in os.environ:
        log.warning(
            "%s está definida fora de um teste e foi IGNORADA — o motor de OCR real "
            "é que vai rodar. Remova a variável do ambiente para não ver este aviso.",
            VARIAVEL_FAKE,
        )
        return None
    log.warning("motor de OCR FALSO ativo por %s: injetando %r", VARIAVEL_FAKE, fake.strip())
    return fake.strip()


def _texto_de(imagem) -> str:  # noqa: ANN001
    fake = _fake_de_teste()
    if fake is not None:
        return fake
    if motor_imagem is not None:
        return (motor_imagem(imagem) or "").strip()
    backend = backend_disponivel()
    if backend == "rapidocr":
        return _texto_rapidocr(imagem)
    if backend == "tesseract":
        return _texto_tesseract(imagem)
    return ""


def _conferir_falhas_de_pagina(
    total: int, falharam: int, por_memoria: int, *, produziu_texto: bool
) -> None:
    """Todas as páginas sem memória é a janela; qualquer outra falha é a página.

    Quem separa é o **tipo**, não o escopo. A primeira versão levantava sempre
    que todas as páginas falhavam, e uma revisão mostrou que em N=1 isso confunde
    "a janela apertou" com "esta única página é um scan corrompido" — e PDF
    escaneado de uma página é comum. Com o tipo a ambiguidade some: página
    corrompida levanta `ValueError` e vira página vazia, como sempre foi;
    `MemoryError` é sintoma de recurso, e aí "tente com mais memória" é o
    conselho certo mesmo com uma página só.

    O escopo continua entrando, mas como **confiança**: uma página gorda no meio
    de um scan que rodou não derruba o arquivo (30/08/2026).
    """
    if falharam:
        log.warning("OCR falhou em %d de %d páginas deste PDF", falharam, total)
    # Q15.b: blank/broken companion pages do not make allocation failure benign.
    # Keep the existing partial-text policy; no text + any OOM must remain retryable.
    if por_memoria and not produziu_texto:
        raise FalhaDeAmbiente(f"OCR ficou sem memória em {por_memoria} páginas deste PDF")


def ocr_pdf(dados: bytes, *, teto_mb: int | None = None) -> list[PaginaTexto] | None:
    """OCR pages that need it. `None` if no backend; empty if the engine saw nothing.

    Native pages are skipped (same detector as the PDF parser). One pixmap
    at a time, sized to the parse RAM ceiling.
    """
    if backend_disponivel() is None:
        return None
    paginas: list[PaginaTexto] = []
    falharam = por_memoria = 0
    try:
        for i, imagem in _iter_rasters(dados, teto_mb=teto_mb):
            try:
                texto = _texto_de(imagem)
            except (FalhaDeAmbiente, ImportError):
                # Dependência que não carrega é da máquina, e vale para o arquivo
                # inteiro. `MemoryError` **não** entra aqui: uma página A0 a 72 dpi
                # pede 593 MB por si só, e isso é o documento, não a janela — era
                # exatamente o que o `noqa` abaixo existe para tratar (30/08/2026).
                raise
            except MemoryError as exc:
                # Falha de memória numa página é sintoma de recurso — e para uma
                # página A0, que pede 593 MB a 72 dpi, "tente com mais memória"
                # é o conselho **certo**. Contada à parte, ver abaixo.
                log.warning("OCR sem memória na página %d: %s", i, exc)
                texto = ""
                falharam += 1
                por_memoria += 1
            except Exception as exc:  # noqa: BLE001 — laço de onda: página de scan hostil não mata o OCR do arquivo
                log.warning("OCR falhou na página %d: %s", i, exc)
                texto = ""
                falharam += 1
                por_memoria += int(falha_de_memoria(exc))
            del imagem
            paginas.append(PaginaTexto(numero=i, texto=texto))
    except FalhaDeAmbiente:
        raise
    except (ImportError, MemoryError) as exc:
        # O `except Exception` abaixo engolia estes dois e devolvia `None`, que é
        # o mesmo valor de "esta instalação não tem OCR". Sob pressão de memória
        # `import pymupdf` levanta `ModuleNotFoundError: No module named 'mupdf'`,
        # e o documento terminava `vazio` sem linha de quarentena (`Q15`).
        raise FalhaDeAmbiente(f"OCR não pôde carregar suas dependências: {exc}") from exc
    except Exception as exc:  # BLE001 — a bad scan must not kill the wave
        if falha_de_memoria(exc):
            raise FalhaDeAmbiente(f"OCR ficou sem memória ao rasterizar: {exc}") from exc
        log.warning("OCR não rasterizou o PDF: %s", exc)
        return None
    _conferir_falhas_de_pagina(
        len(paginas), falharam, por_memoria,
        produziu_texto=any(p.texto.strip() for p in paginas),
    )
    return paginas


def _numero_do_locator(locator: str) -> int:
    partes = (locator or "").split()
    try:
        return int(partes[-1])
    except (ValueError, IndexError):
        return 0


def doc_de_ocr(
    dados: bytes, nome: str, nativo: ParsedDoc | None = None
) -> ParsedDoc | None:
    """ParsedDoc: native blocks kept, OCR blocks only for photo pages.

    `None` if OCR is off or produced nothing — the caller then keeps the
    cheap parse, which is what mixed PDFs need.
    """
    paginas = ocr_pdf(dados)
    if paginas is None:
        return None
    blocos_ocr = [
        Block(
            heading_path=(),
            text=p.texto,
            locator=f"p. {p.numero}",
            kind=BlockKind.TEXT,
        )
        for p in paginas
        if p.texto.strip()
    ]
    if not blocos_ocr:
        return None
    ocr_paginas = {p.numero for p in paginas}
    nativos = [
        b
        for b in (nativo.blocks if nativo is not None else ())
        if _numero_do_locator(b.locator) not in ocr_paginas
    ]
    blocos = sorted(
        (*nativos, *blocos_ocr),
        key=lambda b: _numero_do_locator(b.locator),
    )
    backend = backend_disponivel() or "ocr"
    n_paginas = (nativo.meta.get("paginas") if nativo is not None else None) or str(
        max((p.numero for p in paginas), default=len(paginas))
    )
    meta = {
        "formato": "pdf",
        "fonte": "ocr",
        "backend": backend,
        "parser": VERSAO,
        "paginas": str(n_paginas),
        "suspeita": "digitalizado",
    }
    if nativo is not None:
        for chave in ("motor", "paginas_ocr", "sumario_nativo"):
            if nativo.meta.get(chave):
                meta[chave] = nativo.meta[chave]
    return ParsedDoc(name=nome, blocks=tuple(blocos), meta=meta)
