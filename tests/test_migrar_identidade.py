"""FND-01b: migrar índice legado para pasta nova, original intacto."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from segundocerebro.census import Config, RootSpec
from segundocerebro.index.backup_manifesto import BackupRecusado
from segundocerebro.index.esquema import SCHEMA_VERSAO
from segundocerebro.index.indexer import indexar
from segundocerebro.index.migrar_identidade import MigracaoRecusada, migrar
from segundocerebro.index.ocorrencia import id_de, usa_ocorrencia
from segundocerebro.index.store import Store
from segundocerebro.index.trava import TravaDeIndice

from tests.falsos import DIM, EmbedderFalso
from tests.indice_legado import _legado


def _bytes_origem(indice: Path) -> bytes:
    return (indice / "registro.db").read_bytes()


def test_migrar_preserva_contagens_identidade_e_origem(tmp_path: Path) -> None:
    origem = _legado(tmp_path)
    antes = _bytes_origem(origem)
    destino = tmp_path / "novo"
    conferidas = migrar(origem, destino)

    assert conferidas["documentos"] == 2
    assert conferidas["chunks"] == 1
    assert conferidas["operacoes"] == 0
    assert _bytes_origem(origem) == antes
    assert (origem / "parse_store" / "aa" / "canon.zz").read_bytes() == b"cache"
    assert (destino / "parse_store" / "aa" / "canon.zz").read_bytes() == b"cache"

    store = Store(destino, DIM)
    try:
        assert usa_ocorrencia(store.con)
        versao = store.con.execute(
            "SELECT valor FROM meta WHERE chave = 'schema_versao'"
        ).fetchone()
        assert versao is not None and str(versao["valor"]) == SCHEMA_VERSAO
        oids = {
            str(r["path"]): str(r["ocorrencia_id"])
            for r in store.con.execute("SELECT path, root_id, ocorrencia_id FROM documentos")
        }
        assert oids["contrato.md"] == id_de("pessoal", "contrato.md")
        assert oids["ata.md"] == id_de("trabalho", "ata.md")
        hits = store.buscar_lexical("CT-VCE-2024-0142", 5)
        assert [h.id for h in hits] == ["c-vce-1"]
        campo = store.tabela.schema.field("vetor")
        assert getattr(campo.type, "list_size", None) == DIM
        vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
        densos = store.buscar_denso(vetor, 1)
        assert [h.id for h in densos] == ["c-vce-1"]
        raizes = {str(r[0]) for r in store.con.execute("SELECT root_id FROM raizes")}
        assert raizes == {"pessoal", "trabalho"}
    finally:
        store.fechar()


def test_migrar_recusa_journal_pendente(tmp_path: Path) -> None:
    origem = _legado(tmp_path)
    con = sqlite3.connect(origem / "registro.db")
    con.execute(
        "INSERT INTO operacoes (id, path, tipo, etapa, model_id, chunk_ids, "
        "documento, mtime, criada_em, atualizada_em) "
        "VALUES ('op1','contrato.md','completo','textos','','[]','{}',0,'t','t')"
    )
    con.commit()
    con.close()
    depois_do_journal = _bytes_origem(origem)
    destino = tmp_path / "novo"
    with pytest.raises(MigracaoRecusada) as exc:
        migrar(origem, destino)
    assert exc.value.codigo == "journal_pendente"
    assert not destino.exists()
    assert _bytes_origem(origem) == depois_do_journal


def test_migrar_recusa_indice_em_uso(tmp_path: Path) -> None:
    origem = _legado(tmp_path)
    destino = tmp_path / "novo"
    with TravaDeIndice(origem):
        with pytest.raises(BackupRecusado) as exc:
            migrar(origem, destino)
    assert exc.value.codigo == "escritor_ativo"
    assert not destino.exists()


def test_migrar_recusa_ja_migrado(tmp_path: Path) -> None:
    origem = tmp_path / "v2"
    store = Store(origem, DIM)
    store.registrar_documento(
        path="contrato.md", raiz="pessoal", tamanho=1, mtime=1.0, status="ok",
    )
    store.commit()
    store.fechar()
    with pytest.raises(MigracaoRecusada) as exc:
        migrar(origem, tmp_path / "novo")
    assert exc.value.codigo == "ja_migrado"


def test_migrar_interrompida_nao_publica(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origem = _legado(tmp_path)
    antes = _bytes_origem(origem)
    destino = tmp_path / "novo"

    def quebrar(_registro: Path) -> None:
        raise RuntimeError("falha injetada após copiar")

    monkeypatch.setattr(
        "segundocerebro.index.migrar_identidade._transformar",
        quebrar,
    )
    with pytest.raises(RuntimeError, match="falha injetada"):
        migrar(origem, destino)
    assert not destino.exists()
    assert _bytes_origem(origem) == antes


def test_indexar_aceita_homonimos_depois_do_schema_novo(tmp_path: Path) -> None:
    raiz_a = tmp_path / "pessoal"
    raiz_b = tmp_path / "trabalho"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "contrato.md").write_text("Contrato da oficina da VCE, cláusula 1.", encoding="utf-8")
    (raiz_b / "contrato.md").write_text("Contrato do escritório da VCE, cláusula 9.", encoding="utf-8")
    cfg = Config(roots=[RootSpec(name="pessoal", path=raiz_a), RootSpec(name="trabalho", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)
    assert usa_ocorrencia(store.con)
    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    assert progresso.indexados == 2
    assert store.estatisticas()["documentos"] == 2
    assert {
        str(row["root_id"])
        for row in store.con.execute("SELECT root_id FROM documentos WHERE path = 'contrato.md'")
    } == {"pessoal", "trabalho"}
    store.fechar()
