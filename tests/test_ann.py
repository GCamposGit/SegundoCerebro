"""R4.1: ANN is automatic, retrained by growth, and comparable with flat."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from segundocerebro.index.ann import (
    CANDIDATOS_REFINO,
    CRESCIMENTO_RETREINO,
    LIMIAR_COMPACTACAO,
    NPROBES,
    compactar_se_preciso,
    garantir_ann,
    planejar_ann,
)
from segundocerebro.index.store import Store
from tests.falsos import chunk


@dataclass
class IndiceFake:
    name: str = "vetor_idx"
    index_type: str = "IVF_PQ"
    columns: tuple[str, ...] = ("vetor",)
    num_indexed_rows: int | None = None
    num_unindexed_rows: int | None = None


class TabelaFake:
    def __init__(self, n: int, indices=()) -> None:  # noqa: ANN001
        self.n = n
        self.indices = list(indices)
        self.criados: list[tuple] = []
        self.otimizacoes = 0

    def count_rows(self) -> int:
        return self.n

    def list_indices(self):  # noqa: ANN201
        return list(self.indices)

    def create_index(self, coluna, *, config, replace):  # noqa: ANN001, ANN201
        self.criados.append((coluna, config, replace))
        self.indices = [IndiceFake(num_indexed_rows=self.n)]

    def optimize(self) -> None:
        self.otimizacoes += 1


def test_abaixo_do_limiar_fica_flat_sem_consultar_indices() -> None:
    class TabelaSemIndice:
        def list_indices(self):  # noqa: ANN201
            raise AssertionError("índice pequeno não precisa listar manutenção")

    plano = planejar_ann(TabelaSemIndice(), dim=1024, n_vetores=199_999)
    assert not plano.criar
    assert "abaixo do limiar" in plano.motivo


def test_indice_grande_cria_ivfpq_com_a_geometria_do_dossie() -> None:
    tabela = TabelaFake(1_000_000)
    plano = garantir_ann(tabela, dim=1024)

    assert plano.criar
    assert plano.particoes == 4_000
    assert plano.subvetores == 128
    assert len(tabela.criados) == 1
    coluna, config, replace = tabela.criados[0]
    assert coluna == "vetor"
    assert config.distance_type == "cosine"
    assert config.num_partitions == 4_000
    assert config.num_sub_vectors == 128
    assert replace is True


def test_retreina_so_depois_de_crescer_mais_de_trinta_porcento() -> None:
    indice = IndiceFake(num_indexed_rows=1_000_000)
    ainda_vigente = planejar_ann(
        TabelaFake(1_300_000, [indice]), dim=1024, n_vetores=1_300_000
    )
    cresceu = planejar_ann(
        TabelaFake(1_300_001, [indice]), dim=1024, n_vetores=1_300_001
    )

    assert not ainda_vigente.criar
    assert cresceu.criar
    assert CRESCIMENTO_RETREINO == 1.30


def test_compacta_so_depois_de_uma_onda_grande() -> None:
    tabela = TabelaFake(1_000_000)

    assert not compactar_se_preciso(tabela, LIMIAR_COMPACTACAO - 1)
    assert compactar_se_preciso(tabela, LIMIAR_COMPACTACAO)
    assert tabela.otimizacoes == 1


class ConsultaFake:
    def __init__(self) -> None:
        self.pulou = False
        self.sondas: int | None = None
        self.refino: int | None = None

    def metric(self, _metrica):  # noqa: ANN001, ANN201
        return self

    def bypass_vector_index(self):  # noqa: ANN201
        self.pulou = True
        return self

    def nprobes(self, n: int):  # noqa: ANN201
        self.sondas = n
        return self

    def refine_factor(self, n: int):  # noqa: ANN201
        self.refino = n
        return self

    def where(self, _filtro, prefilter=True):  # noqa: ANN001, ARG002, ANN201
        return self

    def limit(self, _k):  # noqa: ANN001, ANN201
        return self

    def to_list(self) -> list:
        return [{"id": "c1", "_distance": 0.1}]


class TabelaBuscaFake:
    def __init__(self) -> None:
        self.consultas: list[ConsultaFake] = []

    def search(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        consulta = ConsultaFake()
        self.consultas.append(consulta)
        return consulta


def test_busca_pode_forcar_flat_e_ann_para_a_guarda_de_recall() -> None:
    store = object.__new__(Store)
    store._tabela = TabelaBuscaFake()
    store._ann_ativo = True
    vetor = np.ones(8, dtype=np.float32)

    store.buscar_denso(vetor, 1, usar_ann=False)
    store.buscar_denso(vetor, 1, usar_ann=True, nprobes=17, refine_factor=9)

    flat, ann = store._tabela.consultas
    assert flat.pulou and flat.sondas is None
    assert not ann.pulou and ann.sondas == 17 and ann.refino == 9


def test_busca_ann_usa_a_configuracao_aprovada_por_padrao() -> None:
    store = object.__new__(Store)
    store._tabela = TabelaBuscaFake()
    store._ann_ativo = True

    store.buscar_denso(np.ones(8, dtype=np.float32), 20)

    consulta = store._tabela.consultas[0]
    assert consulta.sondas == NPROBES == 256
    assert consulta.refino == CANDIDATOS_REFINO // 20 == 500


def test_lancedb_real_cria_ann_e_preserva_busca_flat(tmp_path) -> None:  # noqa: ANN001
    """A API unificada do LanceDB instalado aceita o plano que o produto gera."""
    rng = np.random.default_rng(42)
    matriz = rng.standard_normal((512, 8), dtype=np.float32)
    matriz /= np.linalg.norm(matriz, axis=1, keepdims=True)
    chunks = [chunk(f"c{i}", "base/doc.md", i, f"trecho {i}") for i in range(512)]
    store = Store(tmp_path / "indice", 8)
    try:
        store.gravar_chunks(chunks, list(matriz), mtime=1.0, model_id="falso:8")
        store.commit()
        plano = store.garantir_ann(512, limiar=1)

        assert plano.criar
        indices = list(store.tabela.list_indices())
        assert any(i.index_type.replace("_", "").upper() == "IVFPQ" for i in indices), [
            (i.name, i.index_type, i.columns) for i in indices
        ]
        assert store.buscar_denso(matriz[0], 5, usar_ann=False)
        assert store.buscar_denso(matriz[0], 5, usar_ann=True)
    finally:
        store.fechar()
