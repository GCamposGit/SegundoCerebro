"""Manutenção e orçamento do SQLite/FTS5 para índices grandes — R4.2."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

MIB = 1024 * 1024
CACHE_PADRAO_MB = 64
MMAP_PADRAO_MB = 256
TERMO = re.compile(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ\-\./_]*")
SEPARADORES_DE_FRASE = frozenset("-./_")


@dataclass(frozen=True)
class PoliticaSQLite:
    cache_mb: int
    mmap_mb: int


def caminho_pesquisavel(path: str) -> str:
    """Path com separadores virados em espaços para o tokenizador FTS."""
    return " ".join(path.replace("/", " ").replace("_", " ").replace("\\", " ").split())


def consulta_fts(texto: str) -> str:
    """Transforma texto livre numa expressão MATCH que preserva hífens."""
    termos = TERMO.findall(texto)
    if not termos:
        return ""
    return " OR ".join('"' + termo.replace('"', '""') + '"' for termo in termos)


def _termo_do_vocabulario(termo: str) -> str:
    """Aproxima a normalização de ``unicode61 remove_diacritics 2`` para um token."""
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", termo.casefold())
        if not unicodedata.combining(caractere)
    )


def consulta_fts_seletiva(con: sqlite3.Connection, texto: str) -> str:
    """Remove só termos cujo IDF o FTS5 já reduz ao piso de 1e-6.

    No BM25 nativo, uma frase presente em pelo menos metade das linhas recebe
    IDF 1e-6. Ela quase não decide a ordem, mas num OR ainda faz o motor visitar
    a maior parte do índice. ``fts5vocab`` permite reconhecê-la sem stoplist por
    idioma. Identificadores com separadores ficam intactos porque são frases no
    tokenizer; se tudo for ubíquo, a consulta original é preservada.
    """
    termos = TERMO.findall(texto)
    if len(termos) < 2:
        return consulta_fts(texto)
    total = int(con.execute("SELECT count(*) FROM chunks").fetchone()[0])
    if not total:
        return consulta_fts(texto)

    frequencias: dict[str, int] = {}
    escolhidos: list[str] = []
    for termo in termos:
        if any(separador in termo for separador in SEPARADORES_DE_FRASE):
            escolhidos.append(termo)
            continue
        normalizado = _termo_do_vocabulario(termo)
        if normalizado not in frequencias:
            linha = con.execute(
                "SELECT doc FROM chunks_fts_vocab WHERE term = ?", (normalizado,)
            ).fetchone()
            frequencias[normalizado] = int(linha[0]) if linha is not None else 0
        if 2 * frequencias[normalizado] < total:
            escolhidos.append(termo)

    return consulta_fts(" ".join(escolhidos or termos))


def politica_sqlite(ram_livre_mb: int = 0) -> PoliticaSQLite:
    """Deriva cache e mmap da RAM livre sem competir com encoder e sistema.

    Cache usa no máximo 1/32 da RAM livre (32–256 MiB); mmap reserva endereço,
    não memória residente, mas fica em 1/8 da RAM (128 MiB–1 GiB). Quando a
    sonda não existe, os padrões são conservadores e independem do hardware.
    """
    if ram_livre_mb <= 0:
        return PoliticaSQLite(CACHE_PADRAO_MB, MMAP_PADRAO_MB)
    return PoliticaSQLite(
        cache_mb=min(256, max(32, ram_livre_mb // 32)),
        mmap_mb=min(1024, max(128, ram_livre_mb // 8)),
    )


def _ram_livre_mb() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().available / MIB)
    except Exception:  # noqa: BLE001 — ausência da sonda tem padrão seguro
        return 0


def configurar_sqlite(con: sqlite3.Connection, *, novo: bool) -> PoliticaSQLite:
    """Aplica orçamento em toda conexão; incremental vacuum nasce com o banco."""
    politica = politica_sqlite(_ram_livre_mb())
    if novo:
        # Só produz efeito antes de criar tabelas. Converter banco antigo exige
        # VACUUM integral e uma segunda cópia do arquivo — não cabe na abertura.
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.execute(f"PRAGMA cache_size=-{politica.cache_mb * 1024}")
    con.execute(f"PRAGMA mmap_size={politica.mmap_mb * MIB}")
    return politica


def otimizar_fts(con: sqlite3.Connection) -> bool:
    """Compacta segmentos FTS e devolve se o vacuum incremental era possível."""
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    incremental = int(con.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    if incremental:
        # Um lote pequeno por passada evita transformar higiene em uma pausa
        # proporcional ao histórico inteiro de exclusões.
        con.execute("PRAGMA incremental_vacuum(1000)")
    con.commit()
    return incremental


def buscar_lexical(  # noqa: ANN001
    store,
    texto: str,
    k: int,
    pesos_colunas=None,
    filtro_path: str | None = None,
    *,
    podar_ubiquos: bool = True,
) -> list:
    """Executa o ranking FTS5; ``Store`` conserva apenas a fachada pública."""
    from .store import Acerto

    expressao = (
        consulta_fts_seletiva(store.con, texto) if podar_ubiquos else consulta_fts(texto)
    )
    if not expressao:
        return []
    extra: tuple[object, ...] = (filtro_path, f"{filtro_path}/%") if filtro_path else ()
    if pesos_colunas is None:
        score = "bm25(chunks_fts)"
        parametros: tuple[object, ...] = (expressao, *extra, k)
    else:
        score = "bm25(chunks_fts, ?, ?, ?)"
        parametros = (*(float(p) for p in pesos_colunas), expressao, *extra, k)
    # O ``id`` mora na tabela externa ``chunks``, mas ele não participa nem do
    # MATCH nem da ordenação. A subconsulta escalar mantém a hidratação do id
    # limitada ao resultado; quando há filtro por pasta, o JOIN expõe `path`
    # para o predicado antes do LIMIT.
    if filtro_path:
        linhas = store.con.execute(
            f"""
            SELECT c.id AS id, {score} AS score
            FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ? AND (c.path = ? OR c.path LIKE ?)
            ORDER BY score
            LIMIT ?
            """,
            parametros,
        ).fetchall()
    else:
        linhas = store.con.execute(
            f"""
            SELECT (
                SELECT c.id FROM chunks c WHERE c.rowid = chunks_fts.rowid
            ) AS id, {score} AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            parametros,
        ).fetchall()
    return [
        Acerto(id=str(linha["id"]), score=-float(linha["score"]), posicao=i)
        for i, linha in enumerate(linhas, start=1)
        if linha["id"] is not None
    ]
