"""Automatic approximate vector index — R4.1.

The user points at a folder; they do not choose IVF partitions or remember to
retrain an index.  This module turns the dossier's policy into one decision:
below 200k vectors flat search stays honest and cheap, above it an IVF-PQ index
is created, and growth beyond 30% retrains it.

The query path can still bypass the index explicitly.  That is laboratory
surface, not product configuration: recall-vs-flat must compare the ANN answer
with the exact answer over the same table and query vector.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

LIMIAR_ANN = 200_000
CRESCIMENTO_RETREINO = 1.30
NPROBES = 256
CANDIDATOS_REFINO = 10_000
"""Quantidade aproximada reavaliada com os vetores originais.

LanceDB expressa o refino como múltiplo de ``k``. O produto pede 200 candidatos
para a fusão, enquanto a guarda pede 20; fixar o fator em 500 faria a busca real
reavaliar 100 mil vetores — dez vezes a configuração que obteve recall 0,98.
O orçamento absoluto preserva o experimento independentemente do ``k``.
"""
LIMIAR_COMPACTACAO = 100_000
COLUNA_VETOR = "vetor"
TIPO_ANN = "IVFPQ"


@dataclass(frozen=True)
class PlanoANN:
    n_vetores: int
    n_indexados: int
    criar: bool
    motivo: str
    particoes: int = 0
    subvetores: int = 0


def _indice_ann(tabela):  # noqa: ANN001, ANN202
    for indice in tabela.list_indices():
        colunas = tuple(getattr(indice, "columns", ()) or ())
        tipo = str(getattr(indice, "index_type", "") or "").replace("_", "").upper()
        if COLUNA_VETOR in colunas and tipo == TIPO_ANN:
            return indice
    return None


def tem_ann(tabela) -> bool:  # noqa: ANN001
    return _indice_ann(tabela) is not None


def compactar_se_preciso(tabela, modificados: int) -> bool:  # noqa: ANN001
    """Compacta arquivos/versões depois de uma onda realmente grande."""
    if modificados < LIMIAR_COMPACTACAO:
        return False
    # ``optimize`` compacta fragmentos, poda versões com mais de sete dias e
    # incorpora linhas novas aos índices. Não usa ``delete_unverified``: uma
    # passada concorrente já é recusada, mas arquivo recente duvidoso se preserva.
    tabela.optimize()
    return True


def _indexados(indice, n_vetores: int) -> int:  # noqa: ANN001
    direto = getattr(indice, "num_indexed_rows", None)
    if direto is not None:
        return max(0, int(direto))
    fora = getattr(indice, "num_unindexed_rows", None)
    if fora is not None:
        return max(0, n_vetores - int(fora))
    # Versões antigas do LanceDB não expunham a contagem. Preservar o índice é
    # mais seguro que treiná-lo em toda passada sem evidência de crescimento.
    return n_vetores


def _particoes(n_vetores: int) -> int:
    return min(n_vetores, max(1, round(4 * math.sqrt(n_vetores))))


def _subvetores(dim: int) -> int:
    if dim < 1:
        raise ValueError(f"dimensão inválida para ANN: {dim}")
    return dim // 8 if dim % 8 == 0 else 1


def planejar_ann(
    tabela,  # noqa: ANN001 — tipo fica no chamador para não importar o módulo pesado
    dim: int,
    n_vetores: int,
    *,
    limiar: int = LIMIAR_ANN,
    crescimento: float = CRESCIMENTO_RETREINO,
) -> PlanoANN:
    """Decide sem escrever; usado pelo indexador e pelos testes de crescimento."""
    n_vetores = max(0, int(n_vetores))
    if n_vetores < limiar:
        return PlanoANN(n_vetores, 0, False, f"abaixo do limiar de {limiar}")

    indice = _indice_ann(tabela)
    n_indexados = _indexados(indice, n_vetores) if indice is not None else 0
    if indice is None:
        motivo = "índice ANN ausente"
    elif n_vetores > n_indexados * crescimento:
        motivo = f"cresceu mais de {crescimento:.0%} desde {n_indexados} vetores"
    else:
        return PlanoANN(n_vetores, n_indexados, False, "índice ANN vigente")

    return PlanoANN(
        n_vetores=n_vetores,
        n_indexados=n_indexados,
        criar=True,
        motivo=motivo,
        particoes=_particoes(n_vetores),
        subvetores=_subvetores(dim),
    )


def garantir_ann(
    tabela,  # noqa: ANN001 — tipo fica no chamador para não importar o módulo pesado
    dim: int,
    n_vetores: int | None = None,
    *,
    limiar: int = LIMIAR_ANN,
    crescimento: float = CRESCIMENTO_RETREINO,
) -> PlanoANN:
    """Cria ou retreina IVF-PQ quando o plano pede; caso contrário não escreve."""
    total = int(tabela.count_rows()) if n_vetores is None else int(n_vetores)
    plano = planejar_ann(
        tabela,
        dim,
        total,
        limiar=limiar,
        crescimento=crescimento,
    )
    if not plano.criar:
        return plano

    from lancedb.index import IvfPq

    tabela.create_index(
        COLUNA_VETOR,
        config=IvfPq(
            distance_type="cosine",
            num_partitions=plano.particoes,
            num_sub_vectors=plano.subvetores,
        ),
        replace=True,
    )
    return plano


def garantir_no_store(store, n_vetores=None, *, limiar=None):  # noqa: ANN001, ANN201
    """Adapta a política pura à fachada e ao cache do ``Store``."""
    plano = garantir_ann(
        store.tabela,
        store.dim,
        n_vetores,
        limiar=LIMIAR_ANN if limiar is None else limiar,
    )
    store._ann_ativo = tem_ann(store.tabela)
    return plano


def _ativo(store) -> bool:  # noqa: ANN001
    if store._ann_ativo is None:
        store._ann_ativo = tem_ann(store.tabela)
    return store._ann_ativo


def buscar_denso(
    store,  # noqa: ANN001 — tipo fica no chamador para não importar o módulo pesado
    vetor: np.ndarray,
    k: int,
    filtro: str | None = None,
    model_id: str | None = None,
    *,
    usar_ann: bool | None = None,
    nprobes: int | None = None,
    refine_factor: int | None = None,
) -> list:
    """Busca exata ou IVF-PQ sem inflar o módulo histórico ``store.py``."""
    from .store import Acerto
    from .vetores_tipo import recusar_coluna_nao_vetor

    recusar_coluna_nao_vetor(store.tabela, getattr(store, "dim", None))
    consulta = store.tabela.search(
        vetor.astype(np.float32), vector_column_name=COLUNA_VETOR
    ).metric("cosine")
    if usar_ann is False:
        consulta = consulta.bypass_vector_index()
    elif _ativo(store):
        consulta = consulta.nprobes(NPROBES if nprobes is None else nprobes)
        refino = (
            max(1, -(-CANDIDATOS_REFINO // max(1, k)))
            if refine_factor is None
            else refine_factor
        )
        if refino > 0:
            consulta = consulta.refine_factor(refino)
    if model_id:
        escapado = model_id.replace("'", "''")
        filtro = f"model_id = '{escapado}'" + (f" AND ({filtro})" if filtro else "")
    if filtro:
        consulta = consulta.where(filtro, prefilter=True)
    linhas = consulta.limit(k).to_list()
    return [
        Acerto(id=linha["id"], score=1.0 - float(linha.get("_distance", 0.0)), posicao=i)
        for i, linha in enumerate(linhas, start=1)
    ]
