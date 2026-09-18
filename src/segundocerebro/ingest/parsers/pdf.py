"""PDF — 1509 files, 47,8% of the corpus and 10 GB of it.

PyMuPDF converts each page to Markdown, detecting headings from font size and
weight, so the structural work is delegated to the Markdown parser. The heading
trail is threaded across pages: a section opened on page 3 still labels the text
that continues on page 4.

Scanned PDFs are the known trap. A page image yields almost no characters, and
indexing it produces a document that exists in the index but answers nothing.
The mark is **per page**: a native cover plus a photographed body used to look
fine on file-level averages and the photo pages stayed invisible. Scan pages
are marked `digitalizado` and left without blocks; native pages still emit
text. The ingestion report then shows a decision to make (OCR or not)
instead of silent noise.
"""

from __future__ import annotations

from ..document import Block, ParsedDoc
from ..document import BlockKind
from . import register
from .text import blocos_de_markdown

# Dois sinais, porque um só erra nos dois sentidos. Texto quase ausente é scan
# com quase certeza. Texto pouco *e* página coberta por imagem também. Mas um
# PDF curto e legítimo — recibo, fatura, passagem, ofício de um parágrafo — tem
# pouco texto e nenhuma imagem, e precisa ser indexado normalmente: o acervo
# tem dezenas deles.
MIN_CHARS_POR_PAGINA = 15
MIN_CHARS_COM_IMAGEM = 100


def pagina_precisa_ocr(pagina, texto: str) -> bool:  # noqa: ANN001
    """Scan detector at **page** grain, not file average.

    A native cover plus a photographed body has a high mean char count, so the
    file-level test never marked `digitalizado` and the photo pages stayed
    invisible. Blank pages without an image are not scans.
    """
    chars = len((texto or "").strip())
    try:
        tem_imagem = bool(pagina.get_images())
    except Exception:  # noqa: BLE001 — a broken image dict is not a scan
        tem_imagem = False
    if chars < MIN_CHARS_POR_PAGINA:
        return tem_imagem
    return tem_imagem and chars < MIN_CHARS_COM_IMAGEM


MOTOR_PADRAO = "fonte"

# Uma linha de título é curta. Passando disso é parágrafo em fonte grande.
MAX_CHARS_TITULO = 120
# Fonte precisa ser visivelmente maior que o corpo para valer como título.
RAZAO_TITULO = 1.12
MAX_NIVEIS = 4


def _tem_sumario_nativo(documento) -> bool:  # noqa: ANN001
    """O PDF traz outline embutido?

    Quando traz, é estrutura declarada pelo autor — hierarquia de seção com
    título e página, sem adivinhação. O motor `fonte` reconstrói heading por
    tamanho de letra, que é heurística e erra em documento com capa, marca d'água
    ou tabela em fonte grande.

    Só **registrado** por enquanto. Trocar o motor de headings muda a trilha
    contextual de todo chunk, e portanto muda o texto embeddado e a fronteira de
    chunk: é mudança que passa pelo eval antes de entrar, como qualquer outra.
    """
    try:
        return bool(documento.get_toc(simple=True))
    except Exception:  # noqa: BLE001 — outline malformado não pode derrubar a ingestão
        return False


def _paginas_por_tamanho_de_fonte(documento) -> list[tuple[int, str]]:  # noqa: ANN001
    """Markdown reconstructed from font sizes — the fast engine.

    `pymupdf4llm` does full layout analysis and costs ~2s per page; measured
    against raw extraction it is 78–103× slower for 3–15% more characters, most
    of which is the Markdown markup itself. On 1509 PDFs that is 8 hours per
    pass versus 6 minutes, which decides it: a full pass has to be cheap enough
    to repeat, or no chunking experiment can ever be run twice.

    What is kept is the part that matters for precision: the heading trail. The
    body font size is whichever size covers the most characters; anything
    meaningfully larger, on a short line, becomes a heading, ranked by size.
    """
    from collections import Counter

    paginas_spans: list[tuple[int, list[list[tuple[float, str]]]]] = []
    chars_por_tamanho: Counter[float] = Counter()

    for numero, pagina in enumerate(documento, start=1):
        linhas: list[list[tuple[float, str]]] = []
        try:
            dados = pagina.get_text("dict")
        except Exception:  # noqa: BLE001 — borda de parse: dict de página malformado não derruba o PDF
            continue
        for bloco in dados.get("blocks", []):
            for linha in bloco.get("lines", []):
                spans: list[tuple[float, str]] = []
                for span in linha.get("spans", []):
                    texto = (span.get("text") or "").strip()
                    if not texto:
                        continue
                    tamanho = round(float(span.get("size", 0.0)), 1)
                    spans.append((tamanho, texto))
                    chars_por_tamanho[tamanho] += len(texto)
                if spans:
                    linhas.append(spans)
        paginas_spans.append((numero, linhas))

    if not chars_por_tamanho:
        return [(n, pagina.get_text() or "") for n, pagina in enumerate(documento, start=1)]

    corpo = chars_por_tamanho.most_common(1)[0][0]
    maiores = sorted({t for t in chars_por_tamanho if t >= corpo * RAZAO_TITULO}, reverse=True)[:MAX_NIVEIS]
    nivel_de_tamanho = {tamanho: i for i, tamanho in enumerate(maiores, start=1)}

    paginas: list[tuple[int, str]] = []
    for numero, linhas in paginas_spans:
        saida: list[str] = []
        for spans in linhas:
            texto = " ".join(t for _, t in spans).strip()
            if not texto:
                continue
            maior = max(tamanho for tamanho, _ in spans)
            nivel = nivel_de_tamanho.get(maior)
            if nivel and len(texto) <= MAX_CHARS_TITULO:
                saida.append("#" * nivel + " " + texto)
            else:
                saida.append(texto)
        paginas.append((numero, "\n".join(saida)))
    return paginas


