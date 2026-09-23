"""Internal occurrence identity: one file in one root of one base (FND-01b).

`doc_id` remains the public content id. This module only names the row in
`documentos`. Consumers must not parse `ocorrencia_id`. Physical drive letters
are not part of the id; remapping a root is an explicit command, not a rename.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any

from .esquema import SCHEMA_VERSAO

if TYPE_CHECKING:
    import sqlite3

    from .store import Store

TAMANHO_OCORRENCIA_ID = 16


class CaminhoRelativoInvalido(ValueError):
    """Relative path is absolute, has a drive, or climbs out of the root."""


class CaminhoAmbiguo(ValueError):
    """A relative path exists in more than one configured root."""


def caminho_rel(path: str) -> str:
    """POSIX relative path: no drive, no `..`, no leading slash."""
    texto = path.replace("\\", "/").strip()
    if not texto or texto.startswith("/") or texto.endswith("/"):
        raise CaminhoRelativoInvalido(f"caminho relativo inválido: {path!r}")
    if len(texto) >= 2 and texto[1] == ":":
        raise CaminhoRelativoInvalido(f"caminho relativo não leva letra de disco: {path!r}")
    partes = texto.split("/")
    if "" in partes or any(p == ".." or p == "." for p in partes):
        raise CaminhoRelativoInvalido(f"caminho relativo inválido: {path!r}")
    return texto


def id_de(root_id: str, path: str) -> str:
    """Opaque id for `(root_id, relative path)`. Same inputs reproduce it."""
    raiz = root_id.strip()
    if not raiz:
        raise ValueError("root_id vazio")
    rel = caminho_rel(path)
    return sha256(f"{raiz}\0{rel}".encode()).hexdigest()[:TAMANHO_OCORRENCIA_ID]


def chave_de(
    store: Store,
    path: str,
    *,
    root_id: str = "",
    ocorrencia_id: str = "",
) -> str:
    """Resolve the internal key while retaining path-only compatibility.

    Low-level callers historically passed only a path. That remains valid for a
    unique path (and for legacy stores); a v2 store refuses to guess when two
    roots contain the same relative path.
    """
    rel = caminho_rel(path)
    if ocorrencia_id:
        return ocorrencia_id
    if root_id:
        return id_de(root_id, rel)
    if not usa_ocorrencia(store.con):
        return rel
    linhas = store.con.execute(
        "SELECT ocorrencia_id FROM documentos WHERE path = ?", (rel,)
    ).fetchall()
    if len(linhas) > 1:
        raise CaminhoAmbiguo(
            f"o caminho relativo '{rel}' existe em mais de uma raiz; informe root_id"
        )
    return str(linhas[0][0]) if linhas else rel


def usa_ocorrencia(con: sqlite3.Connection) -> bool:
    """True when `documentos` already uses `ocorrencia_id` as primary key."""
    try:
        colunas = list(con.execute("PRAGMA table_info(documentos)"))
    except Exception:  # noqa: BLE001 — table missing on a brand-new file
        return False
    return any(str(r["name"]) == "ocorrencia_id" and int(r["pk"]) == 1 for r in colunas)


def estampar_schema(con: sqlite3.Connection) -> None:
    """Record schema version. Does not migrate a primary key."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)"
    )
    if con.execute("SELECT 1 FROM meta WHERE chave = 'schema_versao'").fetchone():
        return
    versao = SCHEMA_VERSAO if usa_ocorrencia(con) else "1"
    con.execute(
        "INSERT INTO meta (chave, valor) VALUES ('schema_versao', ?)",
        (versao,),
    )


def registrar(
    store: Store,
    *,
    path: str,
    raiz: str,
    tamanho: int,
    mtime: float,
    status: str,
    sha256: str = "",
    detalhe: str = "",
    n_chunks: int = 0,
    model_id: str = "",
    chunker: str = "",
    parser: str = "",
    natureza: Any = None,  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
) -> str:
    """Insert or update one document row. Returns `ocorrencia_id` on v2, path on v1."""
    rel = caminho_rel(path)
    root_id = raiz.strip()
    extras, atualiza = _natureza(store, natureza)
    from .store import agora as _agora

    quando = _agora()
    if usa_ocorrencia(store.con):
        return _registrar_v2(
            store,
            rel=rel,
            root_id=root_id,
            tamanho=tamanho,
            mtime=mtime,
            status=status,
            sha256=sha256,
            detalhe=detalhe,
            n_chunks=n_chunks,
            model_id=model_id,
            chunker=chunker,
            parser=parser,
            extras=extras,
            atualiza=atualiza,
            quando=quando,
        )
    _registrar_v1(
        store,
        rel=rel,
        root_id=root_id,
        tamanho=tamanho,
        mtime=mtime,
        status=status,
        sha256=sha256,
        detalhe=detalhe,
        n_chunks=n_chunks,
        model_id=model_id,
        chunker=chunker,
        parser=parser,
        extras=extras,
        atualiza=atualiza,
        quando=quando,
    )
    return rel


