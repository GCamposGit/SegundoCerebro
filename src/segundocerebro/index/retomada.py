"""Retomada automática — comportamento previsto, não conserto.

    py -m segundocerebro.index.retomada            # retoma o que ficou pela metade
    py -m segundocerebro.index.retomada --listar   # só diz o que retomaria
    py -m segundocerebro.index.retomada --instalar  # liga a retomada no logon

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
from .indexer import TravaDeIndice
from .progresso import ler

log = get_logger("index.retomada")

INACABADOS = frozenset({"preparando", "indexando", "interrompida", "pausada"})
"""Status que significam "não terminou".

`indexando` gravado num arquivo em repouso é o mais informativo dos três: quer
dizer que o processo morreu **sem** chegar ao `encerrar` — queda de energia,
reinício, processo morto. `interrompida` é Ctrl+C, e é deliberado; retomar
continua sendo o certo, porque a pessoa interrompeu para usar a máquina, não para
abandonar o acervo. `pausada` é o botão do painel: o processo pode ter morrido
no meio da espera."""

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
    """O conteúdo do `.cmd` que roda no logon.

    `cd /d` porque o processo de logon nasce em `C:\\Windows\\system32`, e o
    `PYTHONPATH` relativo do projeto não significa nada de lá.

    `start "" /min` em vez de chamar o Python direto: a retomada pode levar horas,
    e uma janela de console no meio da tela ao ligar o computador seria lida como
    defeito. Minimizada e não oculta de propósito — processo de horas que não
    aparece em lugar nenhum é pior que janela indesejada, porque o usuário não tem
    como parar o que não vê. O primeiro `""` é o título da janela, e omiti-lo faria
    o `start` tratar o caminho do Python como título.

    `SEGUNDOCEREBRO_PROVIDER` é copiado do ambiente de quem instalou — neste
    desktop, `cuda` — para a retomada não cair na CPU depois do reinício.
    Hardware não entra em `model_id`.
    """
    # Sem acento de propósito: `.cmd` é lido na codepage OEM do console (cp850
    # aqui), então UTF-8 sairia como mojibake e `errors="replace"` trocaria o
    # acento por `?`. Escrever o aviso em ASCII puro é o que faz o arquivo dizer o
    # que quer dizer — e ele existe justamente para o usuário que o encontrar
    # sozinho na pasta de inicialização saber o que é e como desligar.
    linhas = [
        "@echo off\r\n",
        "rem Criado pelo Segundo Cerebro. Apagar este arquivo desliga a retomada\r\n",
        "rem automatica da indexacao. Nada e reindexado do zero.\r\n",
        f'cd /d "{raiz}"\r\n',
        "set PYTHONPATH=src\r\n",
    ]
    provider = os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").strip()
    if provider:
        linhas.append(f"set SEGUNDOCEREBRO_PROVIDER={provider}\r\n")
    linhas.append(f'start "" /min "{sys.executable}" -m segundocerebro.index.retomada\r\n')
    return "".join(linhas)


def caminho_do_gatilho() -> Path:
    """Onde o `.cmd` de logon mora.

    **Pasta de inicialização e não tarefa agendada.** O ROADMAP pedia
    `schtasks /SC ONLOGON`, e isso foi tentado no notebook em 19/08/2026:
    **Acesso negado** sem elevação, tanto por `schtasks /SC ONLOGON` quanto por
    `Register-ScheduledTask -AtLogOn`, num Windows 11 Enterprise com política
    corporativa. Criar tarefa `ONCE` no mesmo shell funciona — o impedimento é
    o gatilho de logon, não o agendador. O `.cmd` foi conferido rodando a
    partir de `C:\\Windows\\System32`, que é de onde o processo de logon nasce.

    Exigir administrador para ligar uma conveniência derrubaria o público desta
    tela. A pasta de inicialização é de usuário, dispensa elevação, e tem a
    propriedade que um mecanismo de horas mais precisa: **é um arquivo visível que
    o usuário apaga à mão** se quiser desligar sem abrir o painel.

    Um só mecanismo, não dois com preferência: o mesmo argumento pelo qual este
    módulo recusa um segundo marcador ao lado do `progresso.json` — duas fontes de
    verdade discordam, e a que discorda aparece no pior momento.
    """
    return (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / f"{NOME_DA_TAREFA}.cmd"
    )


def instalada() -> bool | None:
    """O gatilho de logon existe? `None` quando não há como saber.

    Três respostas e não duas, porque "não sei" e "não está instalado" levam a
    telas diferentes: a primeira pede que o usuário confira à mão, a segunda
    oferece o botão de ligar. Colapsar as duas em `False` mostraria "desligado"
    numa máquina onde o gatilho pode estar ligado, e o usuário ligaria de novo.

    Aqui "não sei" é a pasta de inicialização não existir ou não ser legível — o
    caso de outro sistema operacional, e o de perfil de usuário sem ela.
    """
    alvo = caminho_do_gatilho()
    try:
        if not alvo.parent.is_dir():
            return None
        return alvo.is_file()
    except OSError:
        return None


def agendar(*, instalar: bool) -> int:
    """Liga ou desliga o gatilho de logon, escrevendo ou apagando um `.cmd`.

    Mudança que sobrevive à sessão mora atrás de uma flag explícita — nunca
    acontece porque alguém rodou a retomada.

    Desligar o que já está desligado é sucesso, não erro: o usuário pediu um
    estado e o estado é esse. Devolver falha aqui faria o painel mostrar erro
    vermelho para quem clicou em "Desligar" duas vezes.
    """
    raiz = Path(__file__).resolve().parent.parent.parent.parent
    alvo = caminho_do_gatilho()
    try:
        if instalar:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            # `newline=""` porque a linha já traz `\r\n`: sem isso o Python
            # traduziria de novo e o `.cmd` sairia com `\r\r\n`, que o `cmd`
            # interpreta mal.
            with alvo.open("w", encoding="ascii", errors="replace", newline="") as saida:
                saida.write(linha_da_tarefa(raiz))
        else:
            alvo.unlink(missing_ok=True)
    except OSError as erro:
        log.error("não consegui %s '%s': %s", "criar" if instalar else "remover", alvo, erro)
        return 2
    log.info("retomada no logon %s (%s)", "ligada" if instalar else "desligada", alvo)
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
        "--instalar", action="store_true", help="liga a retomada automática no logon"
    )
    parser.add_argument("--desinstalar", action="store_true", help="desliga a retomada no logon")
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
