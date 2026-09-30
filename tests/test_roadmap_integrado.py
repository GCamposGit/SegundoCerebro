"""Fluxo sintético de indexação e leitura MCP de uma planilha grande."""

from __future__ import annotations

import asyncio
import hashlib
import io

import numpy as np
import openpyxl

from segundocerebro.index.operacoes import publicar_completo
from segundocerebro.index.ocorrencia import id_de
from segundocerebro.index.store import Store
from segundocerebro.ingest.chunking import chunk_document
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.ingest.parsers.sheets import parse_xlsx
from segundocerebro.mcp.server import Recursos, construir
from tests.falsos import EmbedderFalso


def _planilha_de_producao() -> bytes:
    livro = openpyxl.Workbook()
    aba = livro.active
    aba.title = "Medições"
    aba.append([*(f"Campo {coluna}" for coluna in range(1, 22)), "Medida"])
    for linha in range(1200):
        valores = [f"VCE-{coluna}-{linha % 7}" for coluna in range(1, 22)]
        valores.append(12345.67 if linha == 1199 else float(linha) + 0.5)
        aba.append(valores)
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def test_planilha_grande_vai_da_extracao_ao_cursor_mcp(tmp_path, monkeypatch) -> None:
    """Simula localizar uma medição no workbook sem devolver a aba inteira."""
    path = "Planilhas/producao.xlsx"
    bruto = _planilha_de_producao()
    documento = parse_xlsx(bruto, "producao.xlsx")
    assert len(documento.linhas_planilha) == 1201
    assert documento.linhas_planilha[-1].valores[21] == "12345.67"

    emb = EmbedderFalso()
    ocorrencia = id_de("VCE", path)
    chunks = chunk_document(documento, path, ocorrencia_id=ocorrencia, root_id="VCE")
    vetores: list[np.ndarray] = [np.ones(emb.dim, dtype=np.float32) for _ in chunks]
    ids = {chunk.id for chunk in chunks}
    monkeypatch.setattr("segundocerebro.index.operacoes.apagar_vetores_do_path", lambda *_a, **_k: None)
    monkeypatch.setattr(Store, "gravar_vetores", lambda *_a, **_k: None)
    monkeypatch.setattr("segundocerebro.index.operacoes._ids_lance", lambda *_a, **_k: ids)

    indice = tmp_path / "indice"
    store = Store(indice, emb.dim)
    try:
        publicar_completo(
            store,
            chunks,
            vetores,
            1.0,
            emb.model_id,
            {
                "path": path,
                "raiz": "VCE",
                "root_id": "VCE",
                "ocorrencia_id": ocorrencia,
                "tamanho": len(bruto),
                "mtime": 1.0,
                "sha256": hashlib.sha256(bruto).hexdigest(),
                "status": "ok",
                "n_chunks": len(chunks),
                "model_id": emb.model_id,
                "chunker": "2",
                "parser": parser_version_for(".xlsx"),
                "linhas_planilha": documento.linhas_planilha,
            },
        )
        assert store.con.execute(
            "SELECT valor FROM planilha_celulas WHERE linha = 1201 AND coluna = 'V'"
        ).fetchone()[0] == "12345.67"

        recursos = Recursos(indice=indice, modelo="falso", threads=1)
        recursos._store = store
        servidor = construir(recursos)
        primeira = asyncio.run(
            servidor.call_tool(
                "read_spreadsheet_cells",
                {"documento": hashlib.sha256(bruto).hexdigest()[:12], "aba": "Medições", "max_celulas": 2},
            )
        )
        assert not primeira.is_error
        pagina_1 = primeira.structured_content
        assert pagina_1["total"] == 1201 * 22
        assert [celula["onde"] for celula in pagina_1["celulas"]] == [
            "Medições!A1",
            "Medições!B1",
        ]
        assert pagina_1["cursor_proximo"]

        segunda = asyncio.run(
            servidor.call_tool(
                "read_spreadsheet_cells",
                {
                    "documento": hashlib.sha256(bruto).hexdigest()[:12],
                    "aba": "Medições",
                    "cursor": pagina_1["cursor_proximo"],
                    "max_celulas": 2,
                },
            )
        )
        assert not segunda.is_error
        assert [celula["onde"] for celula in segunda.structured_content["celulas"]] == [
            "Medições!C1",
            "Medições!D1",
        ]
        assert segunda.structured_content["cursor_proximo"]
        assert store.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == len(chunks)
    finally:
        store.fechar()
