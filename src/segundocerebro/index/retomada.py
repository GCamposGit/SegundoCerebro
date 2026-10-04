"""Retomada automática — comportamento previsto, não conserto.

    py -m segundocerebro.index.retomada            # retoma o que ficou pela metade
    py -m segundocerebro.index.retomada --listar   # só diz o que retomaria
    py -m segundocerebro.index.retomada --instalar  # liga a retomada no logon

Uma indexação de 39 h atravessa reinício, hibernação e queda de energia. O
ROADMAP promete que isso é previsto: *"registrar status e reindexar na próxima
passada, nunca descartar em silêncio"*. Este módulo é a metade que faltava — a
retomada acontecer **sem alguém lembrar de mandar**.

O `progresso.json` continua sendo o único marcador de status: um run que morreu
sem encerrar deixa `indexando` gravado. A `fila-indexacao.json`, ao lado do
config, não é um segundo status. Ela só guarda a ordem pedida e as flags
(`perfil`, `parse-workers`, `dois-passes`), inclusive de base que ainda não tem
progresso. Sem esse arquivo, o logon segue o scan antigo: só o que ficou pela
metade e com a trava livre.

Nada aqui força indexação: se outro indexador está vivo, a trava manda, e este
módulo sai sem fazer nada. Duas passadas simultâneas duplicariam cada vetor.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import ErroDeConfig, carregar, normalizar_perfil
from ..logger import get_logger
from ..repositorio import em_checkout
from ..repositorio import raiz as raiz_do_repositorio
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


NOME_DA_FILA = "fila-indexacao.json"
"""Fila declarada ao lado do config. Não é progresso: sobrevive a uma base que nunca começou."""

STATUS_CONCLUIDA = "concluida"


@dataclass(frozen=True)
class FilaDeclarada:
    """O que o logon deve continuar, na ordem pedida, com as mesmas flags."""

    bases: tuple[str, ...]
    perfil: str | None = None
    parse_workers: int | None = None
    dois_passes: bool = False


def caminho_da_fila(config: Path) -> Path:
    return Path(config).expanduser().resolve().parent / NOME_DA_FILA


def ler_fila(config: Path) -> FilaDeclarada | None:
    """`None` se ninguém gravou fila. Arquivo presente e inválido é erro, não silêncio."""
    alvo = caminho_da_fila(config)
    if not alvo.is_file():
        return None
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise ErroDeConfig(f"fila ilegível em {alvo.name}: {erro}") from erro
    if not isinstance(dados, dict):
        raise ErroDeConfig(f"fila ilegível em {alvo.name}")
    bases = dados.get("bases")
    if (
        not isinstance(bases, list)
        or not bases
        or not all(isinstance(item, str) and item.strip() for item in bases)
    ):
        raise ErroDeConfig("fila: 'bases' precisa ser uma lista de ids")
    ids = tuple(item.strip() for item in bases)
    if len(ids) != len(set(ids)):
        raise ErroDeConfig("fila: id repetido")
    perfil = dados.get("perfil")
    if perfil is not None and not isinstance(perfil, str):
        raise ErroDeConfig("fila: 'perfil' precisa ser texto")
    workers = dados.get("parse_workers")
    if workers is not None and (isinstance(workers, bool) or not isinstance(workers, int) or workers < 1):
        raise ErroDeConfig("fila: 'parse_workers' precisa ser inteiro >= 1")
    dois = dados.get("dois_passes", False)
    if not isinstance(dois, bool):
        raise ErroDeConfig("fila: 'dois_passes' precisa ser true ou false")
    return FilaDeclarada(ids, perfil.strip() if isinstance(perfil, str) else None, workers, dois)


def gravar_fila(config: Path, fila: FilaDeclarada) -> Path:
    alvo = caminho_da_fila(config)
    payload = {
        "bases": list(fila.bases),
        "perfil": fila.perfil,
        "parse_workers": fila.parse_workers,
        "dois_passes": fila.dois_passes,
    }
    tmp = alvo.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(alvo)
    return alvo


def comando_de_retomada(
    base,  # noqa: ANN001 — config.Base
    caminho_config: Path | None,
    perfil: str,
    *,
    parse_workers: int | None = None,
    dois_passes: bool = False,
) -> list[str]:
    comando = [sys.executable, "-m", "segundocerebro.index.indexer", "--base", base.id]
    if caminho_config is not None:
        comando += ["--config", str(caminho_config)]
    if parse_workers is not None:
        comando += ["--parse-workers", str(parse_workers)]
    if dois_passes:
        comando.append("--dois-passes")
    return comando + ["--perfil", perfil]


def linha_da_tarefa(raiz: Path, config: Path | None = None) -> str:
    """O conteúdo do `.cmd` que roda no logon.

    `cd /d` porque o processo de logon nasce em `C:\\Windows\\system32`, e um
    caminho relativo não significa nada de lá. Ele vai para a pasta **do
    config**, não para a raiz deduzida (`F6`, 30/08/2026): numa instalação por
    `pip` a raiz cai no `site-packages`, e ali a retomada subia, sintetizava a
    base `padrao` sem raiz nenhuma e reindexava o nada — em silêncio, toda vez
    que o usuário liga o computador. O `--config` explícito fecha o mesmo buraco
    que `mcp/registrar.py` acabou de fechar, no arquivo vizinho.

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
    onde = config.parent if config is not None else raiz
    linhas = [
        "@echo off\r\n",
        "rem Criado pelo Segundo Cerebro. Apagar este arquivo desliga a retomada\r\n",
        "rem automatica da indexacao. Nada e reindexado do zero.\r\n",
        f'cd /d "{onde}"\r\n',
    ]
    # `PYTHONPATH` so num checkout (`F6`, 30/08/2026). Este `.cmd` e gravado na
    # pasta de Inicializacao do usuario: e a pior versao de 'codigo que so roda
    # de dentro do repositorio', porque sobrevive ate a desinstalacao do pacote.
    if em_checkout():
        linhas.append("set PYTHONPATH=src\r\n")
    provider = os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").strip()
    if provider:
        linhas.append(f"set SEGUNDOCEREBRO_PROVIDER={provider}\r\n")
    alvo = f' --config "{config}"' if config is not None else ""
    linhas.append(
        f'start "" /min "{sys.executable}" -m segundocerebro.index.retomada{alvo}\r\n'
    )
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


