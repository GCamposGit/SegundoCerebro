"""Idempotent write across SQLite and LanceDB (FND-02b).

Crash between the two stores used to leave equal counts and different ids.
The journal is committed before any Lance mutation. Recovery never invents
embeddings: if the intended ids are already on disk it confirms them; if the
write is partial it aborts the path so the next indexer pass reprocesses
the file. Reading is allowed after the journal row is gone, or after a
successful recovery. A live indexer holds TravaDeIndice; readers then refuse
via recusar_se_indexando instead of recovering under the writer.

Stages: preparar → deletar → textos → vetores → carimbo → verificar → publicar.
`lexical` skips vetores. `vetores` (pass 2) does not delete SQLite chunks.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import numpy as np

from ..ingest.chunking import Chunk
from ..logger import get_logger
from .store import TABELA_VETORES, agora
from .trava import TravaDeIndice, TravaOcupada

if TYPE_CHECKING:
    from .store import Store

log = get_logger("index.operacoes")

ETAPAS = ("preparar", "deletar", "textos", "vetores", "carimbo", "verificar", "publicar")
TIPOS = ("completo", "lexical", "vetores")

_FALHA_APOS: str | None = None


class FalhaInjetada(RuntimeError):
    """Test hook: crash after a named durable stage."""

    def __init__(self, etapa: str) -> None:
        super().__init__(etapa)
        self.etapa = etapa


class OperacaoRecusada(RuntimeError):
    """Recovery could not confirm the intended ids and would not guess."""


def injetar_falha_apos(etapa: str | None) -> None:
    global _FALHA_APOS
    _FALHA_APOS = etapa


def _talvez_falhar(etapa: str) -> None:
    if _FALHA_APOS == etapa:
        raise FalhaInjetada(etapa)


def _e_tabela_ausente(exc: BaseException) -> bool:
    texto = str(exc).lower()
    nome = type(exc).__name__.lower()
    marcas = ("not found", "does not exist", "no such", "notexist", "tablenotfound")
    return any(m in texto or m in nome for m in marcas)


def apagar_vetores_do_path(store: Store, path: str) -> None:
    """Delete dense rows for `path`. Missing table is a no-op; other errors raise."""
    tabela = _tabela_existente(store)
    if tabela is None:
        return
    escapado = path.replace("'", "''")
    tabela.delete(f"path = '{escapado}'")


def _tabela_existente(store: Store) -> Any:
    if store._tabela is not None:
        return store._tabela
    import lancedb

    lance = store.diretorio / "vetores.lance"
    if not lance.is_dir():
        return None
    try:
        db = lancedb.connect(str(lance))
        tabela = db.open_table(TABELA_VETORES)
    except Exception as exc:  # noqa: BLE001 — only absence is a no-op
        if _e_tabela_ausente(exc):
            return None
        raise
    store._db = db
    store._tabela = tabela
    return tabela


def _ids_sqlite(store: Store, path: str) -> set[str]:
    return {
        str(row[0])
        for row in store.con.execute("SELECT id FROM chunks WHERE path = ?", (path,))
    }


def _ids_lance(store: Store, path: str) -> set[str]:
    tabela = _tabela_existente(store)
    if tabela is None:
        return set()
    escapado = path.replace("'", "''")
    try:
        lote = tabela.search().where(f"path = '{escapado}'").select(["id"]).limit(10000).to_arrow()
    except Exception as exc:  # noqa: BLE001 — empty/missing table means no vectors
        if _e_tabela_ausente(exc):
            return set()
        raise
    return {str(i) for i in lote.column("id").to_pylist()}


def ha_pendentes(store: Store) -> bool:
    try:
        row = store.con.execute("SELECT 1 FROM operacoes LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _abrir(
    store: Store,
    *,
    path: str,
    tipo: str,
    chunks: Sequence[Chunk],
    model_id: str,
    mtime: float,
    documento: dict[str, Any],
) -> str:
    op_id = uuid4().hex
    agora_iso = agora()
    payload = {
        k: documento[k]
        for k in (
            "path",
            "raiz",
            "tamanho",
            "mtime",
            "sha256",
            "status",
            "n_chunks",
            "model_id",
            "chunker",
            "parser",
        )
        if k in documento
    }
    raiz = str(documento.get("raiz") or "")
    if raiz:
        from .ocorrencia import id_de

        payload["ocorrencia_id"] = id_de(raiz, path)
    store.con.execute(
        "INSERT INTO operacoes (id, path, tipo, etapa, model_id, chunk_ids, "
        "documento, mtime, criada_em, atualizada_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            op_id,
            path,
            tipo,
            "preparar",
            model_id,
            json.dumps([c.id for c in chunks], ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
            mtime,
            agora_iso,
            agora_iso,
        ),
    )
    store.con.commit()
    _talvez_falhar("preparar")
    return op_id


def _marcar(store: Store, op_id: str, etapa: str) -> None:
    store.con.execute(
        "UPDATE operacoes SET etapa = ?, atualizada_em = ? WHERE id = ?",
        (etapa, agora(), op_id),
    )
    store.con.commit()
    _talvez_falhar(etapa)


def _publicar(store: Store, op_id: str) -> None:
    store.con.execute("DELETE FROM operacoes WHERE id = ?", (op_id,))
    store.con.commit()
    _talvez_falhar("publicar")


def _deletar(store: Store, path: str, *, apagar_textos: bool) -> None:
    if apagar_textos:
        store.con.execute("DELETE FROM chunks WHERE path = ?", (path,))
        store.con.commit()
    apagar_vetores_do_path(store, path)


# Closed set of kwargs `registrar_documento` accepts. The journal payload may
# grow (FND-01b adds ocorrencia_id); extra keys must not crash recovery.
_CAMPOS_REGISTRO = (
    "path",
    "raiz",
    "tamanho",
    "mtime",
    "status",
    "sha256",
    "detalhe",
    "n_chunks",
    "model_id",
    "chunker",
    "parser",
    "natureza",
)


def _registrar(store: Store, documento: dict[str, Any]) -> None:
    store.registrar_documento(**{k: documento[k] for k in _CAMPOS_REGISTRO if k in documento})


def _completo(ids_sql: set[str], ids_lance: set[str], intended: set[str], tipo: str) -> bool:
    if ids_sql != intended:
        return False
    if tipo == "lexical":
        return True
    return ids_lance == intended


def _abortar(store: Store, path: str, tipo: str) -> None:
    if tipo != "vetores":
        store.con.execute("DELETE FROM chunks WHERE path = ?", (path,))
        store.con.execute("DELETE FROM documentos WHERE path = ?", (path,))
    else:
        store.con.execute("UPDATE documentos SET model_id = '' WHERE path = ?", (path,))
    store.con.commit()
    apagar_vetores_do_path(store, path)


def _verificar(store: Store, path: str, intended: set[str], tipo: str) -> None:
    ids_sql = _ids_sqlite(store, path)
    ids_lance = _ids_lance(store, path)
    if not _completo(ids_sql, ids_lance, intended, tipo):
        raise OperacaoRecusada(
            f"operação em {path} não reproduziu os ids pretendidos "
            f"(sqlite={len(ids_sql)} lance={len(ids_lance)} pretendidos={len(intended)})"
        )


def publicar_completo(
    store: Store,
    chunks: Sequence[Chunk],
    vetores: Sequence[np.ndarray],
    mtime: float,
    model_id: str,
    documento: dict[str, Any],
) -> str:
    path = str(documento["path"])
    op_id = _abrir(
        store, path=path, tipo="completo", chunks=chunks, model_id=model_id,
        mtime=mtime, documento=documento,
    )
    _deletar(store, path, apagar_textos=True)
    _marcar(store, op_id, "deletar")
    store.gravar_textos(chunks)
    store.con.commit()
    _marcar(store, op_id, "textos")
    store.gravar_vetores(chunks, vetores, mtime, model_id)
    _marcar(store, op_id, "vetores")
    _registrar(store, documento)
    store.con.commit()
    _marcar(store, op_id, "carimbo")
    _verificar(store, path, {c.id for c in chunks}, "completo")
    _marcar(store, op_id, "verificar")
    _publicar(store, op_id)
    return op_id


def publicar_lexical(
    store: Store,
    chunks: Sequence[Chunk],
    mtime: float,
    documento: dict[str, Any],
) -> str:
    path = str(documento["path"])
    op_id = _abrir(
        store, path=path, tipo="lexical", chunks=chunks, model_id="",
        mtime=mtime, documento=documento,
    )
    _deletar(store, path, apagar_textos=True)
    _marcar(store, op_id, "deletar")
    store.gravar_textos(chunks)
    store.con.commit()
    _marcar(store, op_id, "textos")
    _registrar(store, documento)
    store.con.commit()
    _marcar(store, op_id, "carimbo")
    _verificar(store, path, {c.id for c in chunks}, "lexical")
    _marcar(store, op_id, "verificar")
    _publicar(store, op_id)
    return op_id


def publicar_vetores(
    store: Store,
    chunks: Sequence[Chunk],
    vetores: Sequence[np.ndarray],
    mtime: float,
    model_id: str,
    path: str,
) -> str:
    documento = {"path": path, "model_id": model_id, "n_chunks": len(chunks)}
    op_id = _abrir(
        store, path=path, tipo="vetores", chunks=chunks, model_id=model_id,
        mtime=mtime, documento=documento,
    )
    _deletar(store, path, apagar_textos=False)
    _marcar(store, op_id, "deletar")
    store.gravar_vetores(chunks, vetores, mtime, model_id)
    _marcar(store, op_id, "vetores")
    store.carimbar_modelo(path, model_id)
    store.con.commit()
    _marcar(store, op_id, "carimbo")
    _verificar(store, path, {c.id for c in chunks}, "vetores")
    _marcar(store, op_id, "verificar")
    _publicar(store, op_id)
    return op_id


def _recuperar_uma(store: Store, row: sqlite3.Row) -> None:
    path = str(row["path"])
    tipo = str(row["tipo"])
    intended = set(json.loads(row["chunk_ids"]))
    ids_sql = _ids_sqlite(store, path)
    ids_lance = _ids_lance(store, path)
    if _completo(ids_sql, ids_lance, intended, tipo):
        documento = json.loads(row["documento"] or "{}")
        if tipo != "vetores" and documento.get("path"):
            _registrar(store, documento)
            store.con.commit()
        elif tipo == "vetores" and row["model_id"]:
            store.carimbar_modelo(path, str(row["model_id"]))
            store.con.commit()
        _verificar(store, path, intended, tipo)
        _publicar(store, str(row["id"]))
        return
    if str(row["etapa"]) == "preparar":
        _publicar(store, str(row["id"]))
        return
    log.warning("operação %s em %s abortada para reindexar (etapa %s)", row["id"], path, row["etapa"])
    _abortar(store, path, tipo)
    _publicar(store, str(row["id"]))


def recuperar_pendentes(store: Store) -> int:
    """Replay or abort every unfinished operation. Idempotent."""
    try:
        rows = list(store.con.execute("SELECT * FROM operacoes"))
    except sqlite3.OperationalError:
        return 0
    for row in rows:
        _recuperar_uma(store, row)
    return len(rows)


def recuperar_ao_abrir(store: Store) -> int:
    if not ha_pendentes(store):
        return 0
    try:
        with TravaDeIndice(store.diretorio):
            return recuperar_pendentes(store)
    except TravaOcupada:
        return 0


def abandonar_escrita(store: Store) -> None:
    """Simulate a process crash: uncommitted SQLite work is lost, Lance is not."""
    try:
        store.con.rollback()
    except sqlite3.Error:
        pass
    store.con.close()
    store._tabela = None
    store._db = None
