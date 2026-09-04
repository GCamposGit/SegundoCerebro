"""Costura a manutenção pós-passada sem aumentar o laço do indexador."""

from __future__ import annotations

from ..logger import get_logger
from .ann import compactar_se_preciso

log = get_logger("index.manutencao")


def manter_indices(store, n_vetores: int, modificados: int) -> None:  # noqa: ANN001
    try:
        incremental = store.otimizar_fts()
        log.info("FTS5 otimizado%s", " · vacuum incremental" if incremental else "")
    except Exception as erro:  # noqa: BLE001 — índice continua consistente
        log.warning("FTS5 não pôde ser otimizado; busca continua disponível: %s", erro)
    try:
        if compactar_se_preciso(store.tabela, modificados):
            log.info("LanceDB compactado após %d vetores modificados", modificados)
        plano = store.garantir_ann(n_vetores)
        if plano.criar:
            log.info(
                "ANN criado: %d vetores · %d partições · %d subvetores (%s)",
                plano.n_vetores,
                plano.particoes,
                plano.subvetores,
                plano.motivo,
            )
    except Exception as erro:  # noqa: BLE001 — índice flat continua correto
        log.warning("ANN não pôde ser atualizado; busca exata continua disponível: %s", erro)
