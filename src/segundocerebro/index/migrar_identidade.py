"""Migrate a path-PK index to occurrence identity in a new directory (FND-01b).

Writes a new folder. The original is not modified and is not pointed at.
Pending journal rows refuse the run. Activation is a separate step, like
restore: change `indice` in config.toml only after verification.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
from collections.abc import Mapping
import sys
from pathlib import Path

import numpy as np

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
            _transformar_vetores(tmp)
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
        mapa = _recriar_documentos(con)
        _recriar_chunks(con, mapa)
        _recriar_mencoes(con, mapa)
        _recriar_quarentena(con, mapa)
        _carimbar_tabelas_derivadas(con, mapa)
        _preencher_raizes(con)
        _estampar_v2(con)
        con.commit()
    finally:
        con.close()


def _recriar_documentos(con: sqlite3.Connection) -> dict[str, str]:
    presentes = {str(r["name"]) for r in con.execute("PRAGMA table_info(documentos)")}
    colunas = [c for c in COLUNAS_DOCUMENTOS if c in presentes]
    if "path" not in presentes or "raiz" not in presentes:
        raise MigracaoRecusada(
            "O registro legado não tem path e raiz; não dá para derivar ocorrência.",
            "schema_ilegivel",
            "Restaure um backup anterior e tente de novo.",
        )
    linhas = list(con.execute(f"SELECT {', '.join(colunas)} FROM documentos"))
    mapa = {str(row["path"]): id_de(str(row["raiz"]), str(row["path"])) for row in linhas}
    con.execute("ALTER TABLE documentos RENAME TO documentos_legado")
    con.execute("DROP INDEX IF EXISTS idx_documentos_sha256")
    con.executescript(DOCUMENTOS_V2_CREATE)
    _inserir_v2(con, colunas, linhas)
    con.execute("DROP TABLE documentos_legado")
    con.execute("CREATE INDEX IF NOT EXISTS idx_documentos_sha256 ON documentos(sha256)")
    return mapa


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


def _colunas(con: sqlite3.Connection, tabela: str) -> set[str]:
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({tabela})")}


def _recriar_chunks(con: sqlite3.Connection, mapa: dict[str, str]) -> None:
    """Move legacy chunks to their occurrence without losing opaque chunk ids.

    Legacy fixtures and older indexes may contain chunk ids not produced by the
    current chunker. They are already opaque public references, so migration
    preserves them and changes the owning occurrence. New indexing derives ids
    from occurrence identity and therefore cannot collide across homonyms.
    """
    if not _colunas(con, "chunks"):
        return
    presentes = _colunas(con, "chunks")
    colunas = [
        c for c in ("id", "path", "caminho", "ordinal", "trilha", "locator", "kind", "chars", "texto")
        if c in presentes
    ]
    linhas = list(con.execute(f"SELECT {', '.join(colunas)} FROM chunks"))
    con.execute("DROP TRIGGER IF EXISTS chunks_ai")
    con.execute("DROP TRIGGER IF EXISTS chunks_ad")
    con.execute("DROP TABLE IF EXISTS chunks_fts")
    con.execute("DROP TABLE IF EXISTS chunks_fts_vocab")
    con.execute("ALTER TABLE chunks RENAME TO chunks_legado")
    con.execute("""
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            ocorrencia_id TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            caminho TEXT NOT NULL DEFAULT '',
            ordinal INTEGER NOT NULL,
            trilha TEXT NOT NULL DEFAULT '',
            locator TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            chars INTEGER NOT NULL DEFAULT 0,
            texto TEXT NOT NULL
        )
    """)
    for row in linhas:
        dados = dict(row)
        path = str(dados.get("path") or "")
        valores = [
            dados.get("id", ""), mapa.get(path, path), path,
            dados.get("caminho", ""), dados.get("ordinal", 0),
            dados.get("trilha", ""), dados.get("locator", ""),
            dados.get("kind", ""), dados.get("chars", 0), dados.get("texto", ""),
        ]
        con.execute(
            "INSERT INTO chunks (id, ocorrencia_id, path, caminho, ordinal, trilha, locator, kind, chars, texto) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", valores,
        )
    con.execute("DROP TABLE chunks_legado")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_ocorrencia ON chunks(ocorrencia_id)")
    con.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            texto, trilha, caminho, content='chunks', content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    con.execute("CREATE VIRTUAL TABLE chunks_fts_vocab USING fts5vocab(chunks_fts, 'row')")
    con.execute("""
        CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, texto, trilha, caminho)
            VALUES (new.rowid, new.texto, new.trilha, new.caminho);
        END
    """)
    con.execute("""
        CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, texto, trilha, caminho)
            VALUES ('delete', old.rowid, old.texto, old.trilha, old.caminho);
        END
    """)
    con.execute(
        "INSERT INTO chunks_fts(rowid, texto, trilha, caminho) "
        "SELECT rowid, texto, trilha, caminho FROM chunks"
    )


def _recriar_mencoes(con: sqlite3.Connection, mapa: dict[str, str]) -> None:
    if not _colunas(con, "mencoes"):
        return
    presentes = _colunas(con, "mencoes")
    campos = [c for c in ("path", "tipo", "valor", "chunk_id") if c in presentes]
    linhas = list(con.execute(f"SELECT {', '.join(campos)} FROM mencoes"))
    con.execute("DROP TABLE mencoes")
    con.execute("""
        CREATE TABLE mencoes (
            ocorrencia_id TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            tipo TEXT NOT NULL,
            valor TEXT NOT NULL,
            chunk_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (ocorrencia_id, tipo, valor)
        )
    """)
    for row in linhas:
        dados = dict(row)
        path = str(dados.get("path") or "")
        con.execute(
            "INSERT OR REPLACE INTO mencoes(ocorrencia_id, path, tipo, valor, chunk_id) VALUES (?,?,?,?,?)",
            (mapa.get(path, path), path, dados.get("tipo", ""), dados.get("valor", ""), dados.get("chunk_id", "")),
        )
    con.execute("CREATE INDEX IF NOT EXISTS idx_mencoes_valor ON mencoes(tipo, valor)")


def _recriar_quarentena(con: sqlite3.Connection, mapa: dict[str, str]) -> None:
    if not _colunas(con, "quarentena"):
        return
    linhas = list(con.execute(
        "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa FROM quarentena"
    ))
    con.execute("DROP TABLE quarentena")
    con.execute("""
        CREATE TABLE quarentena (
            ocorrencia_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            hash TEXT DEFAULT '',
            motivo TEXT NOT NULL,
            tentativas INTEGER NOT NULL DEFAULT 1,
            ultima_tentativa TEXT NOT NULL,
            proxima_tentativa TEXT NOT NULL
        )
    """)
    for row in linhas:
        dados = dict(row)
        path = str(dados["path"])
        con.execute(
            "INSERT OR REPLACE INTO quarentena(ocorrencia_id, path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa) "
            "VALUES (?,?,?,?,?,?,?)",
            (mapa.get(path, path), path, dados["hash"], dados["motivo"], dados["tentativas"], dados["ultima_tentativa"], dados["proxima_tentativa"]),
        )


def _carimbar_tabelas_derivadas(con: sqlite3.Connection, mapa: dict[str, str]) -> None:
    """Add occurrence ownership to append-only operational tables."""
    for tabela in ("medicoes", "operacoes"):
        if not _colunas(con, tabela):
            continue
        if "ocorrencia_id" not in _colunas(con, tabela):
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN ocorrencia_id TEXT NOT NULL DEFAULT ''")
        con.executemany(
            f"UPDATE {tabela} SET ocorrencia_id = ? WHERE path = ?",
            [(oid, path) for path, oid in mapa.items()],
        )


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
        _conferir_registros(src, dst)
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


def _conferir_registros(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Compare all migrated semantic rows, not merely table cardinalities."""
    docs_src = [
        tuple(row)
        for row in src.execute("SELECT path, raiz, tamanho, mtime, sha256, status, n_chunks FROM documentos ORDER BY path")
    ]
    docs_dst = [
        tuple(row)
        for row in dst.execute("SELECT path, raiz, tamanho, mtime, sha256, status, n_chunks FROM documentos ORDER BY path")
    ]
    if docs_src != docs_dst:
        raise MigracaoRecusada(
            "Os metadados de documentos não reproduziram a origem.",
            "registro_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )
    for tabela, colunas in {
        "chunks": ("id", "path", "ordinal", "trilha", "locator", "kind", "chars", "texto"),
        "mencoes": ("path", "tipo", "valor", "chunk_id"),
        "quarentena": ("path", "hash", "motivo", "tentativas", "ultima_tentativa", "proxima_tentativa"),
    }.items():
        if not _colunas(src, tabela):
            continue
        ordem = ", ".join(colunas)
        antes = [tuple(row) for row in src.execute(f"SELECT {ordem} FROM {tabela} ORDER BY {ordem}")]
        depois = [tuple(row) for row in dst.execute(f"SELECT {ordem} FROM {tabela} ORDER BY {ordem}")]
        if antes != depois:
            raise MigracaoRecusada(
                f"Os registros de {tabela} não reproduziram a origem.",
                "registro_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )


def _conferir_opcionais(origem: Path, tmp: Path) -> None:
    if _arvore_digests(origem / PASTA_PARSE_STORE) != _arvore_digests(tmp / PASTA_PARSE_STORE):
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
    if (origem / "vetores.lance").is_dir():
        con = sqlite3.connect(tmp / "registro.db")
        try:
            ocorrencias = {
                str(row[0]): str(row[1])
                for row in con.execute("SELECT path, ocorrencia_id FROM documentos")
            }
        finally:
            con.close()
        _conferir_vetores(
            origem / "vetores.lance", tmp / "vetores.lance", ocorrencias
        )


def _n_arquivos(pasta: Path) -> int:
    if not pasta.is_dir():
        return 0
    return sum(1 for p in pasta.rglob("*") if p.is_file())


def _arvore_digests(pasta: Path) -> dict[str, str]:
    if not pasta.is_dir():
        return {}
    saida: dict[str, str] = {}
    for arquivo in sorted(p for p in pasta.rglob("*") if p.is_file()):
        digest = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        saida[arquivo.relative_to(pasta).as_posix()] = digest
    return saida


def _linhas_vetores(pasta: Path) -> dict[str, dict]:  # noqa: ANN001
    import lancedb

    db = lancedb.connect(str(pasta))
    nomes = _nomes_lance(db)
    nome = "vetores" if "vetores" in nomes else ("chunks" if "chunks" in nomes else "")
    if not nome:
        return {}
    return {str(row.get("id")): row for row in db.open_table(nome).to_arrow().to_pylist()}


def _conferir_vetores(
    origem: Path, destino: Path, ocorrencias: Mapping[str, str]
) -> None:
    """Compare every copied vector row, allowing only the new owner column."""
    antes = _linhas_vetores(origem)
    depois = _linhas_vetores(destino)
    if set(antes) != set(depois):
        raise MigracaoRecusada(
            "A cópia dos vetores perdeu ou criou linhas.",
            "vetores_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )
    campos = ("path", "ordinal", "kind", "ext", "mtime", "model_id")
    for ident in sorted(antes):
        a, d = antes[ident], depois[ident]
        if any(a.get(c) != d.get(c) for c in campos):
            raise MigracaoRecusada(
                f"A procedência do vetor {ident} divergiu.",
                "vetores_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )
        if d.get("ocorrencia_id") != ocorrencias.get(str(d.get("path") or "")):
            raise MigracaoRecusada(
                f"A identidade do vetor {ident} divergiu.",
                "vetores_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )
        if not np.array_equal(
            np.asarray(a.get("vetor"), dtype=np.float32),
            np.asarray(d.get("vetor"), dtype=np.float32),
        ):
            raise MigracaoRecusada(
                f"O valor do vetor {ident} divergiu.",
                "vetores_divergente",
                "Não ative este destino; o índice original permanece no lugar.",
            )


def _transformar_vetores(tmp: Path) -> None:
    """Rewrite copied Lance rows with occurrence ownership in the destination only."""
    lance_dir = tmp / "vetores.lance"
    if not lance_dir.is_dir():
        return
    con = sqlite3.connect(tmp / "registro.db")
    con.row_factory = sqlite3.Row
    try:
        mapa = {str(r["path"]): str(r["ocorrencia_id"]) for r in con.execute("SELECT path, ocorrencia_id FROM documentos")}
    finally:
        con.close()

    import lancedb
    import pyarrow as pa

    db = lancedb.connect(str(lance_dir))
    nomes = _nomes_lance(db)
    nome = "vetores" if "vetores" in nomes else ("chunks" if "chunks" in nomes else "")
    if not nome:
        return
    tabela = db.open_table(nome)
    linhas = tabela.to_arrow().to_pylist()
    if not linhas:
        return
    for linha in linhas:
        linha["ocorrencia_id"] = mapa.get(str(linha.get("path") or ""), str(linha.get("ocorrencia_id") or ""))
    novo = tmp / "vetores.lance.novo"
    if novo.exists():
        shutil.rmtree(novo)
    novo_db = lancedb.connect(str(novo))
    novo_db.create_table("vetores", data=pa.Table.from_pylist(linhas))
    del tabela, db, novo_db
    shutil.rmtree(lance_dir)
    novo.rename(lance_dir)


def _nomes_lance(db) -> list[str]:  # noqa: ANN001
    try:
        resposta = db.list_tables()
        if hasattr(resposta, "tables"):
            return list(resposta.tables)
        return list(resposta)
    except Exception:  # noqa: BLE001 — compatibility with older LanceDB
        try:
            return list(db.table_names())
        except Exception:  # noqa: BLE001 — compatibility fallback for old LanceDB
            return []


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
