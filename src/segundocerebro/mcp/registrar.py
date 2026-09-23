"""Gera o trecho de `.mcp.json` de cada base.

    py -m segundocerebro.mcp.registrar --base trabalho
    py -m segundocerebro.mcp.registrar --todas --out .mcp.json

Existe porque registrar um servidor MCP é hoje edição de JSON à mão, e esse é o
primeiro degrau de quem não programa — antes de qualquer ajuste fino, antes do
painel. O comando imprime; só grava com `--out`.

**Gravar mescla, nunca substitui.** Um `.mcp.json` costuma ter outros servidores
dentro, e escrever por cima apagaria a configuração de terceiros para resolver a
nossa. As chaves que não são nossas ficam intactas, e o que mudou é relatado.

Sobre isolamento: registrar num cliente **só** a base que aquele contexto deve
alcançar é fronteira dura, porque a ferramenta não existe na sessão do agente.
Registrar as duas e contar que o modelo escolha pela descrição é conveniência.
Ver `ARCHITECTURE.md` §2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ..config import ErroDeConfig, carregar
from ..logger import get_logger
from ..repositorio import em_checkout
from ..repositorio import raiz as raiz_do_repositorio

log = get_logger("mcp.registrar")

CHAVE = "mcpServers"
AMBIENTE_BASE = {"PYTHONIOENCODING": "utf-8"}
"""`PYTHONIOENCODING` não é ornamento: sem ele o Windows entrega cp1252 no stdio
e um acento no caminho de um documento corrompe o fluxo do protocolo."""


def ambiente_do_cliente() -> dict[str, str]:
    """O `env` do registro. `PYTHONPATH` **só** num checkout — `F6`, 30/08/2026.

    Até aqui `PYTHONPATH=src` era gravado sempre, e para quem instalou por `pip`
    ele aponta para uma pasta que não existe. É a mesma classe que o repositório
    já nomeou duas vezes — *código que só roda de dentro do repositório* — e a
    pior versão dela, porque mora no arquivo de configuração do cliente do
    usuário e sobrevive a qualquer conserto no código.

    Quem instalou por `pip` não precisa dele: o pacote está no `site-packages`.
    Quem roda do checkout precisa, e `em_checkout()` é a pergunta que separa
    os dois — ela já existia, e não estava sendo feita aqui.
    """
    ambiente = dict(AMBIENTE_BASE)
    if em_checkout():
        ambiente["PYTHONPATH"] = "src"
    return ambiente


RAIZ = raiz_do_repositorio()
"""Diretório do projeto. Vira caminho absoluto no registro de clientes que não
abrem na pasta dele.

Era `Path(__file__).resolve().parent` quatro vezes, escrito à mão aqui e em mais
três módulos. A conta é a mesma; o que muda é que agora ela tem um nome e um
teste — de dentro de um `site-packages` os quatro saltos caem na raiz do
ambiente, e `segundocerebro.repositorio.em_checkout()` é a pergunta que separa os
dois casos."""

DESTINOS = {
    "claude-desktop": r"%APPDATA%\Claude\claude_desktop_config.json",
}
"""Clientes cujo arquivo de configuração tem lugar fixo e conhecido.

Só entra aqui cliente cujo caminho **e** formato foram conferidos, porque
`--instalar` grava sem perguntar: um caminho adivinhado erraria escrevendo um
arquivo que ninguém lê — falha silenciosa. Quem não está aqui usa `generico` e
cola à mão. O VS Code fica fora de propósito: o `mcp.json` dele chama a seção
`servers`, não `mcpServers`, e o trecho gerado aqui não serve para ele."""

CLIENTES = {
    "claude-code": "Lê `.mcp.json` na pasta do projeto e abre nela — caminho relativo basta.",
    "claude-desktop": DESTINOS["claude-desktop"],
    "generico": "Qualquer cliente MCP por stdio.",
}

RELATIVO = ("claude-code",)
"""Clientes que abrem na pasta do projeto.

