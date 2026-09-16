"""Point `indice` at a verified occurrence-schema directory (FND-01b activation).

Migration writes a new folder and leaves the original untouched. Activation is
the restore-like step: rewrite only the target base's `indice` in config.toml
after the destination is confirmed. Comments and other bases stay as they are.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

from ..config import BASE_UNICA, ErroDeConfig
from ..config import carregar as carregar_config
from ..logger import get_logger
from .backup_io import recusar_indice_ausente
from .backup_manifesto import FalhaDeBackup
from .ocorrencia import usa_ocorrencia
from .trava import TravaDeIndice

log = get_logger("index.ativar_identidade")

ID_BASE = re.compile(r'(?m)^\s*id\s*=\s*(["\'])(.+?)\1')
LINHA_INDICE = re.compile(r"(?m)^(\s*indice\s*=\s*).+$")


class AtivacaoRecusada(FalhaDeBackup):
    """Destination is not safe to publish; config.toml is untouched."""


def ativar(config: Path, destino: Path, *, base_id: str = BASE_UNICA) -> Path:
    """Point `base_id`'s `indice` at `destino`. Returns the previous path."""
    config = config.resolve()
    destino = destino.resolve()
    if not config.is_file():
        raise AtivacaoRecusada(
            f"Não achei {config}.",
            "config_ausente",
            "Passe --config para o config.toml desta máquina.",
        )
    recusar_indice_ausente(destino)
    _recusar_destino(destino)
    if TravaDeIndice(destino).ocupada():
        raise AtivacaoRecusada(
            "O destino está com o indexador em execução.",
            "indice_em_uso",
            "Espere a passada terminar antes de apontar o config.",
        )
    conf = carregar_config(config, validar=True)
    base = next((b for b in conf.bases if b.id == base_id), None)
    if base is None:
        raise ErroDeConfig(
            f"A base '{base_id}' não foi encontrada. Disponíveis: {', '.join(conf.ids)}."
        )
    anterior = base.indice.resolve()
    if anterior == destino:
        log.info("índice da base '%s' já aponta para %s", base_id, destino)
        return anterior
    texto = _apontar(config.read_text(encoding="utf-8"), base_id, _valor_indice(config, destino))
    _escrever_atomico(config, texto)
    log.info(
        "base '%s': indice %s → %s (pasta antiga intacta)",
        base_id,
        anterior,
        destino,
    )
    return anterior


def _recusar_destino(destino: Path) -> None:
    registro = destino / "registro.db"
    con = sqlite3.connect(registro.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not usa_ocorrencia(con):
            raise AtivacaoRecusada(
                "Este destino ainda é o schema legado.",
                "nao_migrado",
                "Rode a migração para uma pasta nova e só então ative.",
            )
        try:
            n = int(con.execute("SELECT count(*) FROM operacoes").fetchone()[0])
        except sqlite3.OperationalError:
            n = 0
        if n:
            raise AtivacaoRecusada(
                "O destino tem journal pendente.",
                "journal_pendente",
                "Não aponte o config para esta pasta.",
            )
    finally:
        con.close()


def _valor_indice(config: Path, destino: Path) -> str:
    try:
        relativo = destino.relative_to(config.parent)
    except ValueError:
        return _toml_string(str(destino))
    return _toml_string(relativo.as_posix())


def _toml_string(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _apontar(texto: str, base_id: str, valor_toml: str) -> str:
    prefixo, *blocos = texto.split("[[base]]")
    if not blocos:
        raise AtivacaoRecusada(
            "O config.toml não declara [[base]].",
            "base_ausente",
            "Declare a base antes de ativar o índice migrado.",
        )
    saida = [prefixo]
    achou = False
    for bloco in blocos:
        match = ID_BASE.search(bloco)
        if match and match.group(2) == base_id:
            novo, n = LINHA_INDICE.subn(rf"\1{valor_toml}", bloco, count=1)
            if n != 1:
                raise AtivacaoRecusada(
                    f"A base '{base_id}' não tem linha indice.",
                    "indice_ausente",
                    "Acrescente indice = \"...\" nessa [[base]] e tente de novo.",
                )
            bloco = novo
            achou = True
        saida.append(bloco)
    if not achou:
        raise AtivacaoRecusada(
            f"A base '{base_id}' não aparece no arquivo.",
            "base_ausente",
            "Confira o id da [[base]] no config.toml.",
        )
    return "[[base]]".join(saida)


def _escrever_atomico(caminho: Path, texto: str) -> None:
    fd, tmp = tempfile.mkstemp(
        prefix=f"{caminho.name}.", suffix=".tmp", dir=str(caminho.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(texto)
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aponta indice da base para o diretório migrado, depois da conferência."
    )
    parser.add_argument("--base", default=BASE_UNICA, help="Base cujo indice será apontado.")
    parser.add_argument("--config", type=Path, required=True, help="config.toml da máquina.")
    parser.add_argument("--destino", type=Path, required=True, help="Pasta nova já migrada.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        anterior = ativar(args.config, args.destino, base_id=args.base)
    except (FalhaDeBackup, ErroDeConfig) as exc:
        print(str(exc), file=sys.stderr)
        acao = getattr(exc, "acao", "")
        if acao:
            print(acao, file=sys.stderr)
        return 2
    print(f"indice anterior: {anterior}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
