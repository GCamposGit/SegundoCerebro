"""Migrate a path-PK index to occurrence identity in a new directory (FND-01b).

Writes a new folder. The original is not modified and is not pointed at.
Pending journal rows refuse the run. Activation is a separate step, like
restore: change `indice` in config.toml only after verification.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from ..config import BASE_UNICA, ErroDeConfig
from ..config import carregar as carregar_config
from ..logger import get_logger
from .backup_io import (
    copiar_arvore,
    copiar_sqlite,
    destino_exclusivo,
    recusar_indice_ausente,
    recusar_sobreposto,
    trava_de_backup,
)
from .backup_manifesto import FalhaDeBackup
from .esquema import COLUNAS_DOCUMENTOS, DOCUMENTOS_V2_CREATE, SCHEMA_VERSAO
from .ocorrencia import id_de, usa_ocorrencia

log = get_logger("index.migrar_identidade")

PASTA_PARSE_STORE = "parse_store"

TABELAS_CONTAGEM = (
    "documentos",
    "chunks",
    "mencoes",
    "quarentena",
    "medicoes",
    "execucoes",
)


class MigracaoRecusada(FalhaDeBackup):
    """Precondition failed; the original index is untouched."""


def migrar(origem: Path, destino: Path) -> dict[str, int]:
    """Copy `origem` into `destino` with `ocorrencia_id` as document PK."""
    origem = origem.resolve()
    destino = destino.resolve()
    recusar_sobreposto(origem, destino)
    recusar_indice_ausente(origem)
    with trava_de_backup(origem):
        _recusar_origem(origem)
        with destino_exclusivo(destino) as tmp:
            copiar_sqlite(origem / "registro.db", tmp / "registro.db")
            _copiar_opcionais(origem, tmp)
            _transformar(tmp / "registro.db")
            conferidas = _conferir(origem, tmp)
    log.info(
        "migração publicada: %d documento(s) em %s (original intacto)",
        conferidas["documentos"],
        destino,
    )
    return conferidas


def _recusar_origem(origem: Path) -> None:
    con = sqlite3.connect((origem / "registro.db").resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if usa_ocorrencia(con):
            raise MigracaoRecusada(
                "Este índice já usa identidade por ocorrência.",
                "ja_migrado",
                "Aponte `indice` para esta pasta se ela já for o destino da migração.",
            )
        if _contar(con, "operacoes") > 0:
            raise MigracaoRecusada(
                "Há uma escrita de índice interrompida (journal pendente).",
                "journal_pendente",
                "Deixe o indexador recuperar a operação, ou restaure um backup consistente.",
            )
    finally:
        con.close()


def _copiar_opcionais(origem: Path, tmp: Path) -> None:
    lance = origem / "vetores.lance"
    if lance.is_dir():
        copiar_arvore(lance, tmp / "vetores.lance")
    parse = origem / PASTA_PARSE_STORE
    if parse.is_dir():
        copiar_arvore(parse, tmp / PASTA_PARSE_STORE)


def _transformar(registro: Path) -> None:
    con = sqlite3.connect(registro)
    con.row_factory = sqlite3.Row
    try:
        if usa_ocorrencia(con):
            raise MigracaoRecusada(
                "A cópia já estava no schema novo; recusando publicar.",
                "ja_migrado",
                "Não ative este destino; o índice original permanece no lugar.",
            )
        _recriar_documentos(con)
        _preencher_raizes(con)
        _estampar_v2(con)
        con.commit()
    finally:
        con.close()


def _recriar_documentos(con: sqlite3.Connection) -> None:
    presentes = {str(r["name"]) for r in con.execute("PRAGMA table_info(documentos)")}
    colunas = [c for c in COLUNAS_DOCUMENTOS if c in presentes]
    if "path" not in presentes or "raiz" not in presentes:
        raise MigracaoRecusada(
            "O registro legado não tem path e raiz; não dá para derivar ocorrência.",
            "schema_ilegivel",
            "Restaure um backup anterior e tente de novo.",
        )
    linhas = list(con.execute(f"SELECT {', '.join(colunas)} FROM documentos"))
    con.execute("ALTER TABLE documentos RENAME TO documentos_legado")
    con.execute("DROP INDEX IF EXISTS idx_documentos_sha256")
    con.executescript(DOCUMENTOS_V2_CREATE)
    _inserir_v2(con, colunas, linhas)
    con.execute("DROP TABLE documentos_legado")
    con.execute("CREATE INDEX IF NOT EXISTS idx_documentos_sha256 ON documentos(sha256)")


def _inserir_v2(
    con: sqlite3.Connection,
    colunas: list[str],
    linhas: list[sqlite3.Row],
) -> None:
    dest = ("ocorrencia_id", "root_id", *colunas)
    marcas = ", ".join("?" * len(dest))
    sql = f"INSERT INTO documentos ({', '.join(dest)}) VALUES ({marcas})"
    for row in linhas:
        dados = {c: row[c] for c in colunas}
        rel = str(dados["path"])
        root_id = str(dados["raiz"])
        oid = id_de(root_id, rel)
        dados["raiz"] = root_id
        con.execute(sql, (oid, root_id, *[dados[c] for c in colunas]))


def _preencher_raizes(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS raizes ("
        "root_id TEXT PRIMARY KEY, "
        "rotulo TEXT NOT NULL DEFAULT '', "
        "caminho_atual TEXT NOT NULL DEFAULT '')"
    )
    con.execute(
        "INSERT OR IGNORE INTO raizes (root_id, rotulo) "
        "SELECT DISTINCT root_id, root_id FROM documentos"
    )


def _estampar_v2(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)"
    )
    con.execute(
        "INSERT INTO meta (chave, valor) VALUES ('schema_versao', ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (SCHEMA_VERSAO,),
    )


def _conferir(origem: Path, tmp: Path) -> dict[str, int]:
    src = sqlite3.connect((origem / "registro.db").resolve().as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(tmp / "registro.db")
    src.row_factory = sqlite3.Row
    dst.row_factory = sqlite3.Row
    try:
        antes = _contagens(src)
        depois = _contagens(dst)
        if antes != {k: depois[k] for k in antes}:
            raise MigracaoRecusada(
                f"Contagens após a migração divergem: origem={antes} destino={depois}.",
                "contagem_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )
        if depois.get("operacoes", 0) != 0:
            raise MigracaoRecusada(
                "O destino ficou com journal pendente.",
                "journal_pendente",
                "Não ative este destino; o índice original permanece no lugar.",
            )
        _conferir_ids(dst)
        _conferir_opcionais(origem, tmp)
        return depois
    finally:
        src.close()
        dst.close()


def _contagens(con: sqlite3.Connection) -> dict[str, int]:
    saida = {tabela: _contar(con, tabela) for tabela in TABELAS_CONTAGEM}
    saida["fts"] = _contar(con, "chunks_fts")
    saida["operacoes"] = _contar(con, "operacoes")
    return saida


def _contar(con: sqlite3.Connection, tabela: str) -> int:
    try:
        row = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0])


def _conferir_ids(con: sqlite3.Connection) -> None:
    for row in con.execute("SELECT ocorrencia_id, root_id, path FROM documentos"):
        esperado = id_de(str(row["root_id"]), str(row["path"]))
        if str(row["ocorrencia_id"]) != esperado:
            raise MigracaoRecusada(
                "ocorrencia_id divergente após a migração.",
                "identidade_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )


def _conferir_opcionais(origem: Path, tmp: Path) -> None:
    if _n_arquivos(origem / PASTA_PARSE_STORE) != _n_arquivos(tmp / PASTA_PARSE_STORE):
        raise MigracaoRecusada(
            "O parse store copiado não tem a mesma quantidade de arquivos.",
            "parse_store_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )
    if (origem / "vetores.lance").is_dir() != (tmp / "vetores.lance").is_dir():
        raise MigracaoRecusada(
            "A cópia dos vetores não reproduziu o diretório de origem.",
            "vetores_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )


def _n_arquivos(pasta: Path) -> int:
    if not pasta.is_dir():
        return 0
    return sum(1 for p in pasta.rglob("*") if p.is_file())


def _indice_da_base(base_id: str, config: Path | None) -> Path:
    conf = carregar_config(config, validar=True) if config is not None else carregar_config()
    base = next((b for b in conf.bases if b.id == base_id), None)
    if base is None:
        raise ErroDeConfig(
            f"A base '{base_id}' não foi encontrada. Disponíveis: {', '.join(conf.ids)}."
        )
    return base.indice


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migra o índice para identidade por raiz e caminho, numa pasta nova."
    )
    parser.add_argument("--base", default=BASE_UNICA, help="Base cujo índice será copiado.")
    parser.add_argument("--config", type=Path, help="config.toml da base.")
    parser.add_argument("--indice", type=Path, help="Diretório do índice; sobrepõe a base.")
    parser.add_argument("--destino", type=Path, required=True, help="Pasta nova do índice migrado.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        origem = args.indice if args.indice is not None else _indice_da_base(args.base, args.config)
        migrar(origem, args.destino)
    except (MigracaoRecusada, ErroDeConfig) as exc:
        print(str(exc), file=sys.stderr)
        acao = getattr(exc, "acao", "")
        if acao:
            print(acao, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
