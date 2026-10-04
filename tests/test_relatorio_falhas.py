"""O laudo por extensão conta status e não repete o caminho do arquivo."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from segundocerebro.index.progresso import caminho_de
from segundocerebro.index.relatorio_falhas import (
    agrupar,
    extensao_de,
    formatar,
    main,
    montar,
)
from segundocerebro.index import relatorio_falhas


def test_extensao_ignora_a_pasta() -> None:
    assert extensao_de("pasta/comprovante.PDF") == "pdf"
    assert extensao_de("sem-sufixo") == "(sem extensão)"
    assert extensao_de(".gitignore") == "(sem extensão)"


def test_agrupar_separa_status_e_quarentena() -> None:
    linhas = dict(agrupar(
        [("a.pdf", "erro"), ("b.pdf", "vazio"), ("c.docx", "ok"), ("d.ppt", "sem_parser")],
        ["a.pdf"],
    ))
    assert linhas["pdf"].por_status["erro"] == 1
    assert linhas["pdf"].por_status["vazio"] == 1
    assert linhas["pdf"].quarentena == 1
    assert linhas["docx"].por_status["ok"] == 1
    assert linhas["ppt"].por_status["sem_parser"] == 1


def _indice(tmp_path: Path, status_passada: str) -> Path:
    indice = tmp_path / "indice"
    indice.mkdir()
    caminho_de(indice).write_text(
        json.dumps({"status": status_passada}),
        encoding="utf-8",
    )
    con = sqlite3.connect(indice / "registro.db")
    con.execute("CREATE TABLE documentos (path TEXT, status TEXT)")
    con.execute("CREATE TABLE quarentena (path TEXT, motivo TEXT)")
    con.executemany(
        "INSERT INTO documentos VALUES (?, ?)",
        [
            ("pasta/sigilo.pdf", "erro"),
            ("arquivo sem nome", "vazio"),
            ("nota.docx", "ok"),
        ],
    )
    con.execute("INSERT INTO quarentena VALUES (?, ?)", ("pasta/sigilo.pdf", "timeout"))
    con.commit()
    con.close()
    return indice


def test_markdown_nao_repete_caminho(tmp_path: Path) -> None:
    relatorio = montar("alfa", _indice(tmp_path, "concluida"), agora=False)
    texto = formatar(relatorio)
    assert "Passada: fechada." in texto
    assert "sigilo" not in texto
    assert "| pdf |" in texto
    assert "não escolhe leitor novo" in texto


def test_passada_aberta_recusa_sem_agora(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "alfa"\nindice = "indice"\n',
        encoding="utf-8",
    )
    _indice(tmp_path, "indexando")
    assert main(["--config", str(tmp_path / "config.toml"), "--base", "alfa"]) == 3


def test_agora_marca_parcial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "alfa"\nindice = "indice"\n',
        encoding="utf-8",
    )
    _indice(tmp_path, "indexando")
    assert main([
        "--config", str(tmp_path / "config.toml"),
        "--base", "alfa",
        "--agora",
    ]) == 0
    saida = capsys.readouterr().out
    assert "parcial" in saida
    assert "sigilo" not in saida


def test_leitura_recusa_escrita(tmp_path: Path) -> None:
    indice = _indice(tmp_path, "concluida")
    conexao = relatorio_falhas._abrir_somente_leitura(indice / "registro.db")
    try:
        with pytest.raises(sqlite3.OperationalError):
            conexao.execute("INSERT INTO documentos VALUES ('x.txt', 'ok')")
    finally:
        conexao.close()
