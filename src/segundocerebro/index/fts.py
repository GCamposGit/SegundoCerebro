"""Manutenção e orçamento do SQLite/FTS5 para índices grandes — R4.2."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
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


def ambiente_de_ci() -> bool:
    """GitHub Actions e runners compatíveis exportam ``CI=true``."""
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


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


def mmap_aplicado_mb(
    politica: PoliticaSQLite,
    *,
    plataforma: str | None = None,
    ci: bool | None = None,
) -> int:
    """Tamanho efetivo do mmap. Runner hosted não recebe o orçamento de produção.

    No Windows o mapeamento é cometido pelo sistema de arquivos, não só
    reservado. O teto de 128 MiB (PR #109) ainda interrompeu o job pytest.
    ``CI=true`` desliga o mmap: a suíte abre stores efêmeros; o índice local
    do usuário não vê essa variável e mantém o teto.
    """
    if ci is None:
        ci = ambiente_de_ci()
    if ci:
        return 0
    if plataforma is None:
        plataforma = sys.platform
    if plataforma == "win32":
        return min(politica.mmap_mb, 128)
    return politica.mmap_mb


def _ram_livre_mb() -> int:
    if ambiente_de_ci():
        return 0
    try:
        import psutil

        return int(psutil.virtual_memory().available / MIB)
    except Exception:  # noqa: BLE001 — ausência da sonda tem padrão seguro
        return 0


def configurar_sqlite(con: sqlite3.Connection, *, novo: bool) -> PoliticaSQLite:
    """Aplica orçamento em toda conexão; incremental vacuum nasce com o banco."""
    politica = politica_sqlite(_ram_livre_mb())
    mmap_mb = mmap_aplicado_mb(politica)
    if novo:
        # Só produz efeito antes de criar tabelas. Converter banco antigo exige
        # VACUUM integral e uma segunda cópia do arquivo — não cabe na abertura.
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.execute(f"PRAGMA cache_size=-{politica.cache_mb * 1024}")
    con.execute(f"PRAGMA mmap_size={mmap_mb * MIB}")
    return PoliticaSQLite(cache_mb=politica.cache_mb, mmap_mb=mmap_mb)


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


def _buscar_lexical_com_filtros(  # noqa: ANN001
    store,
    expressao: str,
    k: int,
    pesos_colunas: tuple[float, float, float] | None,
    filtro_path: str | None,
    mtime_min: float | None,
    mtime_max: float | None,
) -> list[sqlite3.Row]:
    joins = ["chunks_fts", "JOIN chunks c ON c.rowid = chunks_fts.rowid"]
    where_clausulas = ["chunks_fts MATCH ?"]
    parametros_match: list[object] = [expressao]
    parametros_filtro: list[object] = []

    if filtro_path:
        where_clausulas.append("(c.path = ? OR c.path LIKE ?)")
        parametros_filtro.extend([filtro_path, f"{filtro_path}/%"])

    if mtime_min is not None or mtime_max is not None:
        joins.append("JOIN documentos d ON d.path = c.path")
        if mtime_min is not None:
            where_clausulas.append("d.mtime >= ?")
            parametros_filtro.append(float(mtime_min))
        if mtime_max is not None:
            where_clausulas.append("d.mtime <= ?")
            parametros_filtro.append(float(mtime_max))

    where_sql = " AND ".join(where_clausulas)
    from_sql = " ".join(joins)

    if pesos_colunas is None:
        score = "bm25(chunks_fts)"
        parametros = (*parametros_match, *parametros_filtro, k)
    else:
        score = "bm25(chunks_fts, ?, ?, ?)"
        parametros = (*(float(p) for p in pesos_colunas), *parametros_match, *parametros_filtro, k)

    return store.con.execute(
        f"""
        SELECT c.id AS id, {score} AS score
        FROM {from_sql}
        WHERE {where_sql}
        ORDER BY score
        LIMIT ?
        """,
        parametros,
    ).fetchall()


def buscar_lexical(  # noqa: ANN001
    store,
    texto: str,
    k: int,
    pesos_colunas: tuple[float, float, float] | None = None,
    filtro_path: str | None = None,
    mtime_min: float | None = None,
    mtime_max: float | None = None,
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

    tem_filtro = bool(filtro_path or mtime_min is not None or mtime_max is not None)
    if tem_filtro:
        linhas = _buscar_lexical_com_filtros(
            store, expressao, k, pesos_colunas, filtro_path, mtime_min, mtime_max
        )
    else:
        # O ``id`` mora na tabela externa ``chunks``, mas ele não participa nem do
        # MATCH nem da ordenação. A subconsulta escalar mantém a hidratação do id
        # limitada ao resultado após o LIMIT quando não há predicados adicionais.
        if pesos_colunas is None:
            score = "bm25(chunks_fts)"
            parametros = (expressao, k)
        else:
            score = "bm25(chunks_fts, ?, ?, ?)"
            parametros = (*(float(p) for p in pesos_colunas), expressao, k)
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