Todos os outros nascem em diretório arbitrário — o Claude Desktop começa em
`C:\\Windows\\system32` — e ali `PYTHONPATH=src` não aponta para nada. O servidor
subiria com `ModuleNotFoundError: segundocerebro`, que o cliente mostra como
"servidor nao conecta": silencioso quanto a causa, que e o pior modo de falha.
Num checkout o `PYTHONPATH` absoluto resolve; numa instalacao por `pip` ele nao
e escrito, porque o pacote ja esta no `site-packages` (30/08/2026)."""


SEM_CONFIG = (
    "não há config.toml aqui, e sem ele o servidor sobe com uma base vazia. "
    "Crie um (copie o config.example.toml) ou aponte um com --config."
)


def argumentos_do_registro(conf, args) -> dict[str, Any]:  # noqa: ANN001
    """Os argumentos comuns de `trecho` e `gravar_em` — montados **uma vez**.

    Duas listas iguais divergindo em silêncio é o defeito que o `Q12` mediu sete
    vezes neste repositório, e havia duas aqui.

    Recusa registrar sem config quando o cliente precisa de caminho absoluto
    (`F6`, 30/08/2026). Sem arquivo nenhum, `carregar()` sintetiza uma base
    `padrao` **sem raiz**: o registro escreveria um servidor que sobe, responde e
    não recupera nada. É a porta de entrada calada — o defeito que esta passada
    inteira ataca —, e recusar é o único jeito honesto. `--config census.toml`
    entra aqui pelo `args.config`, que é o caminho que o censo legado não carrega
    no `Config`.
    """
    absoluto = args.cliente not in RELATIVO
    alvo = conf.caminho or args.config
    if absoluto and alvo is None:
        raise ErroDeConfig(SEM_CONFIG)
    return dict(
        nomear=conf.caminho is not None or len(conf.bases) > 1,
        absoluto=absoluto,
        python=args.python,
        config=alvo,
    )


_VAR_PERCENT = re.compile(r"%([^%]+)%")


def expandir_variaveis(modelo: str) -> str:
    """`%APPDATA%` é a forma do Windows. No POSIX, expandvars deixa o literal.

    A barra invertida do modelo também só é separador no Windows. Sem a troca,
    o destino vira um único nome de arquivo debaixo do diretório atual.
    """

    def trocar(achado: re.Match[str]) -> str:
        return os.environ.get(achado.group(1), achado.group(0))

    expandido = _VAR_PERCENT.sub(trocar, modelo)
    if os.name != "nt":
        expandido = expandido.replace("\\", "/")
    return os.path.expandvars(expandido)


def destino_de(cliente: str) -> Path | None:
    """Onde grava a configuração daquele cliente, ou `None` se não se sabe."""
    modelo = DESTINOS.get(cliente)
    return Path(expandir_variaveis(modelo)) if modelo else None


def entrada_de(
    base,  # noqa: ANN001
    *,
    nomear: bool = True,
    absoluto: bool = False,
    python: str = "py",
    config: Path | None = None,
) -> dict[str, Any]:
    """`nomear=False` omite `--base`, para a base sintetizada do `census.toml`.

    O id sintético (`padrao`) não é escolha de ninguém: some no dia em que o
    usuário escrever um `config.toml` com bases suas. Um registro que o cite
    quebra nesse dia. Sem a flag, o servidor resolve a base única enquanto ela
    for única e falha com a mensagem certa — "há 2 bases configuradas e nenhuma
    foi escolhida" — quando deixar de ser.

    `absoluto=True` fixa `--config` e o diretório de trabalho, para cliente que
    não abre na pasta do projeto. `config` é o arquivo que o usuário **de fato**
    carregou: até 30/08/2026 era `RAIZ/config.toml` e o `cwd` era a raiz do
    repositório — para quem instalou por `pip`, os dois apontam para dentro do
    `site-packages`. O índice é relativo ao **config**, não ao repositório.

    `python` é o executável. Neste desktop o `py` do PATH é o 3.11 do sistema;
    o pacote mora no `.venv` 3.12 — sem apontar o venv o cliente sobe um
    interpretador sem as dependências e o handshake falha em silêncio.
    """
    args = ["-m", "segundocerebro.mcp.server"]
    if nomear:
        args += ["--base", base.id]
    ambiente = ambiente_do_cliente()
    comando = python
    if absoluto:
        candidato = Path(python)
        if candidato.exists():
            comando = str(candidato.resolve())
    entrada: dict[str, Any] = {"command": comando, "args": args, "env": ambiente}
    if absoluto:
        if em_checkout():
            ambiente["PYTHONPATH"] = str(RAIZ / "src")
        # Sem config declarado e fora de um checkout, `RAIZ` e o site-packages:
        # apontar para la faz o servidor levantar "configuracao nao encontrada".
        # Melhor nao escrever nada e deixar o cliente descobrir (30/08/2026).
        alvo = Path(config).resolve() if config else (RAIZ / "config.toml" if em_checkout() else None)
        if alvo is not None:
            args += ["--config", str(alvo)]
            # `cwd` porque o índice e o dourado podem ser relativos ao config —
            # e é ao **config**, não ao repositório, que eles são relativos.
            entrada["cwd"] = str(alvo.parent)
    return entrada


def trecho(
    bases,  # noqa: ANN001
    *,
    nomear: bool = True,
    absoluto: bool = False,
    python: str = "py",
    config: Path | None = None,
) -> dict[str, Any]:
    return {
        CHAVE: {
            b.servidor: entrada_de(
                b, nomear=nomear, absoluto=absoluto, python=python, config=config
            )
            for b in bases
        }
    }


def mesclar(existente: dict[str, Any], novo: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Devolve o documento mesclado, o que foi acrescentado e o que foi trocado."""
    saida = dict(existente)
    servidores = dict(saida.get(CHAVE) or {})
    acrescentados, trocados = [], []
    for nome, entrada in novo[CHAVE].items():
        if nome not in servidores:
            acrescentados.append(nome)
        elif servidores[nome] != entrada:
            trocados.append(nome)
        servidores[nome] = entrada
    saida[CHAVE] = servidores
    return saida, acrescentados, trocados


