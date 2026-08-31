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
import sys
from pathlib import Path
from typing import Any

from ..config import ErroDeConfig, carregar
from ..logger import get_logger
from ..repositorio import raiz as raiz_do_repositorio

log = get_logger("mcp.registrar")

CHAVE = "mcpServers"
AMBIENTE = {"PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8"}
"""`PYTHONIOENCODING` não é ornamento: sem ele o Windows entrega cp1252 no stdio
e um acento no caminho de um documento corrompe o fluxo do protocolo."""


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
"servidor não conecta": silencioso quanto à causa, que é o pior modo de falha."""


def destino_de(cliente: str) -> Path | None:
    """Onde grava a configuração daquele cliente, ou `None` se não se sabe."""
    modelo = DESTINOS.get(cliente)
    return Path(os.path.expandvars(modelo)) if modelo else None


def entrada_de(
    base,  # noqa: ANN001
    *,
    nomear: bool = True,
    absoluto: bool = False,
    python: str = "py",
) -> dict[str, Any]:
    """`nomear=False` omite `--base`, para a base sintetizada do `census.toml`.

    O id sintético (`padrao`) não é escolha de ninguém: some no dia em que o
    usuário escrever um `config.toml` com bases suas. Um registro que o cite
    quebra nesse dia. Sem a flag, o servidor resolve a base única enquanto ela
    for única e falha com a mensagem certa — "há 2 bases configuradas e nenhuma
    foi escolhida" — quando deixar de ser.

    `absoluto=True` fixa `PYTHONPATH`, `--config` e o diretório de trabalho, para
    cliente que não abre na pasta do projeto.

    `python` é o executável. Neste desktop o `py` do PATH é o 3.11 do sistema;
    o pacote mora no `.venv` 3.12 — sem apontar o venv o cliente sobe um
    interpretador sem as dependências e o handshake falha em silêncio.
    """
    args = ["-m", "segundocerebro.mcp.server"]
    if nomear:
        args += ["--base", base.id]
    ambiente = dict(AMBIENTE)
    comando = python
    if absoluto:
        candidato = Path(python)
        if candidato.exists():
            comando = str(candidato.resolve())
    entrada: dict[str, Any] = {"command": comando, "args": args, "env": ambiente}
    if absoluto:
        ambiente["PYTHONPATH"] = str(RAIZ / "src")
        args += ["--config", str(RAIZ / "config.toml")]
        # `cwd` porque o índice e o conjunto dourado da base podem ser relativos
        # ao config, e resolver isso a partir de system32 daria caminho vazio.
        entrada["cwd"] = str(RAIZ)
    return entrada


def trecho(
    bases,  # noqa: ANN001
    *,
    nomear: bool = True,
    absoluto: bool = False,
    python: str = "py",
) -> dict[str, Any]:
    return {
        CHAVE: {
            b.servidor: entrada_de(b, nomear=nomear, absoluto=absoluto, python=python)
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
) -> tuple[list[str], list[str]]:
    """Mescla no arquivo. Recusa JSON ilegível em vez de apagar o dos outros."""
    existente = _ler_existente(destino)
    novo = trecho(bases, nomear=nomear, absoluto=absoluto, python=python)
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

    # Configuração sintetizada tem uma base só e um id que ninguém escolheu.
    novo = trecho(
        bases,
        nomear=conf.caminho is not None or len(conf.bases) > 1,
        absoluto=args.cliente not in RELATIVO,
        python=args.python,
    )
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
            nomear=conf.caminho is not None or len(conf.bases) > 1,
            absoluto=args.cliente not in RELATIVO,
            python=args.python,
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
