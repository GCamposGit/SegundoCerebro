from __future__ import annotations

import io
from hashlib import sha256

import numpy as np

from segundocerebro.index.operacoes import publicar_completo
from segundocerebro.index.store import Store
from segundocerebro.ingest.parsers.sheets import parse_xlsx
from tests.falsos import DIM, chunk


def _xlsx(linhas: int, colunas: int = 22) -> bytes:
    import openpyxl

    livro = openpyxl.Workbook()
    aba = livro.active
    aba.title = "Medições"
    aba.append([*(f"Chave {c}" for c in range(colunas - 1)), "Medida"])
    for linha in range(linhas):
        valores = [f"grupo-{coluna}-{linha % 3}" for coluna in range(colunas - 1)]
        valores.append(12345.67 if linha == linhas - 1 else float(linha) + 0.5)
        aba.append(valores)
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def test_aba_grande_preserva_celulas_sem_aumentar_blocos() -> None:
    dados = _xlsx(1200)
    doc = parse_xlsx(dados, "medicoes.xlsx")

    assert len(doc.blocks) == 5
    celula = next(linha for linha in doc.linhas_planilha if linha.linha == 1201)
    assert celula.aba == "Medições"
    assert celula.valores[21] == "12345.67"


def test_indexacao_persiste_celulas_fora_dos_chunks_e_nao_apaga_original(tmp_path, monkeypatch) -> None:
    dados = _xlsx(1200)
    origem = tmp_path / "medicoes.xlsx"
    origem.write_bytes(dados)
    doc = parse_xlsx(dados, origem.name)
    digest = sha256(dados).hexdigest()
    store = Store(tmp_path / "indice", DIM)
    chunks = [chunk(f"digest-{n}", origem.name, n, bloco.text) for n, bloco in enumerate(doc.blocks)]
    ids = {registro.id for registro in chunks}
    monkeypatch.setattr("segundocerebro.index.operacoes.apagar_vetores_do_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(Store, "gravar_vetores", lambda self, *args, **kwargs: None)
    monkeypatch.setattr("segundocerebro.index.operacoes._ids_lance", lambda *args, **kwargs: ids)
    publicar_completo(
        store,
        chunks,
        [np.ones(DIM, dtype=np.float32) for _ in chunks],
        1.0,
        "falso:8",
        {
            "path": origem.name,
            "raiz": "sintetica",
            "tamanho": len(dados),
            "mtime": 1.0,
            "sha256": digest,
            "status": "ok",
            "n_chunks": len(chunks),
            "model_id": "falso:8",
            "chunker": "2",
            "parser": "xlsx:3",
            "linhas_planilha": doc.linhas_planilha,
        },
    )

    celula = store.con.execute(
        "SELECT aba, linha, coluna, valor FROM planilha_celulas "
        "WHERE sha256 = ? AND linha = 1201 AND coluna = 'V'",
        (digest,),
    ).fetchone()
    assert tuple(celula) == ("Medições", 1201, "V", "12345.67")
    assert store.con.execute(
        "SELECT count(*) FROM planilha_celulas WHERE sha256 = ?", (digest,)
    ).fetchone()[0] == 1201 * 22
    assert store.con.execute("SELECT count(*) FROM chunks").fetchone()[0] == len(doc.blocks)

    store.con.execute("DELETE FROM planilha_celulas WHERE sha256 = ?", (digest,))
    store.con.commit()
    assert origem.is_file()
    store.fechar()


def test_aba_pequena_continua_em_janelas_sem_tabela_de_celulas() -> None:
    doc = parse_xlsx(_xlsx(40, 4), "resumo.xlsx")

    assert doc.linhas_planilha == ()
    assert doc.blocks
    assert all("(resumo da aba)" not in bloco.locator for bloco in doc.blocks)
