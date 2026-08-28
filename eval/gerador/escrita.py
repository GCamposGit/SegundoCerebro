"""Como cada formato chega ao disco — um lugar só, e com caminho estendido.

Separado de `nucleo.py` em 25/08/2026 (`E1.e`) porque a escrita deixou de ser
três linhas: são catorze formatos, quatro deles existindo só para o indexador
tropeçar neles, e um que mexe em atributo de arquivo do Windows.

## O prefixo `\\\\?\\` não é detalhe

`CLAUDE.md` manda prefixar caminho longo ao **abrir** arquivo no Windows, e o
projeto tem `census.caminho_estendido()` desde a F1. O gerador não o usava — e
por isso o corpus sintético **não conseguia conter** a armadilha de caminho longo,
que é justamente a que o acervo real tem 34 vezes, com o maior em 293 caracteres.

Medido em 25/08/2026: criar `…/aaa…/bbb…/ccc…/contrato_ddd….txt` (425 caracteres)
falha já no `mkdir`, com `WinError 3 — o sistema não pode encontrar o caminho`.
Com o prefixo, funciona. O modo de falha sem ele é o pior possível: "arquivo não
encontrado" para um arquivo que você acabou de mandar criar.

Usa-se `census.caminho_estendido` e não uma cópia local **de propósito**: duas
implementações da mesma regra divergem, e o leitor (`ingest/reader.py:read_bytes`)
já usa aquela. Gerador e leitor têm de concordar sobre o que é um caminho.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

from segundocerebro.census import caminho_estendido

FORMATOS_DE_TEXTO = ("txt", "md", "markdown", "csv", "vtt", "srt", "sbv", "eml", "rtf")
"""Formatos que sao texto no disco.

`vtt`, `srt`, `sbv` e `eml` sao formato para o harness -- `eval.fonte` classifica
por extensao (`EXTENSOES_DE_TRANSCRICAO`, `EXTENSOES_DE_EMAIL`) -- e o parser de
email de 21/08 le MIME. `rtf` e texto marcado que o parser de texto do produto le.
Escrever binario neles nao acrescentaria nada e tiraria a legibilidade do corpus.

