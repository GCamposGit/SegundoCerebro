"""Pedido de pausa/cancelamento — arquivo no índice, sem IPC."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.index.comando import CANCELAR, PAUSAR, aguardar, ler, limpar, pedir
from segundocerebro.index.estimativa import Relogio
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import Store
from tests.falsos import DIM, EmbedderFalso, corpus


def test_pedir_e_ler(tmp_path: Path) -> None:
    assert ler(tmp_path) is None
    pedir(tmp_path, PAUSAR)
    assert ler(tmp_path) == PAUSAR
    limpar(tmp_path)
    assert ler(tmp_path) is None


def test_comando_desconhecido_nao_grava(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        pedir(tmp_path, "explodir")
    assert ler(tmp_path) is None


def test_aguardar_cancelar_devolve_true(tmp_path: Path) -> None:
    pedir(tmp_path, CANCELAR)
    assert aguardar(tmp_path, intervalo=0.01) is True


def test_aguardar_sem_comando_nao_bloqueia(tmp_path: Path) -> None:
    assert aguardar(tmp_path, intervalo=0.01) is False


def test_pausa_pedida_conta_como_parado_nao_como_suspensao() -> None:
    r = Relogio()
    r.tique(0.0)
    r.tique(5.0)
    r.contar_parado(12.0, agora=17.0)
    assert r.ativo == pytest.approx(5.0)
    assert r.parado == pytest.approx(12.0)
    assert r.suspensoes == 0


def test_cancelar_antes_da_largada_nao_indexa(tmp_path: Path) -> None:
    """Pedido órfão de uma sessão anterior não pode abortar a próxima.

    O indexador apaga o comando ao entrar. Sem isto, um Cancelar velho
    deixaria toda retomada sair vazia.
    """
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    pedir(store.diretorio, CANCELAR)
    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1, publicar=False)
    assert not progresso.interrompido
    assert progresso.indexados == 2
    store.fechar()


def test_cancelar_durante_a_passada_encerra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from segundocerebro.index.isolamento import parse_isolado as original

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    def parse_e_cancela(path, **kw):
        pedir(store.diretorio, CANCELAR)
        return original(path, **kw)

    monkeypatch.setattr("segundocerebro.index.indexer.parse_isolado", parse_e_cancela)
    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1, publicar=False)
    assert progresso.interrompido
    store.fechar()
