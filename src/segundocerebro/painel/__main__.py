"""Sobe o painel em 127.0.0.1 e abre o navegador.

    py -m segundocerebro.painel

Só escuta em loopback, e com token na URL. Porta local **não** é porta privada:
qualquer processo da máquina alcança uma porta aberta, e o painel mostra trecho
de documento. O token é a diferença entre "local" e "protegido".
"""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from ..logger import get_logger
from .app import criar_app, gerar_token

log = get_logger("painel")

HOST = "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.painel", description="Painel de ajuste")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--porta", type=int, default=0, help="0 = o sistema escolhe uma livre")
    parser.add_argument("--sem-navegador", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ModuleNotFoundError:  # pragma: no cover - depende do ambiente
        log.error("o painel precisa do `uvicorn` (pip install uvicorn)")
        return 2

    from .medir import Medidor

    # Alvo de **escrita**. A leitura cai para a descoberta enquanto ele não
    # existir, e é o primeiro salvamento que o materializa.
    caminho = args.config or Path("config.toml")
    token = gerar_token()
    medidor = Medidor()
    app = criar_app(
        caminho, medidor=medidor, diagnosticador=medidor.diagnosticar, token=token
    )

    porta = args.porta or _porta_livre()
    url = f"http://{HOST}:{porta}/?token={token}"
    log.info("painel em %s", url)
    if not args.sem_navegador:
        webbrowser.open(url)

    try:
        uvicorn.run(app, host=HOST, port=porta, log_level="warning")
    finally:
        medidor.fechar()
    return 0


def _porta_livre() -> int:
    import socket

    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    raise SystemExit(main())
