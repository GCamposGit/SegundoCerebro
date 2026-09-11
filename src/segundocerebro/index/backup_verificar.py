"""Integridade e consulta sintética sobre uma cópia já materializada."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .backup_manifesto import BackupInconsistente, LANCEDB_SEM_SNAPSHOT
from .backup_io import limpar_wal
from .store import TABELA_VETORES, Store


def descobrir_dim(diretorio: Path) -> int | None:
    lance = diretorio / "vetores.lance"
    if not lance.is_dir():
        return None
    import lancedb

    db = lancedb.connect(str(lance))
    try:
        tabela = db.open_table(TABELA_VETORES)
        campo = tabela.schema.field("vetor")
        dim = getattr(campo.type, "list_size", None)
        return int(dim) if dim else None
    except Exception as exc:  # noqa: BLE001 — tabela ausente ou esquema ilegível
        raise BackupInconsistente(
            "Não foi possível ler a tabela de vetores do backup.",
            "lancedb_ilegivel",
            "Gere o backup de novo com a indexação parada.",
        ) from exc
    finally:
        db = None


def _anexar_tabela(store: Store) -> dict[str, Any]:
    import lancedb

    lance = store.diretorio / "vetores.lance"
    if not lance.is_dir():
        return {"presente": False}
    store._db = lancedb.connect(str(lance))
    store._tabela = store._db.open_table(TABELA_VETORES)
    tabela = store._tabela
    dim = getattr(tabela.schema.field("vetor").type, "list_size", None)
    return {
        "presente": True,
        "versao_tabela": int(tabela.version),
        "linhas": int(tabela.count_rows()),
        "dim": int(dim) if dim else None,
        "lancedb": LANCEDB_SEM_SNAPSHOT,
    }


def _consulta_sintetica(store: Store) -> dict[str, Any]:
    linha = store.con.execute(
        "SELECT id, texto FROM chunks WHERE texto != '' LIMIT 1"
    ).fetchone()
    if linha is None:
        return {"reproduzido": True, "motivo": "sem_chunks"}
    alvo = str(linha["id"])
    trecho = str(linha["texto"]).split()[:8]
    consulta = " ".join(trecho) if trecho else alvo
    hits = store.buscar_lexical(consulta, 8)
    ids = [h.id for h in hits]
    if alvo not in ids:
        raise BackupInconsistente(
            "A consulta sintética não reproduziu o identificador do trecho.",
            "consulta_divergente",
            "Não use este backup; o índice original permanece intacto.",
        )
    return {"reproduzido": True, "id": alvo}


def verificar_copia(diretorio: Path) -> dict[str, Any]:
    """Open the copy, check identity integrity, run a lexical probe, checkpoint."""
    dim = descobrir_dim(diretorio) or 8
    store = Store(diretorio, dim)
    try:
        lance = _anexar_tabela(store)
        stats = store.estatisticas()
        integridade: dict[str, Any]
        if lance.get("presente"):
            diag = store.diagnosticar_integridade()
            integridade = diag.para_dict()
            if not diag.integro and diag.status not in {"vazio", "rascunho_pendente"}:
                raise BackupInconsistente(
                    f"A cópia não está íntegra ({diag.status}).",
                    "integridade_divergente",
                    "Corrija o índice de origem e gere o backup de novo.",
                )
        else:
            integridade = {"integro": True, "status": "sem_vetores", "lancedb_disponivel": False}
        consulta = _consulta_sintetica(store)
        model_id = ""
        modelos = stats.get("modelos")
        if isinstance(modelos, list) and modelos:
            model_id = str(modelos[0])
        store.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {
            "contagens": {
                "documentos": int(stats["documentos"]),
                "chunks": int(stats["chunks"]),
                "vetores": int(lance["linhas"]) if lance.get("presente") else 0,
            },
            "schema": {"model_id": model_id, "dim": lance.get("dim") or dim},
            "integridade": integridade,
            "consulta": consulta,
            "lance": lance,
        }
    finally:
        store.fechar()
        limpar_wal(diretorio)