def _paginas_em_markdown(documento) -> list[tuple[int, str]]:  # noqa: ANN001
    """Full layout analysis. Slow; kept so F2 can ablate it against `fonte`."""
    import pymupdf4llm

    try:
        pedacos = pymupdf4llm.to_markdown(documento, page_chunks=True, show_progress=False)
    except Exception:  # noqa: BLE001 — layout exótico não pode derrubar a ingestão
        return [(n + 1, pagina.get_text() or "") for n, pagina in enumerate(documento)]

    paginas: list[tuple[int, str]] = []
    for indice, pedaco in enumerate(pedacos, start=1):
        if isinstance(pedaco, dict):
            numero = int(pedaco.get("metadata", {}).get("page", indice) or indice)
            paginas.append((numero, pedaco.get("text", "") or ""))
        else:
            paginas.append((indice, str(pedaco)))
    return paginas


MOTORES = {"fonte": _paginas_por_tamanho_de_fonte, "layout": _paginas_em_markdown}


def _extras_da_pagina(pagina) -> list[str]:  # noqa: ANN001
    """Form fields and annotation bodies — get_text() often skips both."""
    extras: list[str] = []
    try:
        for campo in pagina.widgets() or []:
            valor = getattr(campo, "field_value", None)
            if valor:
                extras.append(str(valor).strip())
    except Exception:  # noqa: BLE001 — widget quebrado não derruba a página
        pass
    try:
        for anot in pagina.annots() or []:
            info = getattr(anot, "info", None) or {}
            for chave in ("content", "subject", "title"):
                valor = info.get(chave) if isinstance(info, dict) else None
                if valor:
                    extras.append(str(valor).strip())
    except Exception:  # noqa: BLE001 — anotação quebrada não derruba a página
        pass
    return [t for t in extras if t]


@register(".pdf", version="2")
def parse_pdf(dados: bytes, nome: str, motor: str = MOTOR_PADRAO) -> ParsedDoc:
    import pymupdf

    extrair = MOTORES.get(motor, _paginas_por_tamanho_de_fonte)
    documento = pymupdf.open(stream=dados, filetype="pdf")
    try:
        n_paginas = documento.page_count
        paginas_com_imagem = sum(1 for pagina in documento if pagina.get_images())
        sumario_nativo = _tem_sumario_nativo(documento)
        paginas = extrair(documento)
        texto_de = {n: t for n, t in paginas}
        paginas_ocr = [
            i
            for i, pagina in enumerate(documento, start=1)
            if pagina_precisa_ocr(pagina, texto_de.get(i, ""))
        ]
        extras = _extras_do_documento(documento)
    finally:
        documento.close()

    total_chars = sum(len(t.strip()) for _, t in paginas)
    media_chars = total_chars / n_paginas if n_paginas else 0.0
    meta = {
        "formato": "pdf",
        "paginas": str(n_paginas),
        "motor": motor,
        "paginas_com_imagem": str(paginas_com_imagem),
        "sumario_nativo": "1" if sumario_nativo else "0",
    }

    ocr_set = set(paginas_ocr)
    if paginas_ocr:
        meta["suspeita"] = "digitalizado"
        meta["chars_por_pagina"] = f"{media_chars:.0f}"
        meta["paginas_ocr"] = ",".join(str(n) for n in paginas_ocr)
        if len(paginas_ocr) == n_paginas:
            return ParsedDoc(name=nome, blocks=(), meta=meta)

    blocos: list[Block] = []
    pilha: list[tuple[int, str]] = []
    for numero, markdown in paginas:
        if numero in ocr_set or not markdown.strip():
            continue
        blocos.extend(
            blocos_de_markdown(markdown, locator=f"p. {numero}", pilha=pilha, fallback_titulo=False)
        )

    if not blocos and total_chars:
        # texto sem nenhuma estrutura detectada: melhor um bloco por página que nada
        blocos = [
            Block(heading_path=(), text=t.strip(), locator=f"p. {n}", kind=BlockKind.TEXT)
            for n, t in paginas
            if t.strip() and n not in ocr_set
        ]

    _anexar_extras(blocos, extras)
    return ParsedDoc(name=nome, blocks=tuple(blocos), meta=meta)


def _extras_do_documento(documento) -> list[tuple[int, str]]:  # noqa: ANN001
    return [
        (i, t)
        for i, pagina in enumerate(documento, start=1)
        for t in _extras_da_pagina(pagina)
    ]


def _anexar_extras(blocos: list[Block], extras: list[tuple[int, str]]) -> None:
    ja = "\n".join(b.text for b in blocos)
    for numero, extra in extras:
        if extra and extra not in ja:
            blocos.append(Block(heading_path=(), text=extra, locator=f"p. {numero} (campo)"))
            ja += "\n" + extra
