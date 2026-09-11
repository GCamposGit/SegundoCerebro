"""FND-01b: ocorrência interna por raiz e caminho, sem trocar o doc_id público."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from segundocerebro.index.esquema import ESQUEMA_DOCUMENTOS_V1, SCHEMA_VERSAO
from segundocerebro.index.ocorrencia import (
    CaminhoRelativoInvalido,
    caminho_rel,
    id_de,
    usa_ocorrencia,
)
from segundocerebro.index.store import Store

from tests.falsos import DIM


def test_id_e_deterministico_e_ignora_letra_de_disco() -> None:
    a = id_de("pessoal", "contrato.md")
    b = id_de("pessoal", "contrato.md")
    c = id_de("trabalho", "contrato.md")
    assert a == b
    assert a != c
    assert len(a) == 16
    assert id_de("pessoal", "atas/2024/x.pdf") == id_de("pessoal", r"atas\2024\x.pdf")


def test_caminho_rel_recusa_absoluto_e_parent() -> None:
    with pytest.raises(CaminhoRelativoInvalido):
        caminho_rel("C:/acervo/contrato.md")
    with pytest.raises(CaminhoRelativoInvalido):
        caminho_rel("../contrato.md")
    with pytest.raises(CaminhoRelativoInvalido):
        caminho_rel("/contrato.md")
    with pytest.raises(ValueError):
        id_de("", "contrato.md")


def test_dois_homonimos_coexistem_e_mesma_ocorrencia_atualiza(store: Store) -> None:
    store.registrar_documento(
        path="contrato.md", raiz="pessoal", tamanho=10, mtime=1.0,
        sha256="a" * 64, status="ok",
    )
    store.registrar_documento(
        path="contrato.md", raiz="trabalho", tamanho=20, mtime=2.0,
        sha256="b" * 64, status="ok",
    )
    store.registrar_documento(
        path="contrato.md", raiz="pessoal", tamanho=11, mtime=3.0,
        sha256="a" * 64, status="ok",
    )
    store.commit()
    assert store.estatisticas()["documentos"] == 2
    linhas = list(store.con.execute(
        "SELECT root_id, path, ocorrencia_id, tamanho FROM documentos ORDER BY root_id"
    ))
    assert [str(r["root_id"]) for r in linhas] == ["pessoal", "trabalho"]
    assert {str(r["ocorrencia_id"]) for r in linhas} == {
        id_de("pessoal", "contrato.md"),
        id_de("trabalho", "contrato.md"),
    }
    tamanho_pessoal = next(int(r["tamanho"]) for r in linhas if r["root_id"] == "pessoal")
    assert tamanho_pessoal == 11
    versao = store.con.execute(
        "SELECT valor FROM meta WHERE chave = 'schema_versao'"
    ).fetchone()
    assert versao is not None and str(versao["valor"]) == SCHEMA_VERSAO
    assert usa_ocorrencia(store.con)


def test_mesmo_conteudo_em_duas_raizes_sao_duas_ocorrencias(store: Store) -> None:
    hash_comum = "ab" * 32
    store.registrar_documento(
        path="contrato.md", raiz="pessoal", tamanho=8, mtime=1.0,
        sha256=hash_comum, status="ok",
    )
    store.registrar_documento(
        path="contrato.md", raiz="trabalho", tamanho=8, mtime=1.0,
        sha256=hash_comum, status="ok",
    )
    store.commit()
    n = store.con.execute("SELECT count(*) FROM documentos").fetchone()[0]
    ids = {str(r[0]) for r in store.con.execute("SELECT ocorrencia_id FROM documentos")}
    hashes = {str(r[0]) for r in store.con.execute("SELECT sha256 FROM documentos")}
    assert n == 2
    assert len(ids) == 2
    assert hashes == {hash_comum}


def test_indice_legado_ainda_sobrescreve_por_path(tmp_path: Path) -> None:
    """O PK antigo é a razão da recusa 01a; a migração é que troca a chave."""
    indice = tmp_path / "legado"
    indice.mkdir()
    con = sqlite3.connect(indice / "registro.db")
    con.executescript(ESQUEMA_DOCUMENTOS_V1)
    con.close()
    store = Store(indice, DIM)
    assert not usa_ocorrencia(store.con)
    store.registrar_documento(
        path="contrato.md", raiz="raiz_a", tamanho=1, mtime=1.0, status="ok",
    )
    store.registrar_documento(
        path="contrato.md", raiz="raiz_b", tamanho=2, mtime=2.0, status="ok",
    )
    store.commit()
    assert store.estatisticas()["documentos"] == 1
    raiz = store.con.execute("SELECT raiz FROM documentos WHERE path = 'contrato.md'").fetchone()[0]
    assert raiz == "raiz_b"
    store.fechar()
