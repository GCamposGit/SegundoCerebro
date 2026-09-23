"""Índice no esquema v1, para migração. Não é arquivo de teste: o Q17 proíbe."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from segundocerebro.index.esquema import ESQUEMA_DOCUMENTOS_V1
from segundocerebro.index.store import Store

from tests.falsos import DIM, chunk

TEXTO = "O contrato CT-VCE-2024-0142 define o reajuste anual da Várzea Clara Energia."


def _legado(tmp_path: Path) -> Path:
    indice = tmp_path / "legado"
    indice.mkdir()
    con = sqlite3.connect(indice / "registro.db")
    con.executescript(ESQUEMA_DOCUMENTOS_V1)
    con.close()
    store = Store(indice, DIM)
    trecho = chunk("c-vce-1", "contrato.md", 0, TEXTO)
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    store.gravar_chunks([trecho], [vetor], mtime=1.0, model_id="falso:8")
    store.registrar_documento(
        path="contrato.md",
        raiz="pessoal",
        tamanho=len(TEXTO),
        mtime=1.0,
        sha256="a" * 64,
        status="ok",
        n_chunks=1,
        model_id="falso:8",
        chunker="2",
    )
    store.registrar_documento(
        path="ata.md",
        raiz="trabalho",
        tamanho=20,
        mtime=2.0,
        sha256="b" * 64,
        status="ok",
        n_chunks=0,
    )
    store.commit()
    store.fechar()
    parse = indice / "parse_store" / "aa"
    parse.mkdir(parents=True)
    (parse / "canon.zz").write_bytes(b"cache")
    return indice
