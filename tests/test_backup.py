"""Backup consistente e restauração verificável (FND-08b)."""

from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from segundocerebro.index.backup import (
    BackupInconsistente,
    BackupRecusado,
    criar_backup,
    main,
    restaurar_backup,
)
from segundocerebro.index.esquema import ESQUEMA_DOCUMENTOS_V1
from segundocerebro.index.store import Store
from segundocerebro.index.trava import TravaDeIndice
from segundocerebro.index.travas import NOME_DA_TRAVA

from tests.falsos import DIM, chunk

REPO = Path(__file__).resolve().parents[1]
TEXTO = "O contrato CT-VCE-2024-0142 define o reajuste anual da Várzea Clara Energia."


def _indice_minimo(tmp_path: Path) -> Path:
    indice = tmp_path / "indice"
    store = Store(indice, DIM)
    c = chunk("c-vce-1", "contrato.md", 0, TEXTO)
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    store.gravar_chunks([c], [vetor], mtime=1.0, model_id="falso:8")
    store.registrar_documento(
        path="contrato.md",
        raiz="principal",
        tamanho=len(TEXTO),
        mtime=1.0,
        sha256="a" * 64,
        status="ok",
        n_chunks=1,
        model_id="falso:8",
        chunker="2",
    )
    store.commit()
    store.fechar()
    (indice / "segredo.txt").write_text("não pertence ao backup", encoding="utf-8")
    return indice


def _indice_legado_minimo(tmp_path: Path) -> Path:
    """Create the pre-occurrence SQLite shape without opening it via Store."""
    indice = tmp_path / "indice-legado"
    indice.mkdir()
    con = sqlite3.connect(indice / "registro.db")
    con.executescript(ESQUEMA_DOCUMENTOS_V1)
    con.executescript(
        """
        CREATE TABLE chunks (
            id       TEXT PRIMARY KEY,
            path     TEXT NOT NULL,
            caminho  TEXT NOT NULL DEFAULT '',
            ordinal  INTEGER NOT NULL,
            trilha   TEXT NOT NULL DEFAULT '',
            locator  TEXT NOT NULL DEFAULT '',
            kind     TEXT NOT NULL DEFAULT '',
            chars    INTEGER NOT NULL DEFAULT 0,
            texto    TEXT NOT NULL
        );
        CREATE INDEX idx_chunks_path ON chunks(path);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            texto, trilha, caminho,
            content='chunks', content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE VIRTUAL TABLE chunks_fts_vocab USING fts5vocab(chunks_fts, 'row');
        CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, texto, trilha, caminho)
            VALUES (new.rowid, new.texto, new.trilha, new.caminho);
        END;
        CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, texto, trilha, caminho)
            VALUES ('delete', old.rowid, old.texto, old.trilha, old.caminho);
        END;
        """
    )
    con.execute(
        """
        INSERT INTO documentos
            (path, raiz, tamanho, mtime, sha256, status, detalhe, n_chunks,
             model_id, chunker, parser, indexado_em)
        VALUES (?, 'principal', ?, 1.0, ?, 'ok', '', 1,
                'falso:8', '2', '', 'agora')
        """,
        ("contrato.md", len(TEXTO), "b" * 64),
    )
    con.execute(
        """
        INSERT INTO chunks
            (id, path, caminho, ordinal, trilha, locator, kind, chars, texto)
        VALUES ('c-vce-legado', 'contrato.md', 'contrato md', 0, '', '',
                'paragrafo', ?, ?)
        """,
        (len(TEXTO), TEXTO),
    )
    con.execute(
        "INSERT INTO chunks_fts(rowid, texto, trilha, caminho) "
        "SELECT rowid, texto, trilha, caminho FROM chunks"
    )
    con.commit()
    con.close()
    return indice


def _ids(diretorio: Path) -> list[str]:
    store = Store(diretorio, DIM)
    try:
        hits = store.buscar_lexical("CT-VCE-2024-0142", 5)
        return [h.id for h in hits]
    finally:
        store.fechar()


