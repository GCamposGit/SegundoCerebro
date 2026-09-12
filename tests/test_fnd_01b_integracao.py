"""FND-01b-int: homonyms remain addressable through public read and search."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.acesso.documento import LeitorDocumento
from segundocerebro.acesso.identidade import interpretar
from segundocerebro.acesso.original import ErroLeitura
from segundocerebro.acesso import registro
from segundocerebro.census import Config, RootSpec
from segundocerebro.config import Base
from segundocerebro.index.indexer import indexar
from segundocerebro.index.ocorrencia import CaminhoAmbiguo
from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida
from segundocerebro.acesso.identidade import doc_id_de

from tests.falsos import DIM, EmbedderFalso


def _acervo(tmp_path: Path) -> tuple[Store, EmbedderFalso, Base]:
    pessoal = tmp_path / "pessoal"
    trabalho = tmp_path / "trabalho"
    pessoal.mkdir()
    trabalho.mkdir()
    (pessoal / "contrato.md").write_text(
        "# Contrato pessoal\nA oficina doméstica começa amanhã.\n",
        encoding="utf-8",
    )
    (trabalho / "contrato.md").write_text(
        "# Contrato trabalho\nO escritório exige a cláusula nove.\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / "indice", DIM)
    embedder = EmbedderFalso()
    cfg = Config(
        roots=[RootSpec("pessoal", pessoal), RootSpec("trabalho", trabalho)]
    )
    indexar(cfg, store, embedder, parse_workers=1, publicar=False)
    base = Base(
        id="teste",
        indice=store.diretorio,
        raizes=(RootSpec("pessoal", pessoal), RootSpec("trabalho", trabalho)),
    )
    return store, embedder, base


def test_leitura_e_busca_desambiguam_por_root_id(tmp_path: Path) -> None:
    store, embedder, base = _acervo(tmp_path)
    try:
        documentos = registro.documentos_da_pasta(store, "", recursivo=True)
        assert {doc.root_id for doc in documentos} == {"pessoal", "trabalho"}
        assert {doc.caminho for doc in documentos} == {"contrato.md"}
        assert len({doc.ocorrencia_id for doc in documentos}) == 2

        with pytest.raises(CaminhoAmbiguo):
            registro.resolver(store, interpretar("contrato.md"))
        pessoal = registro.resolver(
            store, interpretar("contrato.md", root_id="pessoal")
        )
        assert pessoal is not None
        assert pessoal.root_id == "pessoal"

        leitor = LeitorDocumento(store, base)
        with pytest.raises(ErroLeitura, match="root_id"):
            leitor.ler("contrato.md")
        lido = leitor.ler("contrato.md", root_id="pessoal")
        assert lido["documento"]["root_id"] == "pessoal"
        assert "oficina doméstica" in lido["markdown"]

        busca = BuscaHibrida(
            store, embedder, usar_denso=False, usar_nome=False
        )
        acertos = busca.buscar_chunks("oficina", 5, root_id="pessoal")
        assert acertos
        assert {acerto.root_id for acerto in acertos} == {"pessoal"}
        assert all(acerto.path == "contrato.md" for acerto in acertos)

        hits = busca.search("cláusula", 5, root_id="trabalho")
        assert hits
        assert {hit.root_id for hit in hits} == {"trabalho"}

        somente_nome = BuscaHibrida(
            store,
            embedder,
            usar_denso=False,
            usar_lexical=False,
            usar_nome=True,
        )
        hits = somente_nome.search("contrato", 5, root_id="trabalho")
        assert hits
        assert {hit.root_id for hit in hits} == {"trabalho"}
    finally:
        store.fechar()


def test_mesmo_conteudo_mantem_doc_id_publico_e_ocorrencias_distintas(
    tmp_path: Path,
) -> None:
    pessoal = tmp_path / "pessoal"
    trabalho = tmp_path / "trabalho"
    pessoal.mkdir()
    trabalho.mkdir()
    texto = "# Nota\nO mesmo conteúdo fica em duas raízes.\n"
    (pessoal / "nota.md").write_text(texto, encoding="utf-8")
    (trabalho / "nota.md").write_text(texto, encoding="utf-8")
    store = Store(tmp_path / "indice", DIM)
    try:
        indexar(
            Config(roots=[RootSpec("pessoal", pessoal), RootSpec("trabalho", trabalho)]),
            store,
            EmbedderFalso(),
            parse_workers=1,
            publicar=False,
        )
        docs = list(
            store.con.execute(
                "SELECT root_id, ocorrencia_id, sha256 FROM documentos WHERE path = 'nota.md'"
            )
        )
        assert len(docs) == 2
        assert len({str(doc["ocorrencia_id"]) for doc in docs}) == 2
        assert len({str(doc["sha256"]) for doc in docs}) == 1
        assert len({doc_id_de(str(doc["sha256"])) for doc in docs}) == 1
    finally:
        store.fechar()
