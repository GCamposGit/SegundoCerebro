"""R3.2: useful search on day one, final vectors identical to a single pass.

MiniLM (384d, 128-token window) cannot live in the e5-large Lance table
(1024d). The draft that preserves byte-identity is parse + FTS first; pass 2
writes the final vectors on top. Retrieve fusion of two dense spaces is a
notebook package — this one does not touch `retrieve/`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from segundocerebro.index.indexer import TravaDeIndice, indexar
from segundocerebro.index.store import Store
from tests.falsos import DIM, EmbedderFalso, corpus


def test_fts_funciona_sem_vetor(tmp_path: Path) -> None:
    """The class: after pass 1 the document is already findable by name and body."""
    store = Store(tmp_path / "indice", DIM)
    from tests.falsos import chunk

    c = chunk("c1", "Política/PO-ACME-007.md", 0, "O PO-ACME-007 define o uso aceitável de IA.")
    store.gravar_textos([c])
    store.commit()
    acertos = store.buscar_lexical("PO-ACME-007", 5)
    assert [a.id for a in acertos] == ["c1"]
    assert store.verificar_consistencia()["vetores"] == 0
    store.fechar()


def test_passe_2_e_byte_identico_ao_passe_unico(tmp_path: Path) -> None:
    raiz = tmp_path / "corpus"
    cfg = corpus(raiz)
    unico = Store(tmp_path / "unico", DIM)
    indexar(cfg, unico, EmbedderFalso(), publicar=False, reconciliar_ao_fim=False)
    dois = Store(tmp_path / "dois", DIM)
    indexar(
        cfg,
        dois,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        dois_passes=True,
    )
    v_unico = unico.vetores_por_id()
    v_dois = dois.vetores_por_id()
    assert set(v_unico) == set(v_dois)
    for cid, vetor in v_unico.items():
        np.testing.assert_allclose(vetor, v_dois[cid], atol=0, rtol=0)
    assert unico.estado_documento("contrato.md").model_id == "falso:8"
    assert dois.estado_documento("contrato.md").model_id == "falso:8"
    assert dois.verificar_consistencia()["diferenca"] == 0
    unico.fechar()
    dois.fechar()


def test_trava_cerca_os_dois_passes(tmp_path: Path) -> None:
    """Write lock is held for the whole run — pass 2 is not a second indexer."""
    raiz = tmp_path / "corpus"
    cfg = corpus(raiz)
    store = Store(tmp_path / "indice", DIM)
    indexar(cfg, store, EmbedderFalso(), publicar=False, reconciliar_ao_fim=False, dois_passes=True)
    trava = TravaDeIndice(store.diretorio)
    assert not trava.ocupada()
    store.fechar()


def test_config_indexacao_liga_dois_passes(tmp_path: Path) -> None:
    from segundocerebro.config import carregar

    caminho = tmp_path / "config.toml"
    caminho.write_text(
        '[indexacao]\nmodelo_rascunho = "minilm"\n[[base]]\nid = "a"\n',
        encoding="utf-8",
    )
    cfg = carregar(caminho, ambiente={})
    assert cfg.indexacao.modelo_rascunho == "minilm"
    assert cfg.indexacao.ativo
