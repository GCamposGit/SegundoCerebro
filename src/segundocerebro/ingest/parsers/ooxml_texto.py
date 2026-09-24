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


def _e_grafico(nome: str) -> bool:
    """`chart1.xml` holds the cache. Style and color parts do not."""
    base = nome.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base.startswith("chart") and base.endswith(".xml")


def _filho(elem: ET.Element, nome: str) -> ET.Element | None:
    for filho in elem:
        if _local(filho.tag) == nome:
            return filho
    return None


def _primeiro_rotulo(elem: ET.Element | None) -> str:
    """First cached `c:v` or DrawingML `a:t` under this node."""
    if elem is None:
        return ""
    for no in elem.iter():
        if _local(no.tag) in {"v", "t"} and (no.text or "").strip():
            return no.text.strip()
    return ""


def _pontos(elem: ET.Element | None) -> list[str]:
    """Point values in `idx` order. The first value at an index wins."""
    if elem is None:
        return []
    por_indice: dict[int, str] = {}
    for no in elem.iter():
        if _local(no.tag) != "pt":
            continue
        bruto = no.attrib.get("idx", "")
        indice = int(bruto) if bruto.isdigit() else len(por_indice)
        if indice in por_indice:
            continue
        for filho in no:
            if _local(filho.tag) == "v" and (filho.text or "").strip():
                por_indice[indice] = filho.text.strip()
                break
    return [por_indice[i] for i in sorted(por_indice)]


def _linhas_da_serie(ser: ET.Element) -> list[str]:
    nome = _primeiro_rotulo(_filho(ser, "tx"))
    categorias = _pontos(_filho(ser, "cat")) or _pontos(_filho(ser, "xVal"))
    valores = _pontos(_filho(ser, "val")) or _pontos(_filho(ser, "yVal"))
    linhas: list[str] = []
    for i in range(max(len(categorias), len(valores))):
        categoria = categorias[i] if i < len(categorias) else ""
        valor = valores[i] if i < len(valores) else ""
        if not categoria and not valor:
            continue
        linhas.append(" | ".join(p for p in (nome, categoria, valor) if p))
    return linhas


def _texto_do_grafico(raiz: ET.Element) -> str:
    """Series rows only. A title with no cached point is not a chart value."""
    linhas: list[str] = []
    titulo = ""
    for no in raiz.iter():
        if _local(no.tag) == "title" and not titulo:
            titulo = _primeiro_rotulo(no)
        elif _local(no.tag) == "ser":
            linhas.extend(_linhas_da_serie(no))
    if not linhas:
        return ""
    if titulo:
        return titulo + "\n" + "\n".join(linhas)
    return "\n".join(linhas)


def blocos_de_embeddings(dados: bytes, ja_extraido: str) -> list[Block]:
    """Chart workbook embedded in the package, when the cache did not keep it.

    A chart with only `c:f` stores the grid under `embeddings/*.xlsx`. Lines
    already present in the `c:v` block are not repeated.
    """
    if not dados.startswith(b"PK"):
        return []
    coberto = _normalizar(ja_extraido)
    blocos: list[Block] = []
    try:
        pacote = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        return []
    with pacote:
        nomes = sorted(
            n for n in pacote.namelist()
            if "/embeddings/" in n.replace("\\", "/").lower() and n.lower().endswith(".xlsx")
        )
        for nome in nomes:
            bloco = _bloco_da_planilha(pacote, nome, coberto)
            if bloco is None:
                continue
            blocos.append(bloco)
            coberto += " " + _normalizar(bloco.text)
    return blocos


def _bloco_da_planilha(pacote: zipfile.ZipFile, nome: str, coberto: str) -> Block | None:
    from .sheets import parse_xlsx

    try:
        doc = parse_xlsx(pacote.read(nome), nome.replace("\\", "/").rsplit("/", 1)[-1])
    except (OSError, zipfile.BadZipFile):
        return None
    linhas: list[str] = []
    for bloco in doc.blocks:
        for linha in bloco.text.splitlines():
            chave = _normalizar(linha)
            if len(chave) < 2 or chave in coberto:
                continue
            linhas.append(linha.strip())
            coberto += " " + chave
    if not linhas:
        return None
    return Block(heading_path=(), text="\n".join(linhas), locator="grafico")


def blocos_de_grafico(dados: bytes) -> list[Block]:
    """Cached chart values live in `c:v`. The `a:t` harvest never reads them.

    python-pptx walks text frames, tables and groups. A chart is a graphic
    frame, so reading `.text` on the open file misses the series. Points are
    emitted in `idx` order, one block per `chartN.xml`. A chart that only has
    a formula (`c:f`) and no cache yields nothing: the numbers are in the
    embedded workbook, which this function does not open.
    """
    if not dados.startswith(b"PK"):
        return []
    blocos: list[Block] = []
    try:
        pacote = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        return []
    with pacote:
        nomes = sorted(n for n in pacote.namelist() if _e_grafico(n))
        for nome in nomes:
            try:
                raiz = ET.fromstring(pacote.read(nome))
            except (ET.ParseError, OSError, zipfile.BadZipFile):
                continue
            texto = _texto_do_grafico(raiz)
            if texto:
                blocos.append(Block(heading_path=(), text=texto, locator="grafico"))
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
