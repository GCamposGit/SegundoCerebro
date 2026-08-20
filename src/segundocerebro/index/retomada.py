"""Retomada automática — comportamento previsto, não conserto.

    py -m segundocerebro.index.retomada            # retoma o que ficou pela metade
    py -m segundocerebro.index.retomada --listar   # só diz o que retomaria
    py -m segundocerebro.index.retomada --instalar  # tarefa agendada no logon

Uma indexação de 39 h atravessa reinício, hibernação e queda de energia. O
ROADMAP promete que isso é previsto: *"registrar status e reindexar na próxima
passada, nunca descartar em silêncio"*. Este módulo é a metade que faltava — a
retomada acontecer **sem alguém lembrar de mandar**.

**Não há marcador novo.** O `progresso.json` já é o marcador: ele fica no disco com
o status final, e um run que morreu sem encerrar deixa `indexando` gravado.
Inventar um segundo arquivo criaria duas fontes de verdade que podem discordar —
e a que discorda é sempre descoberta no pior momento.

Nada aqui força indexação: se outro indexador está vivo, a trava manda, e este
módulo sai sem fazer nada. Duas passadas simultâneas duplicariam cada vetor.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from ..config import ErroDeConfig, carregar
from ..logger import get_logger
from .indexer import NOME_DA_TRAVA, TravaDeIndice
from .progresso import ler

log = get_logger("index.retomada")

INACABADOS = frozenset({"preparando", "indexando", "interrompida", "pausada"})
"""Status que significam "não terminou".

`indexando` gravado num arquivo em repouso é o mais informativo dos três: quer
dizer que o processo morreu **sem** chegar ao `encerrar` — queda de energia,
reinício, processo morto. `interrompida` é Ctrl+C, e é deliberado; retomar
continua sendo o certo, porque a pessoa interrompeu para usar a máquina, não para
abandonar o acervo."""

NOME_DA_TAREFA = "SegundoCerebro-retomar-indexacao"


def pendente(base) -> dict | None:  # noqa: ANN001 — config.Base
    """O progresso de um run inacabado desta base, ou `None`.

    Base sendo indexada agora **não** é pendente: alguém já está cuidando dela, e
    disparar um segundo indexador é o único jeito de corromper o índice.
    """
    if TravaDeIndice(base.indice).ocupada():
        return None
    progresso = ler(base.indice)
    if progresso is None or progresso.get("status") not in INACABADOS:
        return None
    return progresso


def pendentes(conf) -> list[tuple[object, dict]]:  # noqa: ANN001 — config.Config
    return [(b, p) for b in conf.bases if (p := pendente(b)) is not None]


def comando_de_retomada(base, caminho_config: Path | None, perfil: str) -> list[str]:  # noqa: ANN001
    comando = [sys.executable, "-m", "segundocerebro.index.indexer", "--base", base.id]
    if caminho_config is not None:
        comando += ["--config", str(caminho_config)]
    return comando + ["--perfil", perfil]


def linha_da_tarefa(raiz: Path) -> str:
    """O comando que a tarefa agendada roda no logon.

    `cmd /c` com `cd` porque a tarefa nasce em `C:\\Windows\\system32`, e o
    `PYTHONPATH` relativo do projeto não significa nada de lá. O `src` sai
    absoluto pela mesma razão. `SEGUNDOCEREBRO_PROVIDER` é copiado do ambiente
    de quem instalou — neste desktop, `cuda` — para a retomada não cair na CPU
    depois do reinício.
    """
    src = raiz / "src"
    partes = [f'cd /d "{raiz}"', f'set PYTHONPATH={src}']
    provider = os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").strip()
    if provider:
        partes.append(f"set SEGUNDOCEREBRO_PROVIDER={provider}")
    partes.append(f'"{sys.executable}" -m segundocerebro.index.retomada')
    return "cmd /c \"" + " && ".join(partes) + "\""


def tarefa_instalada() -> bool:
    """A tarefa de logon existe? `schtasks` ausente (não-Windows) é 'não'."""
    try:
        bruto = subprocess.run(
            ["schtasks", "/Query", "/TN", NOME_DA_TAREFA],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return bruto.returncode == 0


def agendar(*, instalar: bool) -> int:
    """Cria ou remove a tarefa de logon, via `schtasks`.

    Mexer no agendador do sistema é mudança que sobrevive à sessão, então mora
    atrás de uma flag explícita — nunca acontece porque alguém rodou a retomada.
    """
    raiz = Path(__file__).resolve().parent.parent.parent.parent
    if instalar:
        comando = [
            "schtasks", "/Create", "/F",
            "/TN", NOME_DA_TAREFA,
            "/TR", linha_da_tarefa(raiz),
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
        ]
    else:
        comando = ["schtasks", "/Delete", "/F", "/TN", NOME_DA_TAREFA]

    resultado = subprocess.run(comando, check=False, capture_output=True)  # noqa: S603
    if resultado.returncode != 0:
        detalhe = (resultado.stderr or resultado.stdout).decode("oem", errors="replace").strip()
        log.error("schtasks falhou: %s", detalhe)
        return 2
    log.info("tarefa '%s' %s", NOME_DA_TAREFA, "criada" if instalar else "removida")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="segundocerebro.index.retomada",
        description="Retoma indexações que não terminaram",
    )
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--base", help="só esta base")
    parser.add_argument("--perfil", default="leve", help="esforço da retomada (padrão: leve)")
    parser.add_argument("--listar", action="store_true", help="diz o que faria e sai")
    parser.add_argument(
        "--instalar", action="store_true", help="cria a tarefa agendada do Windows no logon"
    )
    parser.add_argument("--desinstalar", action="store_true", help="remove a tarefa agendada")
    args = parser.parse_args(argv)

    if args.instalar or args.desinstalar:
        return agendar(instalar=args.instalar)

    try:
        conf = carregar(args.config)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    bases = [b for b in conf.bases if not args.base or b.id == args.base]
    lista = [(b, p) for b in bases if (p := pendente(b)) is not None]

    if not lista:
        # Sair em silêncio e com sucesso importa: isto roda a cada logon, e um
        # erro no caso normal treina o usuário a ignorar o aviso.
        log.info("nada a retomar")
        return 0

    for base, progresso in lista:
        feitos = progresso.get("documentos", {}).get("feitos", "?")
        totais = progresso.get("documentos", {}).get("totais", "?")
        log.info(
            "base '%s': %s de %s documentos, status '%s', faltavam %s",
            base.id,
            feitos,
            totais,
            progresso.get("status"),
            progresso.get("restante", "?"),
        )
        if args.listar:
            continue
        comando = comando_de_retomada(base, conf.caminho, args.perfil)
        log.info("retomando: %s", " ".join(comando))
        # Sequencial de propósito: duas bases ao mesmo tempo dividiriam a CPU que
        # o perfil `leve` já limita, e a segunda demoraria o dobro sem ninguém
        # ganhar nada.
        resultado = subprocess.run(comando, check=False)  # noqa: S603
        if resultado.returncode != 0:
            log.warning("retomada da base '%s' saiu com código %s", base.id, resultado.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
