"""O smoke da F3.6 não pode levantar só porque a máquina não tem GPU hoje."""

from __future__ import annotations

from segundocerebro.index.smoke_cuda import (
    CANDIDATOS_RERANK,
    _gpus,
    _scores_finitos,
    passagens_rerank,
)


def test_gpus_devolve_lista() -> None:
    assert isinstance(_gpus(), list)


def test_passagens_rerank_tamanho() -> None:
    docs = passagens_rerank(CANDIDATOS_RERANK)
    assert len(docs) == CANDIDATOS_RERANK
    assert all(docs)
    assert passagens_rerank(1)[0] == docs[0]


def test_scores_finitos() -> None:
    assert _scores_finitos([0.1, -1.2, 3.0])
    assert not _scores_finitos([0.1, float("nan")])
    assert not _scores_finitos([float("inf")])
    assert not _scores_finitos([])
