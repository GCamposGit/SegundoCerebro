"""A política da quarentena: o que é arquivo podre e o que é máquina apertada.

Saiu de `index/store.py` em 30/08/2026, e é uma das seis costuras que o `Q16`
levantou para aquele arquivo. Não saiu por estética: o `Q15` precisou fazer a
quarentena **ler** o motivo, `store.py` estava no teto exato da escada, e
`tests/test_tamanho_dos_modulos.py` reprovou com a instrução de sempre — *o que
for novo vai em arquivo próprio*.

A distinção que este módulo carrega é a que faltava ao produto. O teto de
tentativas é política de **arquivo podre**: duas falhas e o documento espera os
bytes mudarem, porque insistir num PDF corrompido é gastar a passada. Falha de
**ambiente** é o oposto — a máquina apertada hoje não está apertada amanhã, e o
arquivo é o mesmo. Aposentar por ela tira o documento do acervo até alguém
editá-lo, e é a forma que o `Q15` existe para impedir.

`MOTIVO_RECURSO` era escrito por três sítios e **lido por nenhum**. Um marcador
que ninguém consulta é um comentário caro.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ingest.document import MOTIVO_RECURSO

MAX_TENTATIVAS_QUARENTENA = 2
"""First failure plus one retry after backoff. A third try waits for the bytes to change."""

BACKOFF_QUARENTENA_S = 3600.0
"""One hour, then two. Tests shorten this; a wave of days must not spin on the same PDF."""


@dataclass(frozen=True)
class ItemQuarentena:
    path: str
    hash: str
    motivo: str
    tentativas: int
    ultima_tentativa: str
    proxima_tentativa: str


def por_recurso(motivo: str | None) -> bool:
    """A causa foi a máquina, não o arquivo? É o que `MOTIVO_RECURSO` marca."""
    return (motivo or "").lower().startswith(MOTIVO_RECURSO)


def aposentado(item: ItemQuarentena) -> bool:
    """As tentativas acabaram — e falha de recurso **nunca** acaba.

    Quem falha por ambiente continua respeitando o backoff (não vale insistir de
    imediato), mas nunca sai da fila: a condição que o derrubou é transitória por
    definição, e o teto existe para o caso oposto.
    """
    return not por_recurso(item.motivo) and item.tentativas >= MAX_TENTATIVAS_QUARENTENA
