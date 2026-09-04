"""R4.2: orçamento e manutenção do FTS5 são automáticos."""

from __future__ import annotations

from segundocerebro.index.fts import politica_sqlite
from segundocerebro.index.store import Store
from tests.falsos import chunk


def test_orcamento_sqlite_encolhe_e_tem_teto() -> None:
    apertado = politica_sqlite(512)
    folgado = politica_sqlite(64 * 1024)

    assert (apertado.cache_mb, apertado.mmap_mb) == (32, 128)
    assert (folgado.cache_mb, folgado.mmap_mb) == (256, 1024)


def test_registro_novo_nasce_com_vacuum_incremental_e_pragmas(tmp_path) -> None:  # noqa: ANN001
    store = Store(tmp_path / "indice", 8)
    try:
        assert store.con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        assert store.con.execute("PRAGMA cache_size").fetchone()[0] < 0
        assert store.con.execute("PRAGMA mmap_size").fetchone()[0] > 0
    finally:
        store.fechar()


def test_otimizar_fts_preserva_resultado_e_integridade(tmp_path) -> None:  # noqa: ANN001
    store = Store(tmp_path / "indice", 8)
    try:
        store.gravar_textos(
            [
                chunk("c1", "contrato.md", 0, "reajuste anual do contrato"),
                chunk("c2", "ata.md", 0, "assunto sem relação"),
            ]
        )
        store.commit()
        antes = [a.id for a in store.buscar_lexical("reajuste contrato", 5)]

        assert store.otimizar_fts() is True

        depois = [a.id for a in store.buscar_lexical("reajuste contrato", 5)]
        assert depois == antes == ["c1"]
        assert store.con.execute(
            "INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')"
        ).fetchone() is None
    finally:
        store.fechar()
