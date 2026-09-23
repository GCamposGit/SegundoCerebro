"""R4.2: orçamento e manutenção do FTS5 são automáticos."""

from __future__ import annotations

from segundocerebro.index import fts
from segundocerebro.index.fts import consulta_fts, consulta_fts_seletiva, politica_sqlite
from segundocerebro.index.store import Store
from tests.falsos import chunk


def test_mmap_windows_tem_teto_de_128_mib(monkeypatch) -> None:
    comandos: list[str] = []

    class ConexaoFake:
        def execute(self, comando: str):
            comandos.append(comando)

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(fts.sys, "platform", "win32")
    monkeypatch.setattr(fts, "_ram_livre_mb", lambda: 64 * 1024)

    fts.configurar_sqlite(ConexaoFake(), novo=False)  # type: ignore[arg-type]

    assert "PRAGMA mmap_size=134217728" in comandos


def test_mmap_ci_desliga_mapeamento_mesmo_com_ram_alta(monkeypatch) -> None:
    comandos: list[str] = []

    class ConexaoFake:
        def execute(self, comando: str):
            comandos.append(comando)

    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(fts.sys, "platform", "win32")
    monkeypatch.setattr(fts, "_ram_livre_mb", lambda: 64 * 1024)

    aplicada = fts.configurar_sqlite(ConexaoFake(), novo=False)  # type: ignore[arg-type]

    assert aplicada.mmap_mb == 0
    assert "PRAGMA mmap_size=0" in comandos
    assert "PRAGMA mmap_size=134217728" not in comandos


def test_ci_desliga_mmap_sem_depender_da_sonda_de_ram(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")

    assert fts.ambiente_de_ci() is True
    assert fts.mmap_aplicado_mb(politica_sqlite(64 * 1024), plataforma="win32") == 0
    assert fts.mmap_aplicado_mb(politica_sqlite(0), plataforma="linux") == 0
    assert fts._ram_livre_mb() == 0


def test_orcamento_sqlite_encolhe_e_tem_teto() -> None:
    apertado = politica_sqlite(512)
    folgado = politica_sqlite(64 * 1024)

    assert (apertado.cache_mb, apertado.mmap_mb) == (32, 128)
    assert (folgado.cache_mb, folgado.mmap_mb) == (256, 1024)


def test_registro_novo_nasce_com_vacuum_incremental_e_pragmas(tmp_path) -> None:
    store = Store(tmp_path / "indice", 8)
    try:
        assert store.con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        assert store.con.execute("PRAGMA cache_size").fetchone()[0] < 0
        mmap = store.con.execute("PRAGMA mmap_size").fetchone()[0]
        if fts.ambiente_de_ci():
            assert mmap == 0
        else:
            assert mmap > 0
    finally:
        store.fechar()


def test_otimizar_fts_preserva_resultado_e_integridade(tmp_path) -> None:
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


def test_busca_adia_hidratacao_sem_mudar_ranking(tmp_path) -> None:
    """O top-k sem o JOIN precoce é idêntico ao SQL antigo, inclusive scores."""
    store = Store(tmp_path / "indice", 8)
    try:
        store.gravar_textos(
            [
                chunk("c1", "contrato.md", 0, "reajuste anual do contrato"),
                chunk("c2", "ata.md", 0, "reajuste semestral"),
                chunk("c3", "anexo.md", 0, "contrato sem relação"),
            ]
        )
        store.commit()
        expressao = consulta_fts("reajuste contrato")
        referencia = store.con.execute(
            """
            SELECT c.id, bm25(chunks_fts) AS score
            FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (expressao, 3),
        ).fetchall()

        obtido = store.buscar_lexical("reajuste contrato", 3)

        assert [(a.id, -a.score) for a in obtido] == [
            (linha["id"], linha["score"]) for linha in referencia
        ]
    finally:
        store.fechar()


def test_consulta_poda_so_termo_no_piso_de_idf_e_tem_fallback(tmp_path) -> None:
    store = Store(tmp_path / "indice", 8)
    try:
        store.gravar_textos(
            [
                chunk("c1", "contrato.md", 0, "de contrato"),
                chunk("c2", "dois.md", 0, "de ata"),
                chunk("c3", "tres.md", 0, "de pauta"),
                chunk("c4", "quatro.md", 0, "de norma"),
                chunk("c5", "cinco.md", 0, "relatório"),
            ]
        )
        store.commit()

        assert consulta_fts_seletiva(store.con, "de contrato") == '"contrato"'
        assert consulta_fts_seletiva(store.con, "de") == '"de"'
        assert consulta_fts_seletiva(store.con, "de PO-ACME-007") == '"PO-ACME-007"'
        assert [a.id for a in store.buscar_lexical("de contrato", 5)] == ["c1"]
        assert len(store.buscar_lexical("de contrato", 5, podar_ubiquos=False)) == 4
    finally:
        store.fechar()
