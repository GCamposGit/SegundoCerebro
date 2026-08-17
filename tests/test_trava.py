"""Trava de indexação — e o reuso de PID depois de reinício.

Dois indexadores no mesmo diretório duplicam cada vetor: o SQLite em WAL tolera a
concorrência, o LanceDB não. Foi medido uma vez como 13.458 vetores para 7.214
chunks, sem nada levantar erro. A trava remove a classe inteira de falha — desde
que ela saiba distinguir o dono de um PID reciclado.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from segundocerebro.index.indexer import NOME_DA_TRAVA, TravaDeIndice, TravaOcupada


def test_trava_e_liberada_na_saida(tmp_path: Path) -> None:
    with TravaDeIndice(tmp_path):
        assert (tmp_path / NOME_DA_TRAVA).exists()
    assert not (tmp_path / NOME_DA_TRAVA).exists()


def test_trava_liberada_mesmo_com_excecao(tmp_path: Path) -> None:
    """Queda no meio não pode deixar o índice trancado para sempre."""
    with pytest.raises(RuntimeError):
        with TravaDeIndice(tmp_path):
            raise RuntimeError("indexação estourou")
    assert not (tmp_path / NOME_DA_TRAVA).exists()


def test_processo_vivo_bloqueia(tmp_path: Path) -> None:
    with TravaDeIndice(tmp_path):
        with pytest.raises(TravaOcupada, match="outro indexador"):
            TravaDeIndice(tmp_path).__enter__()


def test_marca_carrega_pid_e_criacao(tmp_path: Path) -> None:
    with TravaDeIndice(tmp_path):
        marca = (tmp_path / NOME_DA_TRAVA).read_text(encoding="utf-8")

    pid, _, criacao = marca.partition(",")
    assert int(pid) == os.getpid()
    assert criacao, "sem o instante de criação, PID reciclado passa por dono"


def test_pid_reciclado_nao_passa_por_dono(tmp_path: Path) -> None:
    """O caso que o PID sozinho não pega.

    Depois de reiniciar, o sistema reaproveita números. A trava aponta para um PID
    que existe — mas é outro processo, nascido depois. Sem o instante de criação,
    o usuário levaria "outro indexador está escrevendo" com nenhum rodando, e o
    conserto seria apagar à mão um arquivo que ele não sabe que existe.
    """
    trava = tmp_path / NOME_DA_TRAVA
    # PID deste processo, mas nascido em 1970: só pode ser um homônimo.
    trava.write_text(f"{os.getpid()},1.000", encoding="utf-8")

    with TravaDeIndice(tmp_path):  # assume, em vez de recusar
        assert trava.read_text(encoding="utf-8").startswith(str(os.getpid()))


def test_pid_morto_libera(tmp_path: Path) -> None:
    (tmp_path / NOME_DA_TRAVA).write_text("999999,1.000", encoding="utf-8")
    with TravaDeIndice(tmp_path):
        pass
    assert not (tmp_path / NOME_DA_TRAVA).exists()


def test_formato_antigo_sem_criacao_e_tratado_como_vivo(tmp_path: Path) -> None:
    """Trava escrita pela versão anterior: sem instante, supor vivo é o lado seguro.

    O preço é uma trava a apagar à mão; o outro lado seria dois indexadores
    duplicando cada vetor.
    """
    (tmp_path / NOME_DA_TRAVA).write_text(str(os.getpid()), encoding="utf-8")

    with pytest.raises(TravaOcupada):
        TravaDeIndice(tmp_path).__enter__()


def test_trava_ilegivel_nao_impede_para_sempre(tmp_path: Path) -> None:
    """Arquivo corrompido não pode ser sentença perpétua sobre o índice."""
    (tmp_path / NOME_DA_TRAVA).write_text("lixo", encoding="utf-8")
    with TravaDeIndice(tmp_path):
        pass
