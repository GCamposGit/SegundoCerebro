"""Indexing queue order: waves, small dense folders first, current version first.

Metadata only — never opens file content. Rules in
`docs/prioridade-de-indexacao.md`. Keep version markers aligned with
`retrieve.familias.MARCADORES`, but this module must not import retrieve
(ranking stays on the notebook).
"""

from __future__ import annotations

import math
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..census import FileEntry
from ..ingest.parsers import supported_extensions

# Wave 1 / 2 size caps in MB. Wave 3 is "the rest still under [base.limites]".
# Wave 4 is old versions, dumps, and anything above the wave-2 cap.
# Defaults for any corpus, not measurements of one disk.
TETO_ONDA_1_MB: dict[str, float] = {
    ".md": 100.0,
    ".markdown": 100.0,
    ".docx": 0.5,
    ".docm": 0.5,
    ".doc": 0.5,
    ".rtf": 0.5,
    ".pdf": 2.0,
    ".pptx": 5.0,
    ".pptm": 5.0,
    ".ppt": 5.0,
    ".xlsx": 2.0,
    ".xlsm": 2.0,
    ".xls": 2.0,
    ".txt": 0.1,
    ".csv": 0.256,
}

TETO_ONDA_2_MB: dict[str, float] = {
    ".md": 100.0,
    ".markdown": 100.0,
    ".docx": 2.0,
    ".docm": 2.0,
    ".doc": 2.0,
    ".rtf": 2.0,
    ".pdf": 8.0,
    ".pptx": 15.0,
    ".pptm": 15.0,
    ".ppt": 15.0,
    ".xlsx": 15.0,
    ".xlsm": 15.0,
    ".xls": 15.0,
    ".txt": 2.0,
    ".csv": 2.0,
}

TETO_ONDA_1_PADRAO_MB = 2.0
TETO_ONDA_2_PADRAO_MB = 15.0
ONDAS = 4

# Token, not substring: "catalog" and "dialog" must not match.
DUMP_TOKENS = re.compile(
    r"(?:^|[_\-\s.])(?:dump|export|backup|log)(?:$|[_\-\s.\d])",
    re.IGNORECASE,
)

# Conservative subset of retrieve.familias.MARCADORES. Do not strip
# final/revisado: the current file often carries those labels and no _vN
# (the g010 shape — newest mtime wins).
MARCADORES_VERSAO = (
    re.compile(r"[ _\-]*v\d+(?:[._]\d+)*\b", re.IGNORECASE),
    re.compile(r"\s*\(\d+\)"),
    re.compile(r"[ _\-]*c[oó]pia(?:\s+de)?", re.IGNORECASE),
    re.compile(r"[ _\-]*copy(?:\s+of)?", re.IGNORECASE),
    re.compile(r"[ _\-]*bkp\d*(?:[._]\d+)*", re.IGNORECASE),
    re.compile(
        r"[ _\-]*(?:final|finalizado|atualizado|comentado|revisado|revisada|"
        r"apresentado|antigo|old|rev\d*)\b",
        re.IGNORECASE,
    ),
)

# Initials of a reviewer — `_GC`, `_TI`. Uppercase only, before lowercasing,
# or `_de` / `_ia` would glue distinct documents. Keep aligned with
# retrieve.familias.INICIAIS.
INICIAIS = re.compile(r"[ _\-][A-Z]{2,3}$")

SEGUNDOS_POR_ANO = 365.25 * 24 * 3600


@dataclass(frozen=True)
class ItemFila:
    """One queued file plus the wave it belongs to."""

    arquivo: FileEntry
    onda: int
    pasta: str
    vigente: bool


def extensao_de(rel: str) -> str:
    return os.path.splitext(rel.replace("\\", "/"))[1].lower()


def pasta_de(rel: str) -> str:
    partes = rel.replace("\\", "/").split("/")
    if len(partes) <= 1:
        return ""
    return "/".join(partes[:-1])


def indexaveis(
    arquivos: Iterable[FileEntry],
    extensoes: Iterable[str] | None = None,
) -> list[FileEntry]:
    """Keep only extensions that have a parser. Noise never enters the queue."""
    permitidas = frozenset(
        e.lower() for e in (extensoes if extensoes is not None else supported_extensions())
    )
    return [a for a in arquivos if extensao_de(a.rel) in permitidas]


def chave_de_versao(rel: str) -> str:
    """Folder + extension + stem without version/copy markers.

    Extension stays in the key (pdf and pptx of the same stem are not a family).
    Folder stays in the key (same name in two folders is not a family).
    """
    partes = rel.replace("\\", "/").split("/")
    pasta, nome = "/".join(partes[:-1]), partes[-1]
    if "." in nome:
        tronco, extensao = nome.rsplit(".", 1)
    else:
        tronco, extensao = nome, ""
    anterior = None
    while anterior != tronco:
        anterior = tronco
        tronco = INICIAIS.sub("", tronco)
        for marcador in MARCADORES_VERSAO:
            tronco = marcador.sub("", tronco)
    tronco = re.sub(r"[ _\-.]+", " ", tronco).strip().lower()
    return f"{pasta.lower()}::{extensao.lower()}::{tronco or nome.lower()}"


