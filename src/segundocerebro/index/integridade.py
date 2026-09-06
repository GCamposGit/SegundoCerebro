"""Diagnóstico e verificação de integridade entre SQLite e LanceDB (FND-02a).

Compara os IDs reais persistidos no SQLite contra a tabela de vetores do LanceDB
em lotes, identificando vetores órfãos, chunks sem embedding, vetores duplicados
ou inconsistência de modelos. Separa a pendência legítima do passe 1 (rascunho
lexical) de corrupção real do índice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Store

TABELA_VETORES = "chunks"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiagnosticoIntegridade:
    """Resultado do diagnóstico de integridade entre SQLite e LanceDB."""

    integro: bool
    status: str
    chunks_sqlite: int
    vetores_lancedb: int
    orfaos: int
    faltantes: int
    duplicados: int
    modelos_divergentes: int
    pendentes_rascunho: int
    lancedb_disponivel: bool
    detalhe: str = ""
    ids_orfaos: tuple[str, ...] = ()
    ids_faltantes: tuple[str, ...] = ()
    ids_duplicados: tuple[str, ...] = ()

    def para_dict(self) -> dict[str, Any]:
        """Formato de compatibilidade preservando chaves legadas e novos campos."""
        vetores = self.vetores_lancedb if self.lancedb_disponivel else -1
        diferenca = (self.vetores_lancedb - self.chunks_sqlite) if self.lancedb_disponivel else -1
        return {
            "chunks": self.chunks_sqlite,
            "vetores": vetores,
            "diferenca": diferenca,
            "integro": self.integro,
            "status": self.status,
            "orfaos": self.orfaos,
            "faltantes": self.faltantes,
            "duplicados": self.duplicados,
            "modelos_divergentes": self.modelos_divergentes,
            "pendentes_rascunho": self.pendentes_rascunho,
            "lancedb_disponivel": self.lancedb_disponivel,
            "detalhe": self.detalhe,
        }


def _coletar_sqlite(store: Store) -> dict[str, str]:
    """Retorna mapa de id -> model_id para todos os chunks registrados no SQLite."""
    consulta = (
        "SELECT c.id, COALESCE(d.model_id, '') "
        "FROM chunks c LEFT JOIN documentos d ON c.path = d.path"
    )
    return {row[0]: row[1] for row in store.con.execute(consulta).fetchall()}


def _tabelas_no_db(db: Any) -> list[str]:
    """Descobre tabelas existentes no LanceDB de forma compatível."""
    try:
        res = db.list_tables()
        if hasattr(res, "tables"):
            return list(res.tables)
        if isinstance(res, list):
            return res
    except Exception:  # noqa: BLE001
        pass
    try:
        return db.table_names()
    except Exception:  # noqa: BLE001
        return []


def _escanear_vetores(
    tbl: Any,
    sqlite_map: dict[str, str],
    lote: int,
) -> tuple[set[str], set[str], set[str], int]:
    """Varre a tabela LanceDB em lotes sem carregar a coluna vetorial pesada."""
    vistos: set[str] = set()
    duplicados: set[str] = set()
    orfaos: set[str] = set()
    modelos_divergentes = 0
    total = tbl.count_rows()

    for offset in range(0, total, lote):
        lim = min(lote, total - offset)
        lote_arrow = (
            tbl.search()
            .select(["id", "model_id"])
            .offset(offset)
            .limit(lim)
            .to_arrow()
        )
        b_ids: list[str] = lote_arrow.column("id").to_pylist()
        b_models: list[str] = lote_arrow.column("model_id").to_pylist()

        for vid, vmodel in zip(b_ids, b_models, strict=False):
            if vid in vistos:
                duplicados.add(vid)
            vistos.add(vid)

            if vid not in sqlite_map:
                orfaos.add(vid)
            else:
                sq_model = sqlite_map[vid]
                if sq_model and vmodel and sq_model != vmodel:
                    modelos_divergentes += 1

    return vistos, duplicados, orfaos, modelos_divergentes


def _avaliar_sem_tabela(sqlite_map: dict[str, str]) -> DiagnosticoIntegridade:
    """Diagnóstico quando o LanceDB não tem tabela chunks ainda."""
    total_chunks = len(sqlite_map)
    if total_chunks == 0:
        return DiagnosticoIntegridade(
            integro=True,
            status="vazio",
            chunks_sqlite=0,
            vetores_lancedb=0,
            orfaos=0,
            faltantes=0,
            duplicados=0,
            modelos_divergentes=0,
            pendentes_rascunho=0,
            lancedb_disponivel=True,
        )

    pendentes = sum(1 for m in sqlite_map.values() if not m)
    faltantes = total_chunks - pendentes
    integro = faltantes == 0
    status = "rascunho_pendente" if integro else "divergente"

    return DiagnosticoIntegridade(
        integro=integro,
        status=status,
        chunks_sqlite=total_chunks,
        vetores_lancedb=0,
        orfaos=0,
        faltantes=faltantes,
        duplicados=0,
        modelos_divergentes=0,
        pendentes_rascunho=pendentes,
        lancedb_disponivel=True,
        detalhe="Tabela de vetores ainda não criada no LanceDB",
    )


def _abrir_tabela(store: Store) -> tuple[Any | None, str | None]:
    """Abre a tabela do LanceDB se existir; retorna (tabela, erro)."""
    import lancedb

    if store._tabela is not None:
        return store._tabela, None
    try:
        db = store._db if store._db is not None else lancedb.connect(store.diretorio)
        tabelas = _tabelas_no_db(db)
        if TABELA_VETORES not in tabelas:
            return None, None
        return db.open_table(TABELA_VETORES), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _apurar_faltantes(
    sqlite_map: dict[str, str],
    vistos: set[str],
) -> tuple[set[str], int]:
    """Calcula chunks do SQLite ausentes do LanceDB e pendentes do passe 1."""
    faltantes_set: set[str] = set()
    pendentes_rascunho = 0
    for cid, cmodel in sqlite_map.items():
        if cid not in vistos:
            if not cmodel:
                pendentes_rascunho += 1
            else:
                faltantes_set.add(cid)
    return faltantes_set, pendentes_rascunho


def _determinar_status(
    integro: bool,
    pendentes_rascunho: int,
    total_chunks: int,
    total_vetores: int,
) -> str:
    """Classifica o status operacional da integridade."""
    if not integro:
        return "divergente"
    if pendentes_rascunho > 0:
        return "rascunho_pendente"
    if total_chunks == 0 and total_vetores == 0:
        return "vazio"
    return "ok"


def diagnosticar_integridade(store: Store, lote: int = 1000) -> DiagnosticoIntegridade:
    """Executa diagnóstico somente-leitura e paginado de integridade entre stores."""
    try:
        sqlite_map = _coletar_sqlite(store)
    except Exception as exc:  # noqa: BLE001
        return DiagnosticoIntegridade(
            integro=False, status="indisponivel", chunks_sqlite=0, vetores_lancedb=0,
            orfaos=0, faltantes=0, duplicados=0, modelos_divergentes=0, pendentes_rascunho=0,
            lancedb_disponivel=False, detalhe=f"Falha ao ler SQLite: {exc}",
        )

    tbl, erro_lancedb = _abrir_tabela(store)
    if erro_lancedb:
        return DiagnosticoIntegridade(
            integro=False, status="indisponivel", chunks_sqlite=len(sqlite_map), vetores_lancedb=-1,
            orfaos=0, faltantes=0, duplicados=0, modelos_divergentes=0, pendentes_rascunho=0,
            lancedb_disponivel=False, detalhe=f"Falha ao acessar LanceDB: {erro_lancedb}",
        )
    if tbl is None:
        return _avaliar_sem_tabela(sqlite_map)

    try:
        vistos, duplicados, orfaos, mod_div = _escanear_vetores(tbl, sqlite_map, max(1, lote))
    except Exception as exc:  # noqa: BLE001
        return DiagnosticoIntegridade(
            integro=False, status="indisponivel", chunks_sqlite=len(sqlite_map), vetores_lancedb=-1,
            orfaos=0, faltantes=0, duplicados=0, modelos_divergentes=0, pendentes_rascunho=0,
            lancedb_disponivel=False, detalhe=f"Falha ao escanear LanceDB: {exc}",
        )

    faltantes_set, pendentes = _apurar_faltantes(sqlite_map, vistos)
    integro = not (orfaos or faltantes_set or duplicados or mod_div)
    status = _determinar_status(integro, pendentes, len(sqlite_map), tbl.count_rows())

    return DiagnosticoIntegridade(
        integro=integro, status=status, chunks_sqlite=len(sqlite_map),
        vetores_lancedb=tbl.count_rows(), orfaos=len(orfaos), faltantes=len(faltantes_set),
        duplicados=len(duplicados), modelos_divergentes=mod_div, pendentes_rascunho=pendentes,
        lancedb_disponivel=True, ids_orfaos=tuple(sorted(orfaos)[:50]),
        ids_faltantes=tuple(sorted(faltantes_set)[:50]), ids_duplicados=tuple(sorted(duplicados)[:50]),
    )


def verificar_consistencia(store: Store) -> dict[str, Any]:
    """Compara integridade entre SQLite e LanceDB por identidade."""
    return diagnosticar_integridade(store).para_dict()
