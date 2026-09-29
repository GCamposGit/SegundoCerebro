"""Leitura MCP paginada de células estruturadas sem abrir o original."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from segundocerebro.index.store import Store
from segundocerebro.mcp.server import Recursos, construir

SHA = "a" * 64
DOC_ID = SHA[:12]
ARQUIVO = "Planilhas/Producao.xlsx"


def _celulas(store: Store, sha: str, registros: list[tuple[str, int, str, str]]) -> None:
    store.con.executemany(
        "INSERT INTO planilha_celulas (sha256, aba, linha, coluna, valor) VALUES (?, ?, ?, ?, ?)",
        [(sha, *registro) for registro in registros],
    )


def _servidor(tmp_path: Path, *, base: object | None = None):
    store = Store(tmp_path / "indice", dim=8)
    store.registrar_documento(
        path=ARQUIVO,
        raiz="VCE",
        tamanho=0,
        mtime=1.0,
        status="ok",
        sha256=SHA,
        parser="xlsx:3",
        n_chunks=0,
    )
    _celulas(
        store,
        SHA,
        [
            ("Medições", 1, "A", "Data"),
            ("Medições", 1, "B", "Mês"),
            ("Medições", 1201, "V", "12345.67"),
            ("Notas", 1, "C", "Plantado"),
        ],
    )
    store.commit()
    recursos = Recursos(indice=store.diretorio, modelo="falso", threads=1, base=base)
    recursos._store = store
    return construir(recursos), store


def _chamar(servidor, **argumentos):
    return asyncio.run(servidor.call_tool("read_spreadsheet_cells", argumentos))


def _payload(servidor, **argumentos) -> dict:
    resultado = _chamar(servidor, **argumentos)
    assert not resultado.is_error, resultado.structured_content
    return resultado.structured_content


@pytest.fixture
def workbook(tmp_path: Path):
    servidor, store = _servidor(tmp_path)
    yield servidor, store
    store.fechar()


def test_le_celulas_exatas_em_paginas_com_arquivo_locator_e_cursor(workbook) -> None:
    servidor, store = workbook
    chunks_antes = store.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    primeira = _payload(
        servidor,
        documento=DOC_ID,
        aba="Medições",
        max_celulas=2,
    )

    assert primeira["arquivo"] == ARQUIVO
    assert primeira["aba"] == "Medições"
    assert primeira["total"] == 3
    assert primeira["mostrando"] == "1-2 de 3"
    assert primeira["restante"] == 1
    assert [celula["valor"] for celula in primeira["celulas"]] == ["Data", "Mês"]
    assert [celula["onde"] for celula in primeira["celulas"]] == ["Medições!A1", "Medições!B1"]
    assert primeira["cursor_proximo"]

    segunda = _payload(
        servidor,
        documento=DOC_ID,
        aba="Medições",
        cursor=primeira["cursor_proximo"],
        max_celulas=2,
    )

    assert segunda["celulas"] == [
        {
            "aba": "Medições",
            "linha": 1201,
            "coluna": "V",
            "valor": "12345.67",
            "onde": "Medições!V1201",
        }
    ]
    assert segunda["cursor_proximo"] is None
    assert segunda["completo"] is True
    assert store.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == chunks_antes


def test_limite_maximo_impede_devolver_a_aba_inteira(workbook) -> None:
    servidor, store = workbook
    _celulas(store, SHA, [("Medições", linha, "A", str(linha)) for linha in range(2, 222)])
    store.commit()

    pagina = _payload(servidor, documento=DOC_ID, aba="Medições", max_celulas=10000)

    assert len(pagina["celulas"]) == 200
    assert pagina["total"] == 223
    assert pagina["cursor_proximo"]
    assert pagina["completo"] is False


def test_cursor_nao_pode_ser_reutilizado_com_outra_aba_ou_documento(workbook) -> None:
    servidor, store = workbook
    primeira = _payload(servidor, documento=DOC_ID, aba="Medições", max_celulas=1)
    outra_aba = _chamar(
        servidor,
        documento=DOC_ID,
        aba="Notas",
        cursor=primeira["cursor_proximo"],
        max_celulas=1,
    )
    assert outra_aba.is_error
    assert outra_aba.structured_content["codigo"] == "cursor_contexto_divergente"

    outro_sha = "b" * 64
    store.registrar_documento(
        path="Planilhas/Outra.xlsx",
        raiz="VCE",
        tamanho=0,
        mtime=1.0,
        status="ok",
        sha256=outro_sha,
        parser="xlsx:3",
    )
    store.commit()
    outro_documento = _chamar(
        servidor,
        documento=outro_sha[:12],
        aba="Medições",
        cursor=primeira["cursor_proximo"],
        max_celulas=1,
    )
    assert outro_documento.is_error
    assert outro_documento.structured_content["codigo"] == "cursor_contexto_divergente"


def test_cursor_malformado_e_recusado_com_erro_de_entrada(workbook) -> None:
    servidor, _ = workbook

    resultado = _chamar(servidor, documento=DOC_ID, cursor="nao-e-um-cursor")

    assert resultado.is_error
    assert resultado.structured_content["codigo"] == "cursor_invalido"


def test_referencia_de_outra_base_e_recusada(workbook) -> None:
    servidor, _ = workbook
    resultado = _chamar(servidor, documento=f"sc://outra/{DOC_ID}")

    assert resultado.is_error
    assert resultado.structured_content["codigo"] == "referencia_invalida"


def test_planilha_sem_tabela_nao_abre_original_nem_finge_conteudo(workbook) -> None:
    servidor, store = workbook
    sem_tabela = "c" * 64
    store.registrar_documento(
        path="Planilhas/Pequena.xlsx",
        raiz="VCE",
        tamanho=0,
        mtime=1.0,
        status="ok",
        sha256=sem_tabela,
        parser="xlsx:3",
    )
    store.commit()

    saida = _payload(servidor, documento=sem_tabela[:12])

    assert saida["total"] == 0
    assert saida["celulas"] == []
    assert saida["aviso"] == "Nenhuma célula estruturada foi persistida para este documento."


def test_caminho_homonimo_exige_root_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", dim=8)
    for raiz, sha, valor in (("RaizA", "d" * 64, "A"), ("RaizB", "e" * 64, "B")):
        store.registrar_documento(
            path="Planilhas/Dados.xlsx",
            raiz=raiz,
            tamanho=0,
            mtime=1.0,
            status="ok",
            sha256=sha,
            parser="xlsx:3",
        )
        _celulas(store, sha, [("Dados", 1, "A", valor)])
    store.commit()
    recursos = Recursos(indice=store.diretorio, modelo="falso", threads=1)
    recursos._store = store
    servidor = construir(recursos)
    try:
        ambigua = _chamar(servidor, documento="Planilhas/Dados.xlsx")
        assert ambigua.is_error
        assert ambigua.structured_content["codigo"] == "caminho_ambiguo"

        resolvida = _payload(servidor, documento="Planilhas/Dados.xlsx", root_id="RaizB")
        assert resolvida["arquivo"] == "Planilhas/Dados.xlsx"
        assert resolvida["root_id"] == "RaizB"
        assert resolvida["celulas"][0]["valor"] == "B"
    finally:
        store.fechar()


def test_root_id_tambem_restringe_doc_id_em_colisao_de_prefixo(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", dim=8)
    sha_a = "f" * 12 + "a" * 52
    sha_b = "f" * 12 + "b" * 52
    for raiz, sha, valor in (("RaizA", sha_a, "A"), ("RaizB", sha_b, "B")):
        store.registrar_documento(
            path="Planilhas/Dados.xlsx",
            raiz=raiz,
            tamanho=0,
            mtime=1.0,
            status="ok",
            sha256=sha,
            parser="xlsx:3",
        )
        _celulas(store, sha, [("Dados", 1, "A", valor)])
    store.commit()
    recursos = Recursos(indice=store.diretorio, modelo="falso", threads=1)
    recursos._store = store
    servidor = construir(recursos)
    try:
        saida = _payload(servidor, documento=sha_a[:12], root_id="RaizB")

        assert saida["root_id"] == "RaizB"
        assert saida["celulas"][0]["valor"] == "B"
    finally:
        store.fechar()


def test_search_orienta_a_usar_a_leitura_de_celulas(workbook) -> None:
    servidor, _ = workbook
    ferramentas = {tool.name: tool for tool in asyncio.run(servidor.list_tools())}

    assert "read_spreadsheet_cells" in ferramentas["search"].description
    assert "cursor" in ferramentas["read_spreadsheet_cells"].description