def _config_carregado() -> Path | None:
    """O `config.toml` que esta instalação de fato usa, ou `None`."""
    try:
        return carregar().caminho
    except ErroDeConfig:
        return None


def agendar(*, instalar: bool) -> int:
    """Liga ou desliga o gatilho de logon, escrevendo ou apagando um `.cmd`.

    Mudança que sobrevive à sessão mora atrás de uma flag explícita — nunca
    acontece porque alguém rodou a retomada.

    Desligar o que já está desligado é sucesso, não erro: o usuário pediu um
    estado e o estado é esse. Devolver falha aqui faria o painel mostrar erro
    vermelho para quem clicou em "Desligar" duas vezes.
    """
    raiz = raiz_do_repositorio()
    alvo = caminho_do_gatilho()
    try:
        if instalar:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            # `newline=""` porque a linha já traz `\r\n`: sem isso o Python
            # traduziria de novo e o `.cmd` sairia com `\r\r\n`, que o `cmd`
            # interpreta mal.
            with alvo.open("w", encoding="ascii", errors="replace", newline="") as saida:
                saida.write(linha_da_tarefa(raiz, _config_carregado()))
        else:
            alvo.unlink(missing_ok=True)
    except OSError as erro:
        log.error("não consegui %s '%s': %s", "criar" if instalar else "remover", alvo, erro)
        return 2
    log.info("retomada no logon %s (%s)", "ligada" if instalar else "desligada", alvo)
    return 0


def _perfil_efetivo(pedido: str | None, fila: FilaDeclarada | None, conf) -> str:  # noqa: ANN001
    bruto = pedido or (fila.perfil if fila is not None else None) or conf.maquina.perfil
    return normalizar_perfil(bruto)


def _alguma_trava(conf, ids: tuple[str, ...]) -> str | None:  # noqa: ANN001
    """A primeira base da fila cujo índice está com indexador vivo.

    Uma trava em qualquer base da fila impede abrir outra: duas bases ao mesmo
    tempo dividem a mesma memória. A base ocupada segue com quem já a tem.
    """
    for base_id in ids:
        base = conf.base(base_id)
        if TravaDeIndice(base.indice).ocupada():
            return base_id
    return None


