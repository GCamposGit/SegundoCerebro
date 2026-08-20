"""Comparação de vetores entre dois índices — a prova da F3.6, sem GPU."""

from __future__ import annotations

import numpy as np

import pytest

from eval.sintetico.comparar import comparar, cosseno


def test_cosseno_de_vetor_igual_e_um() -> None:
    v = np.array([0.6, 0.8], dtype=np.float32)
    assert cosseno(v, v) == pytest.approx(1.0)


def test_indices_identicos_passam() -> None:
    v = np.array([1.0, 0.0], dtype=np.float32)
    rel = comparar({"c1": v}, {"c1": v}, ("e5-large:1024:x",), ("e5-large:1024:x",))
    assert rel.passou
    assert rel.min_cosseno == 1.0


def test_vetor_distinto_reprova() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    rel = comparar({"c1": a}, {"c1": b}, ("m",), ("m",))
    assert not rel.passou
    assert rel.abaixo == ("c1",)


def test_chunk_faltando_reprova() -> None:
    v = np.array([1.0, 0.0], dtype=np.float32)
    rel = comparar({"c1": v, "c2": v}, {"c1": v}, ("m",), ("m",))
    assert rel.so_a == 1
    assert not rel.passou


def test_model_id_diferente_reprova() -> None:
    v = np.array([1.0, 0.0], dtype=np.float32)
    rel = comparar({"c1": v}, {"c1": v}, ("e5-large:1024:a",), ("e5-large:1024:b",))
    assert not rel.passou
