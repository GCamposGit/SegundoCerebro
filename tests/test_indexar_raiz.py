"""Indexar uma raiz nova não pode parecer que as outras sumiram."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.acesso import registro
from segundocerebro.census import Config, RootSpec
from segundocerebro.config import ErroDeConfig
from segundocerebro.index.cli import construir_parser
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import Store

from tests.falsos import DIM, EmbedderFalso


def _duas_raizes(tmp_path: Path) -> tuple[Config, Path, Path]:
    alfa = tmp_path / "alfa"
    beta = tmp_path / "beta"
    alfa.mkdir()
    beta.mkdir()
    (alfa / "um.md").write_text("# Alfa\nconteúdo da primeira raiz\n", encoding="utf-8")
    (beta / "dois.md").write_text("# Beta\nconteúdo da segunda raiz\n", encoding="utf-8")
    return Config(roots=[RootSpec("alfa", alfa), RootSpec("beta", beta)]), alfa, beta


def test_so_raiz_indexa_so_a_nova_e_mantem_a_outra(tmp_path: Path) -> None:
    cfg, _alfa, beta = _duas_raizes(tmp_path)
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    indexar(cfg, store, emb, publicar=False)
    antes = int(store.estatisticas()["documentos"])
    (beta / "tres.md").write_text("# Beta 2\nterceiro arquivo\n", encoding="utf-8")
    chamadas = emb.chamadas

    progresso = indexar(cfg, store, emb, so_raiz="beta", publicar=False)

    assert progresso.indexados == 1
    assert int(store.estatisticas()["documentos"]) == antes + 1
    assert emb.chamadas > chamadas
    docs = registro.documentos_da_pasta(store, "", recursivo=True)
    assert {doc.root_id for doc in docs} == {"alfa", "beta"}
    store.fechar()


def test_so_raiz_desconhecida_recusa(tmp_path: Path) -> None:
    cfg, _a, _b = _duas_raizes(tmp_path)
    store = Store(tmp_path / "indice", DIM)
    with pytest.raises(ErroDeConfig, match="gamma"):
        indexar(cfg, store, EmbedderFalso(), so_raiz="gamma", publicar=False)
    store.fechar()


def test_cli_declara_flag_raiz() -> None:
    ajuda = construir_parser().format_help()
    assert "--raiz" in ajuda
    assert "outras" in ajuda