def _natureza(store: Store, natureza: Any) -> tuple[tuple[object, ...], str]:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    # Sem natureza, preserva a gravada: o filho que morre por recurso devolve
    # `ParseResult` sem ela, o UPDATE zerava `digitalizado`, e o scan saía da
    # fila de OCR em silêncio (30/08/2026).
    colunas = store.COLUNAS_NATUREZA
    valores = natureza.como_colunas() if natureza is not None else {}
    extras = tuple(valores.get(c, "" if c == "familia_real" else 0) for c in colunas)
    origem = "excluded" if natureza is not None else "documentos"
    atualiza = ", ".join(f"{c}={origem}.{c}" for c in colunas)
    return extras, atualiza


def _registrar_v1(
    store: Store,
    *,
    rel: str,
    root_id: str,
    tamanho: int,
    mtime: float,
    status: str,
    sha256: str,
    detalhe: str,
    n_chunks: int,
    model_id: str,
    chunker: str,
    parser: str,
    extras: tuple[object, ...],
    atualiza: str,
    quando: str,
) -> None:
    lista = ", ".join(store.COLUNAS_NATUREZA)
    marcas = ", ".join("?" * len(store.COLUNAS_NATUREZA))
    store.con.execute(
        f"""
        INSERT INTO documentos
            (path, raiz, tamanho, mtime, sha256, status, detalhe, n_chunks,
             model_id, chunker, parser, indexado_em, {lista})
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?, {marcas})
        ON CONFLICT(path) DO UPDATE SET
            raiz=excluded.raiz, tamanho=excluded.tamanho, mtime=excluded.mtime,
            sha256=excluded.sha256, status=excluded.status, detalhe=excluded.detalhe,
            n_chunks=excluded.n_chunks, model_id=excluded.model_id,
            chunker=excluded.chunker, parser=excluded.parser,
            indexado_em=excluded.indexado_em, {atualiza}
        """,
        (
            rel, root_id, tamanho, mtime, sha256, status, detalhe, n_chunks,
            model_id, chunker, parser, quando,
        )
        + extras,
    )


def _registrar_v2(
    store: Store,
    *,
    rel: str,
    root_id: str,
    tamanho: int,
    mtime: float,
    status: str,
    sha256: str,
    detalhe: str,
    n_chunks: int,
    model_id: str,
    chunker: str,
    parser: str,
    extras: tuple[object, ...],
    atualiza: str,
    quando: str,
) -> str:
    if not root_id:
        raise ValueError("root_id vazio")
    oid = id_de(root_id, rel)
    lista = ", ".join(store.COLUNAS_NATUREZA)
    marcas = ", ".join("?" * len(store.COLUNAS_NATUREZA))
    store.con.execute(
        f"""
        INSERT INTO documentos
            (ocorrencia_id, root_id, path, raiz, tamanho, mtime, sha256, status,
             detalhe, n_chunks, model_id, chunker, parser, indexado_em, {lista})
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, {marcas})
        ON CONFLICT(ocorrencia_id) DO UPDATE SET
            root_id=excluded.root_id, path=excluded.path, raiz=excluded.raiz,
            tamanho=excluded.tamanho, mtime=excluded.mtime,
            sha256=excluded.sha256, status=excluded.status, detalhe=excluded.detalhe,
            n_chunks=excluded.n_chunks, model_id=excluded.model_id,
            chunker=excluded.chunker, parser=excluded.parser,
            indexado_em=excluded.indexado_em, {atualiza}
        """,
        (
            oid, root_id, rel, root_id, tamanho, mtime, sha256, status, detalhe,
            n_chunks, model_id, chunker, parser, quando,
        )
        + extras,
    )
    store.con.execute(
        "INSERT INTO raizes (root_id, rotulo) VALUES (?, ?) "
        "ON CONFLICT(root_id) DO UPDATE SET rotulo=excluded.rotulo",
        (root_id, root_id),
    )
    return oid