def python_do_projeto(*, relativo: bool = True) -> str:
    """O interpretador da instalação, não o `py` do PATH.

    Neste desktop o `py` é o 3.11 do sistema e o pacote mora no `.venv` 3.12.
    Registrar `py` faz o cliente subir um interpretador sem dependências e o
    handshake falha em silêncio.
    """
    for candidato in (RAIZ / ".venv" / "Scripts" / "python.exe", RAIZ / ".venv" / "bin" / "python"):
        if candidato.exists():
            if relativo:
                return str(candidato.relative_to(RAIZ)).replace("\\", "/")
            return str(candidato.resolve())
    return sys.executable


def extra_env_hardware(conf: Any = None, existente: dict[str, Any] | None = None) -> dict[str, str]:
    """Provider de embedding (cuda/cpu) — hardware, não entra em `model_id`.

    Ordem: variável de ambiente, `[maquina] provider`, o que já estiver num
    `segundocerebro-*` do arquivo. Sem isto a base nova no desktop subiria em
    CPU com o índice feito em GPU, ou o contrário no notebook.
    """
    provider = (os.environ.get("SEGUNDOCEREBRO_PROVIDER") or "").strip()
    if not provider and conf is not None:
        provider = (getattr(getattr(conf, "maquina", None), "provider", None) or "").strip()
    if not provider and existente:
        for nome, entrada in (existente.get(CHAVE) or {}).items():
            if str(nome).startswith("segundocerebro"):
                herdado = ((entrada or {}).get("env") or {}).get("SEGUNDOCEREBRO_PROVIDER")
                if herdado:
                    provider = str(herdado).strip()
                    break
    return {"SEGUNDOCEREBRO_PROVIDER": provider} if provider else {}


