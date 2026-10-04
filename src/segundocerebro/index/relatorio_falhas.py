"""Contagem de falhas por extensão, só leitura, quando a passada fechou.

Não recomenda leitor novo. A tabela é o número; a decisão de formato fica
fora daqui. Não lista caminhos: o acervo pode ter nome de arquivo sensível.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ErroDeConfig, carregar
from ..logger import get_logger
from .progresso import ler

log = get_logger("index.relatorio_falhas")

STATUS_CONHECIDOS = (
    "ok",
    "vazio",
    "erro",
    "sem_parser",
    "adiado",
    "travado",
    "placeholder",
    "sumiu",
)
ROTULOS = {
    "ok": "ok",
    "vazio": "sem texto",
    "erro": "erro",
    "sem_parser": "sem leitor",
    "adiado": "adiado",
    "travado": "travado",
    "placeholder": "só na nuvem",
    "sumiu": "sumiu",
    "outros": "outros",
    "quarentena": "quarentena",
}


@dataclass
class Contagem:
    por_status: dict[str, int] = field(default_factory=dict)
    quarentena: int = 0

    def total_falhas(self) -> int:
        falhas = sum(
            n for status, n in self.por_status.items() if status != "ok"
        )
        return falhas + self.quarentena


@dataclass(frozen=True)
class Relatorio:
    base_id: str
    fechada: bool
    linhas: tuple[tuple[str, Contagem], ...]

    @property
    def parcial(self) -> bool:
        return not self.fechada


def extensao_de(caminho: str) -> str:
    nome = caminho.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in nome or (nome.startswith(".") and nome.count(".") == 1):
        return "(sem extensão)"
    sufixo = nome.rsplit(".", 1)[-1].lower()
    return sufixo or "(sem extensão)"


def agrupar(
    documentos: list[tuple[str, str]],
    quarentena: list[str],
) -> tuple[tuple[str, Contagem], ...]:
    grupos: dict[str, Contagem] = {}
    for caminho, status in documentos:
        chave = extensao_de(caminho or "")
        item = grupos.setdefault(chave, Contagem())
        nome = status if status in STATUS_CONHECIDOS else "outros"
        item.por_status[nome] = item.por_status.get(nome, 0) + 1
    for caminho in quarentena:
        grupos.setdefault(extensao_de(caminho or ""), Contagem()).quarentena += 1
    ordem = sorted(
        grupos.items(),
        key=lambda par: (-par[1].total_falhas(), par[0]),
    )
    return tuple(ordem)


def _abrir_somente_leitura(registro: Path) -> sqlite3.Connection:
    conexao = sqlite3.connect(f"{registro.resolve().as_uri()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA query_only=ON")
    return conexao


def _tabelas(conexao: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def ler_contagens(indice: Path) -> tuple[tuple[str, Contagem], ...]:
    registro = indice / "registro.db"
    if not registro.is_file():
        raise ErroDeConfig(f"não há registro.db em {indice}")
    conexao = _abrir_somente_leitura(registro)
    try:
        tabelas = _tabelas(conexao)
        if "documentos" not in tabelas:
            raise ErroDeConfig("o índice não tem a tabela documentos")
        documentos = [
            (str(row["path"] or ""), str(row["status"] or ""))
            for row in conexao.execute("SELECT path, status FROM documentos")
        ]
        quarentena: list[str] = []
        if "quarentena" in tabelas:
            quarentena = [
                str(row["path"] or "")
                for row in conexao.execute("SELECT path FROM quarentena")
            ]
    finally:
        conexao.close()
    return agrupar(documentos, quarentena)


class PassadaAberta(ErroDeConfig):
    """A passada ainda não fechou. Um retrato no meio não é o laudo."""


def montar(base_id: str, indice: Path, *, agora: bool) -> Relatorio:
    progresso = ler(indice)
    status = (progresso or {}).get("status")
    fechada = status == "concluida"
    if not fechada and not agora:
        raise PassadaAberta(status or "sem progresso")
    return Relatorio(base_id, fechada, ler_contagens(indice))


def formatar(relatorio: Relatorio) -> str:
    titulo = "fechada" if relatorio.fechada else "parcial, passada ainda aberta"
    linhas = [
        f"# Falhas por extensão — {relatorio.base_id}",
        "",
        f"Passada: {titulo}.",
        "",
        "Contagem apenas. Esta tabela não escolhe leitor novo.",
        "",
        "| Extensão | " + " | ".join(ROTULOS[nome] for nome in (*STATUS_CONHECIDOS, "outros", "quarentena")) + " |",
        "| --- | " + " | ".join("---" for _ in (*STATUS_CONHECIDOS, "outros", "quarentena")) + " |",
    ]
    if not relatorio.linhas:
        linhas.append("| (nenhuma) | " + " | ".join("0" for _ in (*STATUS_CONHECIDOS, "outros", "quarentena")) + " |")
    for extensao, contagem in relatorio.linhas:
        celulas = [str(contagem.por_status.get(nome, 0)) for nome in STATUS_CONHECIDOS]
        celulas.append(str(contagem.por_status.get("outros", 0)))
        celulas.append(str(contagem.quarentena))
        linhas.append(f"| {extensao} | " + " | ".join(celulas) + " |")
    linhas.append("")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="segundocerebro.index.relatorio_falhas",
        description="Conta falhas por extensão, sem abrir os arquivos",
    )
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--base", required=True, help="id da base")
    parser.add_argument("--out", type=Path, help="markdown de saída; ausente: stdout")
    parser.add_argument(
        "--agora",
        action="store_true",
        help="emite o retrato mesmo com a passada aberta, marcado como parcial",
    )
    args = parser.parse_args(argv)
    try:
        conf = carregar(args.config)
        base = conf.base(args.base)
        relatorio = montar(base.id, base.indice, agora=args.agora)
    except PassadaAberta as erro:
        log.error("a passada ainda não fechou (%s). Use --agora para um retrato parcial.", erro)
        return 3
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    texto = formatar(relatorio)
    if args.out is None:
        sys.stdout.write(texto)
    else:
        args.out.write_text(texto, encoding="utf-8")
        log.info("relatório em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
