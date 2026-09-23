"""A guarda de recall escolhe ANN por qualidade, não só por velocidade."""

from dataclasses import dataclass

import numpy as np
import pytest

from eval.ann import (
    ResultadoANN,
    escolher_configuracao,
    escolher_nprobes,
    medir,
    parse_nprobes,
    parse_refine,
    recall_do_flat,
)


@dataclass(frozen=True)
class AcertoFake:
    id: str


def resultado(nprobes: int, recalls: tuple[float, ...]) -> ResultadoANN:
    return ResultadoANN(nprobes, 0, recalls, tuple(1.0 for _ in recalls))


def test_recall_e_a_intersecao_com_o_top_k_exato() -> None:
    flat = [AcertoFake("a"), AcertoFake("b"), AcertoFake("c"), AcertoFake("d")]
    ann = [AcertoFake("a"), AcertoFake("c"), AcertoFake("x"), AcertoFake("y")]

    assert recall_do_flat(flat, ann) == 0.5
    assert recall_do_flat([], []) == 1.0


def test_escolhe_o_menor_nprobes_que_passa_a_porta() -> None:
    resultados = (
        resultado(128, (1.0, 1.0)),
        resultado(16, (0.90, 0.90)),
        resultado(64, (0.95, 0.95)),
        resultado(32, (0.90, 1.0)),
    )

    assert escolher_nprobes(resultados) == 32
    assert escolher_configuracao(resultados).nprobes == 32


def test_recusa_quando_nenhum_candidato_preserva_recall() -> None:
    assert escolher_nprobes((resultado(64, (0.9,)), resultado(128, (0.94,)))) is None


def test_parse_nprobes_ordena_remove_repetidos_e_recusa_invalidos() -> None:
    assert parse_nprobes("64, 16,64,32") == (16, 32, 64)
    with pytest.raises(ValueError):
        parse_nprobes("0,16")
    with pytest.raises(ValueError):
        parse_nprobes("rápido")
    assert parse_refine("sem, 5,25,5") == (0, 5, 25)
    with pytest.raises(ValueError):
        parse_refine("-2")


def test_medicao_usa_flat_como_referencia_e_varre_as_sondas() -> None:
    class StoreFake:
        def __init__(self) -> None:
            self.chamadas: list[
                tuple[bool | None, int | None, int | None, str | None]
            ] = []

        def buscar_denso(
            self,
            _vetor,
            _k,
            filtro=None,
            model_id=None,
            *,
            usar_ann=None,
            nprobes=None,
            refine_factor=None,
        ):
            self.chamadas.append((usar_ann, nprobes, refine_factor, model_id))
            if usar_ann is False:
                return [AcertoFake("a"), AcertoFake("b")]
            return [AcertoFake("a"), AcertoFake("b" if nprobes == 32 else "x")]

    store = StoreFake()
    vetores = [np.ones(4, dtype=np.float32)]
    resultados = medir(
        store,
        vetores,
        "modelo:4",
        k=2,
        nprobes=(16, 32),
        refine_factors=(0, 5),
    )

    assert [r.recall_medio for r in resultados] == [0.5, 1.0, 0.5, 1.0]
    assert store.chamadas == [
        (False, None, None, "modelo:4"),
        (True, 16, 0, "modelo:4"),
        (True, 32, 0, "modelo:4"),
        (True, 16, 5, "modelo:4"),
        (True, 32, 5, "modelo:4"),
    ]
