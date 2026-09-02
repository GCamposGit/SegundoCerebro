"""Ponto de entrada do exportador de vault — comando explícito do usuário.

    py -m segundocerebro.acesso.exportar --base trabalho --destino D:\\vault

Não é ferramenta MCP: escrever no disco é ação do leigo, não do agente.
Não carrega encoder. Não ranqueia. Não sintetiza. Não inicia OCR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import ErroDeConfig, carregar
from ..index.store import Store
from ..logger import get_logger
from ..retrieve.glossario import Glossario
from .documento import LeitorDocumento
from .original import ErroLeitura
from .vault import ErroVault, exportar

log = get_logger("acesso.exportar")

# A tabela de vetores não é aberta: o export lê registro, parse store e menções.
DIM_LEITURA = 8


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="segundocerebro.acesso.exportar",
        description=(
            "Exporta a base (ou uma pasta) como vault Markdown. View one-way: "
            "edições no vault não voltam ao acervo. O destino tem de ficar fora "
            "das raízes indexadas."
        ),
    )
    parser.add_argument("--base", help="qual base (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--indice", type=Path, help="diretório do índice, sobrepõe a base")
    parser.add_argument(
        "--destino", type=Path, required=True,
        help="pasta do vault, obrigatoriamente fora das raízes indexadas",
    )
    parser.add_argument("--pasta", default="", help="subpasta relativa; vazio exporta a base")
    parser.add_argument(
        "--politica", choices=("canonicos", "todos"), default="canonicos",
        help="canonicos = um membro vigente por família; todos = cada arquivo",
    )
    parser.add_argument(
        "--completo", action="store_true",
        help="reescreve todas as notas, mesmo as cuja chave não mudou",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        conf = carregar(args.config)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    diretorio = args.indice or base.indice
    if not diretorio.exists():
        log.error("índice não encontrado em %s — indexe antes de exportar", diretorio)
        return 2

    censo_cfg = base.censo()
    raizes = [Path(r.path) for r in censo_cfg.roots]
    glossario = Glossario.de_arquivo(base.glossario) if base.glossario else Glossario.vazio()
    store = Store(diretorio, DIM_LEITURA)
    try:
        saida = exportar(
            store, args.destino, leitor=LeitorDocumento(store, base), raizes=raizes,
            pasta=args.pasta, politica=args.politica, recursivo=True,
            base=base.id, censo_cfg=censo_cfg, glossario=glossario,
            completo=bool(args.completo),
        )
    except (ErroVault, ErroLeitura) as erro:
        log.error("%s", erro)
        return 2
    except OSError:
        log.error("Não foi possível gravar o vault. Confira o destino e o acesso ao disco.")
        return 1
    finally:
        store.fechar()

    sys.stdout.write(json.dumps(saida, ensure_ascii=False, indent=2) + "\n")
    log.info(
        "vault: %d escritos, %d reusados, %d removidos, %d omitidos → %s",
        len(saida["escritos"]), len(saida["reusados"]),
        len(saida["removidos"]), len(saida["omitidos"]), saida["destino"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