def _rodar_fila(conf, fila: FilaDeclarada, *, listar: bool, somente: str | None, perfil_cli: str | None) -> int:  # noqa: ANN001
    if somente and somente not in fila.bases:
        log.error("base '%s' não está na fila", somente)
        return 2
    try:
        ocupada = _alguma_trava(conf, fila.bases)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    if ocupada:
        log.info("base '%s' já está sendo indexada; a fila espera e não abre outra", ocupada)
        return 0
    perfil = _perfil_efetivo(perfil_cli, fila, conf)
    alvos = [item for item in fila.bases if somente is None or item == somente]
    for base_id in alvos:
        try:
            base = conf.base(base_id)
        except ErroDeConfig as erro:
            log.error("%s", erro)
            return 2
        progresso = ler(base.indice) or {}
        status = progresso.get("status")
        if status == STATUS_CONCLUIDA:
            log.info("base '%s' já concluída", base_id)
            continue
        log.info("fila '%s': status '%s'", base_id, status or "nunca indexada")
        if listar:
            continue
        comando = comando_de_retomada(
            base,
            conf.caminho,
            perfil,
            parse_workers=fila.parse_workers,
            dois_passes=fila.dois_passes,
        )
        log.info("retomando: %s", " ".join(comando))
        resultado = subprocess.run(comando, check=False)  # noqa: S603
        if resultado.returncode != 0:
            log.warning("retomada da base '%s' saiu com código %s", base_id, resultado.returncode)
            return 0
    return 0


def _gravar_fila_cli(args: argparse.Namespace) -> int:
    if not args.bases:
        log.error("gravar a fila exige --bases")
        return 2
    if args.parse_workers is not None and args.parse_workers < 1:
        log.error("parse-workers precisa ser >= 1")
        return 2
    try:
        conf = carregar(args.config)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    if conf.caminho is None:
        log.error("gravar a fila exige --config")
        return 2
    ids = tuple(parte.strip() for parte in args.bases.split(",") if parte.strip())
    if not ids:
        log.error("gravar a fila exige ao menos uma base")
        return 2
    if len(ids) != len(set(ids)):
        log.error("fila: id repetido")
        return 2
    try:
        for base_id in ids:
            conf.base(base_id)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    fila = FilaDeclarada(
        ids,
        args.perfil,
        args.parse_workers,
        bool(args.dois_passes),
    )
    destino = gravar_fila(conf.caminho, fila)
    log.info("fila gravada em %s", destino.name)
    return 0


def _analisador() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="segundocerebro.index.retomada",
        description="Retoma indexações que não terminaram",
    )
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--base", help="só esta base")
    parser.add_argument(
        "--perfil",
        default=None,
        help="esforço da retomada; ausente: o [maquina] perfil salvo nesta máquina",
    )
    parser.add_argument("--listar", action="store_true", help="diz o que faria e sai")
    parser.add_argument(
        "--instalar", action="store_true", help="liga a retomada automática no logon"
    )
    parser.add_argument("--desinstalar", action="store_true", help="desliga a retomada no logon")
    parser.add_argument(
        "--gravar-fila",
        action="store_true",
        help="grava fila-indexacao.json ao lado do config e sai, sem indexar",
    )
    parser.add_argument("--bases", help="ids da fila, separados por vírgula")
    parser.add_argument("--parse-workers", type=int, default=None)
    parser.add_argument(
        "--dois-passes",
        action="store_true",
        help="a fila gravada pede parse e só depois os vetores",
    )
    return parser


def _rodar_pendentes(conf, args: argparse.Namespace) -> int:  # noqa: ANN001
    """O scan antigo: só status inacabado, e uma falha não corta a base seguinte."""
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
        perfil = normalizar_perfil(args.perfil or conf.maquina.perfil)
        comando = comando_de_retomada(
            base,
            conf.caminho,
            perfil,
            parse_workers=args.parse_workers,
            dois_passes=bool(args.dois_passes),
        )
        log.info("retomando: %s", " ".join(comando))
        # Sequencial de propósito: duas bases ao mesmo tempo dividiriam a CPU que
        # o perfil `leve` já limita, e a segunda demoraria o dobro sem ninguém
        # ganhar nada.
        resultado = subprocess.run(comando, check=False)  # noqa: S603
        if resultado.returncode != 0:
            log.warning("retomada da base '%s' saiu com código %s", base.id, resultado.returncode)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _analisador().parse_args(argv)
    if args.instalar or args.desinstalar:
        return agendar(instalar=args.instalar)
    if args.gravar_fila:
        return _gravar_fila_cli(args)
    try:
        conf = carregar(args.config)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    if conf.caminho is not None:
        try:
            fila = ler_fila(conf.caminho)
        except ErroDeConfig as erro:
            log.error("%s", erro)
            return 2
        if fila is not None:
            return _rodar_fila(
                conf, fila, listar=args.listar, somente=args.base, perfil_cli=args.perfil
            )
    return _rodar_pendentes(conf, args)


if __name__ == "__main__":
    raise SystemExit(main())