**Texto no disco nao quer dizer prosa.** As tres de transcricao levam legenda com
marca de tempo, montada por `gerador/transcricao.py`: desde o `F4-T` o produto le
esses formatos, e um arquivo de prosa com extensao `.srt` volta vazio do parser.
"""


def _abrir(destino: Path, modo: str):
    """`open` que sobrevive a caminho acima de 260 caracteres."""
    return open(caminho_estendido(destino), modo)  # noqa: SIM115, PTH123


def _preparar(destino: Path) -> None:
    os.makedirs(caminho_estendido(destino.parent), exist_ok=True)


def _texto(destino: Path, conteudo: str) -> None:
    with _abrir(destino, "w") as fh:
        fh.write(conteudo)


def _bytes(destino: Path, conteudo: bytes) -> None:
    with _abrir(destino, "wb") as fh:
        fh.write(conteudo)


def _pdf(destino: Path, texto: str) -> None:
    import pymupdf

    pdf = pymupdf.open()
    pagina = pdf.new_page()
    if texto:
        pagina.insert_textbox(pymupdf.Rect(50, 50, 545, 790), texto, fontsize=11)
    pdf.save(caminho_estendido(destino))
    pdf.close()


def _xlsx(destino: Path, texto: str, *, formula_sem_cache: bool = False, abas: int = 1) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    linhas = texto.split("\n")
    for indice in range(abas):
        aba = wb.active if indice == 0 else wb.create_sheet()
        aba.title = f"Aba {indice + 1}"
        for i, linha in enumerate(linhas, start=1):
            aba.cell(row=i, column=1, value=linha)
        if formula_sem_cache:
            # A armadilha do `C7.a`, e ela e silenciosa: `openpyxl` com
            # `data_only=True` devolve `None` quando o Excel nao gravou o valor
            # calculado. O documento indexa como `ok` e a celula simplesmente
            # nao existe no texto extraido. Medido: a planilha inteira rende 5
            # caracteres onde deveria render o resultado.
            aba.cell(row=len(linhas) + 1, column=1, value="=SUM(1,2)")
    wb.save(caminho_estendido(destino))


def _pptx(destino: Path, texto: str) -> None:
    from pptx import Presentation
    from pptx.util import Emu

    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    caixa = slide.shapes.add_textbox(Emu(457200), Emu(457200), Emu(8229600), Emu(4572000))
    quadro = caixa.text_frame
    linhas = texto.split("\n")
    quadro.text = linhas[0] if linhas else ""
    for linha in linhas[1:]:
        quadro.add_paragraph().text = linha
    pres.save(caminho_estendido(destino))


def _docx(destino: Path, texto: str) -> None:
    import docx as dx

    documento = dx.Document()
    for paragrafo in texto.split("\n"):
        documento.add_paragraph(paragrafo)
    documento.save(caminho_estendido(destino))


def _marcar_placeholder(destino: Path) -> bool:
    """Marca o arquivo como placeholder de nuvem. Devolve se conseguiu.

    `FILE_ATTRIBUTE_OFFLINE` (0x1000) está na `CLOUD_ONLY_MASK` do censo, e
    `SetFileAttributesW` o aplica sem OneDrive nenhum — conferido em 25/08/2026,
    `attrs=0x1000` e `cloud_only=True`. É o que permite ter a armadilha de
    placeholder num corpus gerado, e ela importa mais que as outras: ler um
    placeholder **baixa o arquivo**, então o defeito custa banda e tempo de quem
    instala, não só uma métrica.

    Só existe no Windows. Fora dele devolve `False`, e quem chama registra em
    `caps` — que é dimensão do selo desde o `E1.a`, então um corpus gerado no
    Linux não se confunde com um gerado aqui.
    """
    if os.name != "nt":
        return False
    import ctypes

    return bool(ctypes.windll.kernel32.SetFileAttributesW(caminho_estendido(destino), 0x1000))


def escrever(doc, raiz):  # noqa: ANN001
    """Um documento no disco, no formato que ele declara."""
    destino = raiz / doc.caminho
    _preparar(destino)
    formato = doc.formato

    if formato == "cfb_pronto":
        # O container OLE ja veio montado pela fatia (`.msg`, `.doc`, `.ppt`).
        # Viaja em `Doc.texto` como latin-1 porque `Doc` guarda texto e o hash
        # logico do manifesto e sobre ele -- latin-1 e a unica codificacao que
        # faz a viagem byte-a-byte sem perda.
        _bytes(destino, doc.texto.encode("latin-1"))
    elif formato in FORMATOS_DE_TEXTO:
        _texto(destino, doc.texto)
    elif formato in ("docx", "docm"):
        _docx(destino, doc.texto)
    elif formato in ("xlsx", "xlsm"):
        _xlsx(destino, doc.texto)
    elif formato in ("pptx", "pptm"):
        _pptx(destino, doc.texto)
    elif formato == "pdf":
        _pdf(destino, doc.texto)

    # --- os que existem para o indexador tropeçar ---------------------------
    elif formato == "pdf_digitalizado":
        # PDF **válido** e sem texto: uma página em branco. Status `vazio`, que é
        # diferente de `erro` — e é o caso que importa, porque o documento entra
        # no registro sem nenhum chunk e fica invisível até para o ranqueador de
        # nome. O documento que a multi-hop do grafo precisa é exatamente este.
        _pdf(destino, "")
    elif formato == "pdf_truncado":
        _bytes(destino, b"%PDF-1.4\n" + b"\x00\x01lixo" * 40)
    elif formato == "zip_como_docx":
        with zipfile.ZipFile(caminho_estendido(destino), "w") as z:
            z.writestr("x/nada.bin", b"\x00" * 128)
    elif formato == "html_como_xls":
        # O achado do `F4-L`: `.xls` que na verdade é HTML. Medido em 25/08: o
        # parser de planilha **lê** e devolve o identificador. A fixture existe
        # para travar esse comportamento — se um dia ele passar a levantar erro,
        # é decisão, não acidente.
        _bytes(destino, doc.texto.encode("utf-8"))
    elif formato == "xlsx_formula_sem_cache":
        _xlsx(destino, doc.texto, formula_sem_cache=True)
    elif formato == "xlsx_muitas_abas":
        _xlsx(destino, doc.texto, abas=12)
    elif formato == "sem_parser":
        _bytes(destino, doc.texto.encode("utf-8"))
    elif formato == "vazio":
        _bytes(destino, b"")
    elif formato == "owner_do_word":
        # `~$nome.docx`: o arquivo de 162 bytes que o Word deixa ao abrir um
        # documento. Não é docx, o nome mente sobre o conteúdo, e ele aparece aos
        # pares com o documento de verdade em qualquer pasta de trabalho viva.
        _bytes(destino, b"\x00\x06" + b" " * 160)
    elif formato == "grande":
        # Acima do corte por tipo (`[base.limites]`): status `adiado`, decidido
        # pelo `stat` **antes de abrir**. Não é falha — é "esta passada quer
        # terminar" — e é o único status que o tamanho sozinho produz.
        _texto(destino, doc.texto)
    elif formato == "placeholder_de_nuvem":
        _texto(destino, doc.texto)
        return _marcar_placeholder(destino)
    else:
        raise ValueError(f"formato desconhecido: {formato}")

    _datar(destino, doc.meta.get("mtime"))
    return True


def _datar(destino: Path, marca: str | None) -> None:
    """Fixa o mtime quando a fatia o declara. `AAAA-MM-DD`, UTC.

    **O mtime é contrato, não enfeite.** `retrieve/familias.py` desempata família
    de versão por número declarado e, na falta dele, por data — e o caso que criou
    a regra é justamente a revisão **sem** `_vN` que é mais nova que a `_v6`. Sem
    controlar o mtime, essa fatia mediria a ordem em que o gerador escreveu os
    arquivos, que é acidente.

    Fora daí o mtime fica o do sistema de arquivos, e é o certo: fingir data em
    documento que não depende dela só criaria uma correlação inventada.
    """
    if not marca:
        return
    from datetime import datetime, timezone

    quando = datetime.strptime(marca, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    os.utime(caminho_estendido(destino), (quando, quando))