def vigentes(arquivos: Sequence[FileEntry]) -> set[str]:
    """Newest mtime in each version family. Version number in the name never wins."""
    por_chave: dict[str, FileEntry] = {}
    for arquivo in arquivos:
        chave = chave_de_versao(arquivo.rel)
        atual = por_chave.get(chave)
        if atual is None or arquivo.mtime > atual.mtime or (
            arquivo.mtime == atual.mtime and arquivo.rel > atual.rel
        ):
            por_chave[chave] = arquivo
    return {a.rel for a in por_chave.values()}


def e_dump(rel: str) -> bool:
    """Dump/export/backup/log as a path token, not a substring of another word."""
    for parte in rel.replace("\\", "/").split("/"):
        tronco = parte.rsplit(".", 1)[0] if "." in parte else parte
        if DUMP_TOKENS.search(tronco):
            return True
    return False


def onda_de(
    arquivo: FileEntry,
    *,
    vigentes_rels: set[str],
    teto_1: dict[str, float] | None = None,
    teto_2: dict[str, float] | None = None,
) -> int:
    if arquivo.rel not in vigentes_rels:
        return 4
    if e_dump(arquivo.rel):
        return 4
    ext = extensao_de(arquivo.rel)
    mb = arquivo.size / 1_000_000
    t1 = (teto_1 or TETO_ONDA_1_MB).get(ext, TETO_ONDA_1_PADRAO_MB)
    t2 = (teto_2 or TETO_ONDA_2_MB).get(ext, TETO_ONDA_2_PADRAO_MB)
    if mb <= t1:
        return 1
    if mb <= t2:
        return 2
    return 3


def _score_pasta(
    itens: Sequence[FileEntry],
    *,
    indexaveis_na_pasta: int,
    agora: float,
) -> float:
    n = len(itens)
    if n == 0:
        return 0.0
    bytes_ = sum(a.size for a in itens)
    mtime_max = max(a.mtime for a in itens)
    idade_anos = max(0.0, (agora - mtime_max) / SEGUNDOS_POR_ANO)
    recencia = 1.0 / (1.0 + idade_anos)
    densidade = n / max(1, indexaveis_na_pasta)
    return (n / (1.0 + math.log1p(bytes_))) * densidade * recencia


def ordenar(
    arquivos: Sequence[FileEntry],
    *,
    apenas_onda: int | None = None,
    agora: float | None = None,
) -> list[FileEntry]:
    """Wave ASC, then folder score DESC, then size ASC, then newer mtime first."""
    return [item.arquivo for item in planejar(arquivos, apenas_onda=apenas_onda, agora=agora)]


def montar_trabalho(
    enumerados: Sequence[tuple],
    *,
    apenas_onda: int | None = None,
    so_raiz: str | None = None,
) -> list[tuple]:
    """Process queue. Enumeration/`vistos` stay complete; this only picks work.

    `--raiz` must not drop other roots from `vistos`: that would look like they
    vanished and reconciliation would delete them.
    """
    if so_raiz:
        nomes = [root.name for root, _arquivos in enumerados]
        if so_raiz not in nomes:
            from ..config import ErroDeConfig

            raise ErroDeConfig(
                f"A raiz '{so_raiz}' não está nesta base. "
                f"Disponíveis: {', '.join(nomes) or '(nenhuma)'}."
            )
    saida: list[tuple] = []
    for root, arquivos in enumerados:
        if so_raiz and root.name != so_raiz:
            continue
        saida.append((root, ordenar(indexaveis(arquivos), apenas_onda=apenas_onda)))
    return saida


def planejar(
    arquivos: Sequence[FileEntry],
    *,
    apenas_onda: int | None = None,
    agora: float | None = None,
) -> list[ItemFila]:
    lista = list(arquivos)
    if not lista:
        return []
    vig = vigentes(lista)
    por_pasta_todos: dict[str, int] = defaultdict(int)
    for arquivo in lista:
        por_pasta_todos[pasta_de(arquivo.rel)] += 1

    itens: list[ItemFila] = []
    for arquivo in lista:
        onda = onda_de(arquivo, vigentes_rels=vig)
        if apenas_onda is not None and onda != apenas_onda:
            continue
        itens.append(
            ItemFila(
                arquivo=arquivo,
                onda=onda,
                pasta=pasta_de(arquivo.rel),
                vigente=arquivo.rel in vig,
            )
        )

    instante = time.time() if agora is None else agora
    por_onda_pasta: dict[tuple[int, str], list[FileEntry]] = defaultdict(list)
    for item in itens:
        por_onda_pasta[(item.onda, item.pasta)].append(item.arquivo)

    scores: dict[tuple[int, str], float] = {}
    for chave, grupo in por_onda_pasta.items():
        _onda, pasta = chave
        scores[chave] = _score_pasta(
            grupo,
            indexaveis_na_pasta=por_pasta_todos[pasta],
            agora=instante,
        )

    itens.sort(
        key=lambda item: (
            item.onda,
            -scores[(item.onda, item.pasta)],
            item.arquivo.size,
            -item.arquivo.mtime,
            item.arquivo.rel,
        )
    )
    return itens