def _ler_existente(destino: Path) -> dict[str, Any]:
    if not destino.exists():
        return {}
    try:
        return json.loads(destino.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ErroDeConfig(
            f"{destino} não é JSON válido ({erro}) — não vou sobrescrever"
        ) from erro


def gravar_em(
    destino: Path,
    bases: Any,
    *,
    nomear: bool = True,
    absoluto: bool = False,
    python: str = "py",
    extra_env: dict[str, str] | None = None,
    config: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Mescla no arquivo. Recusa JSON ilegível em vez de apagar o dos outros."""
    existente = _ler_existente(destino)
    novo = trecho(bases, nomear=nomear, absoluto=absoluto, python=python, config=config)
    extra = dict(extra_env or {})
    if extra:
        for entrada in novo[CHAVE].values():
            env = dict(entrada.get("env") or {})
            env.update({k: v for k, v in extra.items() if v})
            entrada["env"] = env
    mesclado, acrescentados, trocados = mesclar(existente, novo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    temporario.write_text(
        json.dumps(mesclado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporario.replace(destino)
    return acrescentados, trocados


def ativar(base: Any, *, conf: Any, destino: Path | None = None) -> Path:
    """Liga a base no `.mcp.json` do projeto. Idempotente.

    Indexar uma base nova e esquecer este degrau deixa o índice pronto e o
    assistente cego. O painel 'conectar' era o passo humano; agora a passada
    completa registra sozinha.
    """
    if destino is None:
        raiz = conf.caminho.parent if getattr(conf, "caminho", None) else RAIZ
        destino = raiz / ".mcp.json"
    existente = _ler_existente(destino) if destino.exists() else {}
    acrescentados, trocados = gravar_em(
        destino,
        [base],
        nomear=True,
        absoluto=False,
        python=python_do_projeto(relativo=True),
        extra_env=extra_env_hardware(conf, existente),
        config=getattr(conf, "caminho", None),
    )
    log.info(
        "MCP da base '%s' em %s: %s",
        base.id,
        destino,
        "já estava" if not acrescentados and not trocados else (
            "acrescentado" if acrescentados else "atualizado"
        ),
    )
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="segundocerebro.mcp.registrar",
        description="Gera o trecho de .mcp.json para registrar uma base num cliente MCP",
    )
    parser.add_argument("--base", help="qual base registrar")
    parser.add_argument(
        "--todas",
        action="store_true",
        help="registra todas as bases — conveniência, não isolamento: o agente passa a "
        "enxergar as duas e escolhe pela descrição",
    )
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--out", type=Path, help="grava mesclando no arquivo, em vez de imprimir")
    parser.add_argument(
        "--instalar",
        action="store_true",
        help="grava direto no arquivo de configuração do cliente, quando ele tem lugar fixo "
        "e conhecido. Equivale a --out com o caminho certo já resolvido",
    )
    parser.add_argument(
        "--cliente",
        choices=sorted(CLIENTES),
        default="claude-code",
        help="para quem é o trecho. Fora do claude-code os caminhos saem absolutos, "
        "porque o cliente não abre na pasta do projeto",
    )
    parser.add_argument(
        "--python",
        default="py",
        help="executável do servidor. Passe o python do .venv quando o `py` do "
        "PATH não for o da instalação (caso deste desktop: sistema 3.11, venv 3.12)",
    )
    args = parser.parse_args(argv)

    if args.instalar:
        if args.out is not None:
            log.error("--instalar e --out escolhem o mesmo arquivo; use um dos dois")
            return 2
        args.out = destino_de(args.cliente)
        if args.out is None:
            log.error(
                "não sei onde %s guarda a configuração — imprima sem --instalar e cole em: %s",
                args.cliente,
                CLIENTES[args.cliente],
            )
            return 2
        # Criar a pasta seria escrever configuração para um app que não está aqui,
        # e o arquivo ficaria órfão sem ninguém avisar.
        if not args.out.parent.is_dir():
            log.error("%s não existe — %s não parece instalado nesta máquina", args.out.parent, args.cliente)
            return 2

    try:
        conf = carregar(args.config)
        bases = conf.bases if args.todas else (conf.base(args.base),)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    try:
        comum = argumentos_do_registro(conf, args)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    novo = trecho(bases, **comum)
    if args.cliente not in RELATIVO:
        log.info("cole em: %s", CLIENTES[args.cliente])

    if args.out is None:
        print(json.dumps(novo, indent=2, ensure_ascii=False))
        return 0

    try:
        existente = _ler_existente(args.out)
        acrescentados, trocados = gravar_em(
            args.out,
            bases,
            **comum,
            extra_env=extra_env_hardware(conf, existente),
        )
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    escrito = json.loads(args.out.read_text(encoding="utf-8"))
    preservados = sorted(set(escrito[CHAVE]) - {b.servidor for b in bases})
    log.info(
        "%s: %d acrescentado(s)%s, %d atualizado(s)%s, %d preservado(s)%s",
        args.out,
        len(acrescentados),
        f" ({', '.join(acrescentados)})" if acrescentados else "",
        len(trocados),
        f" ({', '.join(trocados)})" if trocados else "",
        len(preservados),
        f" ({', '.join(preservados)})" if preservados else "",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