def test_store_fechar_libera_recursos_lance() -> None:
    class Recurso:
        def __init__(self) -> None:
            self.fechado = False

        def close(self) -> None:
            self.fechado = True

    class Conexao:
        def __init__(self) -> None:
            self.commits = 0
            self.fechada = False

        def commit(self) -> None:
            self.commits += 1

        def close(self) -> None:
            self.fechada = True

    tabela = Recurso()
    conexao_lance = Recurso()
    conexao = Conexao()
    store = object.__new__(Store)
    store.con = conexao
    store._tabela = tabela
    store._db = SimpleNamespace(_conn=conexao_lance)
    store._ann_ativo = True

    store.fechar()

    assert conexao.commits == 1
    assert conexao.fechada
    assert tabela.fechado
    assert conexao_lance.fechado
    assert store._tabela is None
    assert store._db is None
    assert store._ann_ativo is None


def test_backup_e_restore_reproduzem_ids_e_consulta(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    original = raiz / "contrato.md"
    original.write_text(TEXTO, encoding="utf-8")
    mtime = original.stat().st_mtime_ns

    backup = tmp_path / "backup"
    manifesto = criar_backup(indice, backup)

    assert "registro" in manifesto.inclui
    assert "vetores" in manifesto.inclui
    assert "originais" not in manifesto.inclui
    assert manifesto.procedimento["sqlite"] == "backup_api"
    assert manifesto.procedimento["lancedb"] == "copia_apos_trava"
    assert not (backup / "segredo.txt").exists()
    assert not (backup / NOME_DA_TRAVA).exists()
    assert original.stat().st_mtime_ns == mtime
    assert original.read_text(encoding="utf-8") == TEXTO

    restaurado = tmp_path / "restaurado"
    restaurar_backup(backup, restaurado)

    assert _ids(restaurado) == ["c-vce-1"]
    assert _ids(indice) == ["c-vce-1"]
    assert original.stat().st_mtime_ns == mtime


def test_backup_verifica_indice_legado_antes_de_publicar(tmp_path: Path) -> None:
    indice = _indice_legado_minimo(tmp_path)
    antes = (indice / "registro.db").read_bytes()
    backup = tmp_path / "backup-legado"

    manifesto = criar_backup(indice, backup)

    assert manifesto.contagens["documentos"] == 1
    assert manifesto.contagens["chunks"] == 1
    assert manifesto.consulta["reproduzido"] is True
    assert (indice / "registro.db").read_bytes() == antes


def test_escritor_ativo_recusa_e_nao_publica(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    dest = tmp_path / "backup"
    with TravaDeIndice(indice):
        with pytest.raises(BackupRecusado, match="indexação") as exc:
            criar_backup(indice, dest)
    assert exc.value.codigo == "escritor_ativo"
    assert not dest.exists()
    assert (indice / "registro.db").is_file()


def test_checksum_divergente_recusa_restore(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    criar_backup(indice, backup)
    registro = backup / "registro.db"
    registro.write_bytes(registro.read_bytes() + b"\x00")

    dest = tmp_path / "restaurado"
    with pytest.raises(BackupInconsistente) as exc:
        restaurar_backup(backup, dest)
    assert exc.value.codigo == "checksum_divergente"
    assert not dest.exists()
    assert _ids(indice) == ["c-vce-1"]


def test_arquivo_truncado_recusa_restore(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    criar_backup(indice, backup)
    registro = backup / "registro.db"
    registro.write_bytes(registro.read_bytes()[:32])

    dest = tmp_path / "restaurado"
    with pytest.raises(BackupInconsistente) as exc:
        restaurar_backup(backup, dest)
    assert exc.value.codigo == "checksum_divergente"
    assert not dest.exists()


def test_versao_incompativel_recusa_restore(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    criar_backup(indice, backup)
    manifesto = json.loads((backup / "manifesto.json").read_text(encoding="utf-8"))
    manifesto["versao_formato"] = 99
    (backup / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False), encoding="utf-8"
    )

    dest = tmp_path / "restaurado"
    with pytest.raises(BackupRecusado) as exc:
        restaurar_backup(backup, dest)
    assert exc.value.codigo == "versao_incompativel"
    assert not dest.exists()


def test_disco_cheio_nao_publica_e_preserva_origem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    indice = _indice_minimo(tmp_path)
    antes = (indice / "registro.db").read_bytes()
    dest = tmp_path / "backup"

    def estourar(_origem: Path, _destino: Path) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("segundocerebro.index.backup.copiar_sqlite", estourar)
    with pytest.raises(BackupRecusado) as exc:
        criar_backup(indice, dest)
    assert exc.value.codigo == "disco_cheio"
    assert not dest.exists()
    assert (indice / "registro.db").read_bytes() == antes
    leftover = list(dest.parent.glob(".backup.*.tmp"))
    assert leftover == []


def test_tmp_de_outro_processo_permanece(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    dest = tmp_path / "backup"
    alheio = dest.parent / f".{dest.name}.999999.tmp"
    alheio.mkdir()
    marca = alheio / "de-outro"
    marca.write_text("fica", encoding="utf-8")

    criar_backup(indice, dest)

    assert marca.is_file()
    assert marca.read_text(encoding="utf-8") == "fica"


def test_destino_ocupado_nao_apaga_indice_existente(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    criar_backup(indice, backup)
    ocupado = tmp_path / "restaurado"
    ocupado.mkdir()
    (ocupado / "registro.db").write_text("indice-ja-existente", encoding="utf-8")

    with pytest.raises(BackupRecusado) as exc:
        restaurar_backup(backup, ocupado)
    assert exc.value.codigo == "destino_ocupado"
    assert (ocupado / "registro.db").read_text(encoding="utf-8") == "indice-ja-existente"


def test_anexos_opcionais_e_parse_store(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    parse = indice / "parse_store"
    parse.mkdir()
    (parse / "entrada.canon.zz").write_bytes(b"cache")
    cfg = tmp_path / "config.toml"
    cfg.write_text("versao = 1\n", encoding="utf-8")
    gloss = tmp_path / "glossario.toml"
    gloss.write_text("[CT-VCE]\nformas = [\"contrato\"]\n", encoding="utf-8")

    sem_extra = tmp_path / "so-indice"
    criar_backup(indice, sem_extra)
    assert not (sem_extra / "parse_store").exists()
    assert not (sem_extra / "anexos").exists()

    com_extra = tmp_path / "com-anexos"
    criar_backup(
        indice,
        com_extra,
        config=cfg,
        glossario=gloss,
        incluir_parse_store=True,
    )
    assert (com_extra / "parse_store" / "entrada.canon.zz").read_bytes() == b"cache"
    assert (com_extra / "anexos" / "config.toml").read_text(encoding="utf-8") == "versao = 1\n"
    restaurado = tmp_path / "restaurado-anexos"
    manifesto = restaurar_backup(com_extra, restaurado)
    assert "parse_store" in manifesto.inclui
    assert "config" in manifesto.inclui
    assert (restaurado / "anexos" / "glossario.toml").is_file()


def test_destino_unicode(tmp_path: Path) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "cópia-índice"
    criar_backup(indice, backup)
    assert _ids(tmp_path / "indice") == ["c-vce-1"]
    restaurado = tmp_path / "índice-restaurado"
    restaurar_backup(backup, restaurado)
    assert _ids(restaurado) == ["c-vce-1"]


def test_cli_criar_e_restaurar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    codigo = main(["criar", "--indice", str(indice), "--destino", str(backup)])
    assert codigo == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida["contagens"]["chunks"] == 1

    restaurado = tmp_path / "restaurado"
    codigo = main(["restaurar", "--origem", str(backup), "--destino", str(restaurado)])
    assert codigo == 0
    assert _ids(restaurado) == ["c-vce-1"]


def test_cli_help_nao_carrega_encoder() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "segundocerebro.index.backup", "--help"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "criar" in proc.stdout
    assert "restaurar" in proc.stdout


def test_backup_nao_importa_encoder() -> None:
    """AST: the backup surface must not pull embeddings/fastembed."""
    for nome in ("backup.py", "backup_io.py", "backup_manifesto.py", "backup_verificar.py"):
        arvore = ast.parse(
            (REPO / "src" / "segundocerebro" / "index" / nome).read_text(encoding="utf-8"),
            filename=nome,
        )
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                mods = [a.name.split(".")[0] for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.module:
                mods = [no.module.split(".")[0]]
            else:
                continue
            assert "fastembed" not in mods
            assert "embeddings" not in mods


def test_backup_nao_leva_wal_nem_trava(tmp_path: Path) -> None:
    """Published snapshot is the backup-API database, not live WAL/lock files."""
    indice = _indice_minimo(tmp_path)
    backup = tmp_path / "backup"
    manifesto = criar_backup(indice, backup)
    assert manifesto.procedimento["sqlite"] == "backup_api"
    assert not (backup / "registro.db-wal").exists()
    assert not (backup / NOME_DA_TRAVA).exists()
    assert (backup / "registro.db").stat().st_size > 0
