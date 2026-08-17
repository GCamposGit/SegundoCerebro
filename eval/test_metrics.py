"""Unit tests for the metrics — hand-computed values, no corpus needed."""

from __future__ import annotations

from math import log2

import pytest

from eval.metrics import (
    MODO_QUALQUER,
    MODO_TODAS,
    media,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

RANKED = ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"]


def test_recall_qualquer_e_binario() -> None:
    assert recall_at_k(RANKED, {"c.pdf"}, 3, MODO_QUALQUER) == 1.0
    assert recall_at_k(RANKED, {"c.pdf"}, 2, MODO_QUALQUER) == 0.0
    # duas fontes intercambiáveis: achar uma já é sucesso completo
    assert recall_at_k(RANKED, {"c.pdf", "z.pdf"}, 3, MODO_QUALQUER) == 1.0


def test_recall_todas_e_proporcional() -> None:
    assert recall_at_k(RANKED, {"a.pdf", "b.pdf"}, 5, MODO_TODAS) == 1.0
    assert recall_at_k(RANKED, {"a.pdf", "z.pdf"}, 5, MODO_TODAS) == 0.5
    assert recall_at_k(RANKED, {"a.pdf", "b.pdf"}, 1, MODO_TODAS) == 0.5


def test_recall_sem_fontes_ou_k_zero() -> None:
    assert recall_at_k(RANKED, set(), 5) == 0.0
    assert recall_at_k(RANKED, {"a.pdf"}, 0) == 0.0


def test_recall_modo_invalido() -> None:
    with pytest.raises(ValueError):
        recall_at_k(RANKED, {"a.pdf"}, 5, "mais_ou_menos")


def test_duplicata_no_ranking_nao_conta_duas_vezes() -> None:
    ranked = ["a.pdf", "a.pdf", "b.pdf"]
    # 'a' repetido não pode empurrar 'b' para fora do top-2 nem contar dobrado
    assert recall_at_k(ranked, {"a.pdf", "b.pdf"}, 2, MODO_TODAS) == 1.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(RANKED, {"a.pdf"}) == 1.0
    assert reciprocal_rank(RANKED, {"b.pdf"}) == 0.5
    assert reciprocal_rank(RANKED, {"d.pdf"}) == 0.25
    assert reciprocal_rank(RANKED, {"z.pdf"}) == 0.0


def test_reciprocal_rank_respeita_o_corte() -> None:
    assert reciprocal_rank(RANKED, {"e.pdf"}, k=10) == pytest.approx(0.2)
    assert reciprocal_rank(RANKED, {"e.pdf"}, k=3) == 0.0


def test_ndcg_perfeito_e_um() -> None:
    assert ndcg_at_k(RANKED, {"a.pdf"}, 5) == pytest.approx(1.0)
    assert ndcg_at_k(RANKED, {"a.pdf", "b.pdf"}, 5) == pytest.approx(1.0)


def test_ndcg_penaliza_posicao() -> None:
    # relevante na 2a posição: DCG = 1/log2(3), IDCG = 1/log2(2) = 1
    assert ndcg_at_k(RANKED, {"b.pdf"}, 5) == pytest.approx(1 / log2(3))
    assert ndcg_at_k(RANKED, {"b.pdf"}, 5) < ndcg_at_k(RANKED, {"a.pdf"}, 5)


def test_ndcg_sem_acerto() -> None:
    assert ndcg_at_k(RANKED, {"z.pdf"}, 5) == 0.0


def test_ndcg_idcg_limitado_por_k() -> None:
    # três fontes esperadas mas k=1: o ideal alcançável é uma só
    assert ndcg_at_k(RANKED, {"a.pdf", "b.pdf", "c.pdf"}, 1) == pytest.approx(1.0)


def test_media() -> None:
    assert media([1.0, 0.0]) == 0.5
    assert media([]) == 0.0
