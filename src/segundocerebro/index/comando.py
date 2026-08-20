"""Pedido da tela para o indexador — arquivo ao lado do índice, sem IPC.

Pausar, continuar e cancelar não podem morar num socket: fechar o painel não
pode deixar o indexador surdo, e a linha de comando tem que fazer o mesmo sem
o painel instalado. Um arquivo atômico é o mesmo contrato do `progresso.json`.

`pausar` — o indexador termina o documento em voo e espera. O relógio conta
parado, não ativo.
`cancelar` — termina o documento em voo e encerra como `interrompida`.
Ausente — segue.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ..logger import get_logger

log = get_logger("index.comando")

NOME = "comando.txt"
PAUSAR = "pausar"
CANCELAR = "cancelar"
VALIDOS = frozenset({PAUSAR, CANCELAR})


def caminho_de(indice: Path) -> Path:
    return Path(indice) / NOME


def ler(indice: Path) -> str | None:
    alvo = caminho_de(indice)
    if not alvo.exists():
        return None
    try:
        texto = alvo.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return texto if texto in VALIDOS else None


def pedir(indice: Path, acao: str) -> None:
    if acao not in VALIDOS:
        raise ValueError(f"comando desconhecido: {acao}")
    alvo = caminho_de(indice)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_suffix(".txt.tmp")
    tmp.write_text(acao + "\n", encoding="utf-8")
    tmp.replace(alvo)
    log.info("comando '%s' em %s", acao, alvo)


def limpar(indice: Path) -> None:
    caminho_de(indice).unlink(missing_ok=True)


def aguardar(
    indice: Path,
    *,
    relogio: object | None = None,
    publicar: Callable[[str], None] | None = None,
    intervalo: float = 0.4,
) -> bool:
    """Bloqueia enquanto estiver pausado.

    Devolve True se o pedido for cancelar — o laço trata como interrupção.
    """
    anunciou = False
    while True:
        cmd = ler(indice)
        if cmd == CANCELAR:
            return True
        if cmd == PAUSAR:
            if not anunciou:
                log.info("indexação pausada — apague %s para continuar", caminho_de(indice))
                anunciou = True
            if publicar is not None:
                publicar("pausada")
            time.sleep(intervalo)
            marcar = getattr(relogio, "contar_parado", None)
            if callable(marcar):
                marcar(intervalo)
            continue
        return False
