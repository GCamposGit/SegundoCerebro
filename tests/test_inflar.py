"""R9.3 — inflate an index without the encoder.

The canary of the class: latency doors existed, the 1M index did not, and every
measurement of search ran on ~18 chunks. Perturbing vectors is the method;
cleaning a venv or indexing for 22 h is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from segundocerebro.index.inflar import (
    CHUNKS_POR_DOC,
    InflarErro,
    dim_do_indice,
    inflar,
    main,
    perturbar,
    replica,
)
from segundocerebro.index.store import Store

from tests.falsos import DIM, EmbedderFalso, chunk


def _indice_minimo(tmp_path: Path, n: int = 4) -> Path:
    dest = tmp_path / "origem"
    store = Store(dest, DIM)
    emb = EmbedderFalso()
    chunks = [
        chunk(f"c{i}", f"doc{i}.md", 0, f"contrato CT-VCE-2024-0142 trecho {i}")
        for i in range(n)
    ]
    vetores = emb.embed_passagens([c.text for c in chunks])
    for c in chunks:
        store.registrar_documento(
            path=c.doc_path,
            raiz="teste",
            tamanho=len(c.text),
            mtime=1.0,
            status="ok",
            n_chunks=1,
            model_id=emb.model_id,
        )
    store.gravar_chunks(chunks, vetores, mtime=1.0, model_id=emb.model_id)
    store.commit()
    store.fechar()
    return dest


def test_dim_sai_do_model_id(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path)
    assert dim_do_indice(origem) == DIM


def test_inflar_atinge_n(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path, n=4)
    destino = tmp_path / "inflado"
    relato = inflar(origem, destino, n=20, seed=42)
    assert relato.n_origem == 4
    assert relato.n_destino == 20
    dest = Store(destino, DIM)
    try:
        cons = dest.verificar_consistencia()
        assert cons["chunks"] == 20
        assert cons["vetores"] == 20
        assert cons["diferenca"] == 0
    finally:
        dest.fechar()


def test_semente_igual_produz_os_mesmos_vetores(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path, n=3)
    a = inflar(origem, tmp_path / "a", n=8, seed=7)
    b = inflar(origem, tmp_path / "b", n=8, seed=7)
    assert a.n_destino == b.n_destino
    sa, sb = Store(tmp_path / "a", DIM), Store(tmp_path / "b", DIM)
    try:
        va, vb = sa.vetores_por_id(), sb.vetores_por_id()
        assert sorted(va) == sorted(vb)
        for chave in va:
            np.testing.assert_allclose(va[chave], vb[chave], rtol=0, atol=0)
    finally:
        sa.fechar()
        sb.fechar()


def test_busca_densa_ainda_devolve(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path, n=4)
    destino = tmp_path / "inflado"
    inflar(origem, destino, n=16, seed=42)
    dest = Store(destino, DIM)
    try:
        consulta = EmbedderFalso().embed_consulta("contrato CT-VCE-2024-0142")
        acertos = dest.buscar_denso(consulta, k=5)
        assert acertos
        assert acertos[0].id.startswith("inflado-")
    finally:
        dest.fechar()


def test_recusa_n_menor_que_a_semente(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path, n=4)
    with pytest.raises(InflarErro, match="menor que a semente"):
        inflar(origem, tmp_path / "x", n=2, seed=1)


def test_recusa_destino_igual_origem(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path)
    with pytest.raises(InflarErro, match="mesmo índice"):
        inflar(origem, origem, n=10, seed=1)


def test_perturbar_e_deterministico() -> None:
    """Isolated: the predicate, not the real index."""
    rng_a = np.random.default_rng(99)
    rng_b = np.random.default_rng(99)
    v = np.ones(8, dtype=np.float32) / np.sqrt(8)
    np.testing.assert_allclose(perturbar(v, rng_a), perturbar(v, rng_b))
    diferente = perturbar(v, np.random.default_rng(100))
    assert not np.allclose(perturbar(v, np.random.default_rng(99)), diferente)


def test_replica_nao_reusa_id_nem_caminho() -> None:
    base = chunk("c0", "doc.md", 0, "texto")
    v = np.ones(DIM, dtype=np.float32)
    a, _ = replica(base, v, 0, seed=1)
    b, _ = replica(base, v, 1, seed=1)
    longe, _ = replica(base, v, CHUNKS_POR_DOC, seed=1)
    assert a.id != b.id
    assert a.doc_path == b.doc_path
    assert a.ordinal != b.ordinal
    assert longe.doc_path != a.doc_path
    assert a.id != base.id


def test_modulo_nao_importa_encoder() -> None:
    """Inflating that loads fastembed is the 22 h path. This module must not."""
    fonte = Path("src/segundocerebro/index/inflar.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(a.name.split(".")[0] for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    proibidos = {"fastembed", "onnxruntime", "embeddings", "indexer"}
    assert not (nomes & proibidos), nomes & proibidos


def test_cli_recusa_em_portugues(tmp_path: Path) -> None:
    origem = _indice_minimo(tmp_path)
    codigo = main(
        ["--origem", str(origem), "--destino", str(origem), "--n", "10"]
    )
    assert codigo == 2
