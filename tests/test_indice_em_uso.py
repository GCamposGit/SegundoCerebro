"""Suíte recusa índice em escrita — não espera 15 s por consulta em silêncio."""

from __future__ import annotations

import os

import pytest

from segundocerebro.index.store import IndiceEmEscrita, indexacao_viva, recusar_se_indexando


def test_sem_trava_nao_recusa(tmp_path) -> None:
    recusar_se_indexando(tmp_path)
    assert not indexacao_viva(tmp_path)


def test_trava_de_processo_morto_nao_recusa(tmp_path) -> None:
    (tmp_path / "indexacao.lock").write_text("1\n", encoding="utf-8")
    recusar_se_indexando(tmp_path)
    assert not indexacao_viva(tmp_path)


def test_trava_deste_processo_recusa_com_comando_txt(tmp_path) -> None:
    (tmp_path / "indexacao.lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    with pytest.raises(IndiceEmEscrita, match="pausar") as erro:
        recusar_se_indexando(tmp_path)
    assert "comando.txt" in str(erro.value)
    assert indexacao_viva(tmp_path)


def test_journal_pendente_sem_trava_nao_e_indice_em_escrita(tmp_path) -> None:
    """FND-02b: unfinished write is recovered, not treated as a live indexer."""
    recusar_se_indexando(tmp_path)
    assert not indexacao_viva(tmp_path)
