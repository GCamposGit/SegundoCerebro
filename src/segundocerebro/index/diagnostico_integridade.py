"""Fronteira somente leitura para o diagnóstico profundo FND-08a."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .diagnostico_relatorio import ItemDiagnostico
from .diagnostico_relatorio import item as _item
from .integridade import DiagnosticoIntegridade, diagnosticar_integridade

if TYPE_CHECKING:
    from .store import Store

Cancelar = Callable[[], bool]
Progresso = Callable[[int, int], None]


class _BancoSemTabelas:
    def list_tables(self) -> list[str]:
        return []


@dataclass
class _StoreLeitura:
    diretorio: Path
    con: sqlite3.Connection
    _db: Any
    _tabela: Any = None


@contextmanager
def _abrir_store(diretorio: Path) -> Iterator[_StoreLeitura]:
    registro = (diretorio / "registro.db").resolve()
    con = sqlite3.connect(registro.as_uri() + "?mode=ro", uri=True, timeout=0)
    con.execute("PRAGMA query_only=ON")
    vetores = diretorio / "vetores.lance"
    db: Any = _BancoSemTabelas()
    if vetores.is_dir():
        import lancedb

        db = lancedb.connect(str(vetores))
    try:
        yield _StoreLeitura(vetores, con, db)
    finally:
        con.close()


def _resultado(diag: DiagnosticoIntegridade) -> ItemDiagnostico:
    if diag.status == "cancelado":
        return _item(
            "integridade_cancelada",
            "aviso",
            "O diagnóstico profundo foi cancelado sem alterar o índice.",
            "Execute novamente quando puder aguardar a varredura completa.",
            escopo="integridade",
        )
    if diag.integro:
        return _item(
            "integridade_ok",
            "ok",
            f"SQLite e vetores estão íntegros ({diag.chunks_sqlite} chunks).",
            escopo="integridade",
            evidencia=diag.para_dict(),
        )
    codigo = (
        "integridade_indisponivel" if diag.status == "indisponivel" else "integridade_divergente"
    )
    return _item(
        codigo,
        "erro",
        f"Diagnóstico profundo não íntegro: {diag.detalhe or diag.status}.",
        "Pare a escrita e restaure ou reconstrua a base.",
        escopo="integridade",
        evidencia=diag.para_dict(),
    )


def conferir_integridade(
    diretorio: Path,
    lote: int,
    cancelar: Cancelar | None,
    progresso: Progresso | None,
) -> list[ItemDiagnostico]:
    if not (diretorio / "registro.db").is_file():
        return []
    try:
        with _abrir_store(diretorio) as leitor:
            diag = diagnosticar_integridade(
                cast("Store", leitor),
                lote=max(1, lote),
                cancelar=cancelar,
                progresso=progresso,
            )
        return [_resultado(diag)]
    except Exception as exc:  # noqa: BLE001 — I/O do store de leitura vira integridade indisponível
        return [
            _item(
                "integridade_indisponivel",
                "erro",
                f"Não foi possível concluir o diagnóstico profundo: {exc}",
                "Verifique a trava e a permissão do índice.",
                escopo="integridade",
                evidencia={"tipo_erro": type(exc).__name__},
            )
        ]
