"""Text that Office stores in the ZIP but python-pptx/docx never walk.

SmartArt lives in `ppt/diagrams/*.xml` (`a:t` runs). Word text boxes live in
`w:txbxContent`. Headers, footnotes and chart titles are the same class: the
file has the characters, the structured API never visits the part.

The well-known fix (python-pptx #83, unzip+grep of `a:t`/`w:t`) is to harvest
the package XML and keep whatever the structured parse did not already emit.
No new dependency. Skip `w:del` (track-changes deletions).
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from ..document import Block

# DrawingML run and Word run. Spreadsheet inline strings use a different `t`.
_TAGS_TEXTO = frozenset({"t"})
_TAGS_PULAR_SUBARVORE = frozenset({"del"})  # w:del — texto apagado no controle de alterações

_IGNORAR_PARTE = re.compile(
    r"(slideLayout|slideMaster|notesMaster|theme\d|tableStyles|presProps|"
    r"viewProps|fontTable|webSettings|settings\.xml|styles\.xml|"
    r"\[Content_Types\]|_rels/|docProps/)",
    re.IGNORECASE,
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _textos_xml(xml: bytes) -> list[str]:
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        return []
    saida: list[str] = []

    def andar(elem: ET.Element, pular: bool) -> None:
        nome = _local(elem.tag)
        agora = pular or nome in _TAGS_PULAR_SUBARVORE
        if not agora and nome in _TAGS_TEXTO and elem.text:
            trecho = elem.text.strip()
            if trecho:
                saida.append(trecho)
        for filho in elem:
            andar(filho, agora)

    andar(raiz, False)
    return saida


def colher_partes(dados: bytes) -> list[tuple[str, list[str]]]:
    """`(part_name, run texts)` for XML parts that can hold visible text."""
    if not dados.startswith(b"PK"):
        return []
    saida: list[tuple[str, list[str]]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as zf:
            for info in zf.infolist():
                nome = info.filename.replace("\\", "/")
                if not nome.lower().endswith(".xml"):
                    continue
                if _IGNORAR_PARTE.search(nome):
                    continue
                try:
                    bruto = zf.read(info)
                except Exception:  # noqa: BLE001 — parte ilegível não derruba o arquivo
                    continue
                textos = _textos_xml(bruto)
                if textos:
                    saida.append((nome, textos))
    except zipfile.BadZipFile:
        return []
    return saida


def _normalizar(texto: str) -> str:
    return " ".join(texto.split()).casefold()


def completar(dados: bytes, blocos: list[Block]) -> None:
    """Append leftover package text onto an existing structured parse."""
    ja = "\n".join(b.text for b in blocos)
    blocos.extend(sobras(dados, ja))


def sobras(dados: bytes, ja_extraido: str) -> list[Block]:
    """Blocks with package text that the structured parse did not emit."""
    coberto = _normalizar(ja_extraido)
    blocos: list[Block] = []
    for parte, textos in colher_partes(dados):
        novos = [t for t in textos if len(t) >= 2 and _normalizar(t) not in coberto]
        if not novos:
            continue
        corpo = "\n".join(novos)
        blocos.append(
            Block(
                heading_path=(),
                text=corpo,
                locator=_rotulo(parte),
            )
        )
        coberto += " " + _normalizar(corpo)
    return blocos


def _rotulo(parte: str) -> str:
    baixo = parte.replace("\\", "/").lower()
    if "/diagrams/" in baixo:
        return "diagrama"
    if "/charts/" in baixo:
        return "grafico"
    if "header" in baixo:
        return "cabecalho"
    if "footer" in baixo:
        return "rodape"
    if "footnote" in baixo:
        return "nota"
    if "endnote" in baixo:
        return "nota_final"
    if "comment" in baixo:
        return "comentario"
    if "/notes" in baixo:
        return "notas"
    return "ooxml"
