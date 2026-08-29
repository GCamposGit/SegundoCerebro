"""Index storage: SQLite for the registry and lexical side, LanceDB for vectors.

The registry is what makes indexing resumable. Each document row records the
size, mtime, content hash, the `model_id` that produced its vectors and the
chunker version. A document is skipped only when all of those match, so
switching embedding model or chunking rule re-processes exactly what it must,
and never mixes vectors from two models in the same table without noticing.

The lexical side is SQLite FTS5 with the native `bm25()` ranking. Two notes that
cost debugging time if forgotten:

- Hyphen, dot and slash are **operators** in FTS5 MATCH syntax. `PO-ACME-007`
  unquoted parses as `PO NOT ACME NOT 007` and returns nothing. Every term is
  quoted before reaching FTS5 (see `consulta_fts`).
- The FTS table uses external content plus triggers, so it stays in sync with
  `chunks` automatically instead of depending on every call site remembering to
  update both.
"""

from __future__ import annotations

import json
import os
import sqlite3
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..ingest.chunking import Chunk
from ..logger import get_logger
from .travas import NOME_DA_TRAVA as NOME_DA_TRAVA  # reexport: ver o comentário abaixo

log = get_logger("index.store")

# `NOME_DA_TRAVA` é importado no topo, de `index/travas.py`, e segue alcançável
# por `index.store` porque é assim que a suíte e o `eval/` o pedem. Era declarado
# aqui, com a justificativa de que eval e testes precisam consultar a trava **sem**
# importar o indexador (GPU, encoder, laço) — a justificativa continua valendo, e
# desde 29/08/2026 `indexer.py` lê a mesma constante em vez de declarar a segunda
# cópia.


class IndiceEmEscrita(RuntimeError):
    """Indexação viva neste diretório — o leitor recusa, não espera em silêncio."""


def indexacao_viva(diretorio: Path) -> bool:
    """Há um indexador vivo neste índice agora?

    Não reimplementa o par pid+criação do `TravaDeIndice`: para recusar a suíte
    basta o PID estar vivo. Falso positivo após reciclar PID é raro e o preço
    é uma mensagem, não dois indexadores duplicando vetor.
    """
    marca = Path(diretorio) / NOME_DA_TRAVA
    if not marca.exists():
        return False
    try:
        bruto = marca.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    pid_texto, _, _ = bruto.partition(",")
    if not pid_texto.isdigit():
        return True
    try:
        os.kill(int(pid_texto), 0)
    except OSError:
        return False
    except Exception:  # noqa: BLE001 — permissão: supor vivo
        return True
    return True


def recusar_se_indexando(diretorio: Path) -> None:
    """Levanta `IndiceEmEscrita` se a passada estiver viva.

    Sem isto, `PRAGMA busy_timeout=15000` faz cada consulta da suíte esperar
    15 s na trava de escrita do SQLite, em silêncio: 40 minutos sem uma linha.
    Pausar o indexador (`comando.txt` = `pausar`) libera; esta função diz isso
    em milissegundos.
    """
    if not indexacao_viva(diretorio):
        return
    comando = Path(diretorio) / "comando.txt"
    raise IndiceEmEscrita(
        f"o índice em {diretorio} está sendo escrito agora. "
        f"Escreva 'pausar' em {comando} (ou cancele a passada) e rode de novo — "
        "sem isso o SQLite espera a trava de escrita sem mensagem."
    )

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    path        TEXT PRIMARY KEY,
    raiz        TEXT NOT NULL,
    tamanho     INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    sha256      TEXT DEFAULT '',
    status      TEXT NOT NULL,
    detalhe     TEXT DEFAULT '',
    n_chunks    INTEGER DEFAULT 0,
    model_id    TEXT DEFAULT '',
    chunker     TEXT DEFAULT '',
    -- Versão do parser que produziu o texto (ver ingest/parsers/__init__.py).
    -- Sem ela um parser corrigido não alcança o que já está no índice: tamanho,
    -- mtime, modelo e chunker todos passam.
    parser      TEXT DEFAULT '',
    indexado_em TEXT NOT NULL,
    -- Natureza do arquivo (ver ingest/natureza.py). Persistida porque estava
    -- sendo calculada e descartada: um PDF digitalizado e um PDF vazio de
    -- verdade recebiam o mesmo status, e separar os dois exigia script avulso.
    familia_real       TEXT DEFAULT '',
    extensao_mente     INTEGER DEFAULT 0,
    digitalizado       INTEGER DEFAULT 0,
    tem_sumario_nativo INTEGER DEFAULT 0,
    tem_tabela         INTEGER DEFAULT 0,
    figuras_por_pagina REAL DEFAULT 0,
    paginas            INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id       TEXT PRIMARY KEY,
    path     TEXT NOT NULL,
    caminho  TEXT NOT NULL DEFAULT '',
    ordinal  INTEGER NOT NULL,
    trilha   TEXT NOT NULL DEFAULT '',
    locator  TEXT NOT NULL DEFAULT '',
    kind     TEXT NOT NULL DEFAULT '',
    chars    INTEGER NOT NULL DEFAULT 0,
    texto    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

-- `caminho` é o path com separadores virados em espaço, para o tokenizador
-- quebrar em palavras. Sem ele o índice lexical ignora o nome do arquivo, que é
-- o sinal mais forte deste acervo: o baseline por nome tira recall@1 = 0,55.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    texto, trilha, caminho,
    content='chunks', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, texto, trilha, caminho)
    VALUES (new.rowid, new.texto, new.trilha, new.caminho);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, texto, trilha, caminho)
    VALUES ('delete', old.rowid, old.texto, old.trilha, old.caminho);
END;

-- Grafo derivado (F4). Guarda **menção**, não aresta: duas arestas entre N
-- documentos que citam o mesmo identificador seriam N² linhas, e envelheceriam
-- na primeira reindexação. A aresta é derivada por junção em tempo de consulta,
-- que é a mesma escolha de `retrieve/familias.py` e pelo mesmo motivo.
--
-- `chunk_id` existe para a resposta carregar procedência: dizer que dois
-- documentos se ligam pela ISO 42001 vale pouco se o cliente não pode ler o
-- trecho onde cada um a cita.
CREATE TABLE IF NOT EXISTS mencoes (
    path     TEXT NOT NULL,
    tipo     TEXT NOT NULL,
    valor    TEXT NOT NULL,
    chunk_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (path, tipo, valor)
);
-- A junção do `neighbors` parte de (tipo, valor) para achar quem mais cita o
-- mesmo identificador; sem este índice ela varre a tabela inteira por consulta.
CREATE INDEX IF NOT EXISTS idx_mencoes_valor ON mencoes(tipo, valor);

CREATE TABLE IF NOT EXISTS execucoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciada_em  TEXT NOT NULL,
    terminada_em TEXT,
    model_id     TEXT NOT NULL,
    chunker      TEXT NOT NULL,
    config       TEXT NOT NULL DEFAULT '{}',
    documentos   INTEGER DEFAULT 0,
    chunks       INTEGER DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'em_andamento'
);

-- R1.4: a poisonous file is skipped on later waves, not retried every pass.
-- `CREATE TABLE IF NOT EXISTS` is enough here — this is a new table, not a
-- column on an old one. Hash change (the user replaced the file) clears the row.
CREATE TABLE IF NOT EXISTS quarentena (
    path               TEXT PRIMARY KEY,
    hash               TEXT DEFAULT '',
    motivo             TEXT NOT NULL,
    tentativas         INTEGER NOT NULL DEFAULT 1,
    ultima_tentativa   TEXT NOT NULL,
    proxima_tentativa  TEXT NOT NULL
);

-- Quanto cada documento custou, por etapa e em tempo **ativo**.
--
-- Antes desta tabela o custo de indexar não era guardado em lugar nenhum:
-- `documentos` tem tamanho, n_chunks, paginas, digitalizado — e nenhuma coluna
-- de tempo. Sem isto não há como recalibrar sobre histórico, que é a lacuna
-- estrutural que a v2 da estimativa fecha (`docs/spec-estimativa-v2.md` §10).
--
-- `suspeito` marca documento cujo relógio não pode ser usado: houve suspensão
-- ou pausa enquanto ele estava em voo. Guardar a linha e marcá-la é melhor que
-- descartar na origem — ela ainda serve para auditar por que a calibragem
-- ignorou aquela passada.
CREATE TABLE IF NOT EXISTS medicoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao      INTEGER NOT NULL DEFAULT 0,
    path          TEXT NOT NULL,
    tipo          TEXT NOT NULL DEFAULT '',
    mb            REAL NOT NULL DEFAULT 0,
    n_chunks      INTEGER NOT NULL DEFAULT 0,
    tokens        INTEGER NOT NULL DEFAULT 0,
    s_parse       REAL,
    s_chunk       REAL,
    s_embed       REAL,
    s_grava       REAL,
    s_total_ativo REAL NOT NULL DEFAULT 0,
    suspeito      INTEGER NOT NULL DEFAULT 0,
    perfil        TEXT NOT NULL DEFAULT '',
    fingerprint   TEXT NOT NULL DEFAULT '',
    model_id      TEXT NOT NULL DEFAULT '',
    situacao      TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '',
    quando        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_medicoes_tipo ON medicoes(tipo);
"""

TERMO = re.compile(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ\-\./_]*")
TABELA_VETORES = "vetores"
CAMPO_VETOR = "vetor"


class DimensaoIncompativel(RuntimeError):
    """O índice foi construído com um modelo de outra dimensão."""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def caminho_pesquisavel(path: str) -> str:
    """Path with separators turned into spaces, so FTS tokenises it as words."""
    return " ".join(path.replace("/", " ").replace("_", " ").replace("\\", " ").split())


def consulta_fts(texto: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Every term is quoted: `PO-ACME-007` must stay one token instead of becoming
    `PO NOT ACME NOT 007`, which is how FTS5 reads a bare hyphen.
    """
    termos = TERMO.findall(texto)
    if not termos:
        return ""
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in termos)


@dataclass(frozen=True)
class EstadoDocumento:
    path: str
    tamanho: int
    mtime: float
    sha256: str
    status: str
    n_chunks: int
    model_id: str
    chunker: str
    parser: str


@dataclass(frozen=True)
class ChunkArmazenado:
    id: str
    path: str
    ordinal: int
    trilha: str
    locator: str
    kind: str
    texto: str


@dataclass(frozen=True)
class Acerto:
    id: str
    score: float
    posicao: int


MAX_TENTATIVAS_QUARENTENA = 2
"""First failure plus one retry after backoff. A third try waits for the bytes to change."""

BACKOFF_QUARENTENA_S = 3600.0
"""One hour, then two. Tests shorten this; a wave of days must not spin on the same PDF."""


@dataclass(frozen=True)
class ItemQuarentena:
    path: str
    hash: str
    motivo: str
    tentativas: int
    ultima_tentativa: str
    proxima_tentativa: str


class Store:
    """Registry + lexical index + vector table. One directory holds all of it."""

    def __init__(self, diretorio: Path, dim: int) -> None:
        self.diretorio = Path(diretorio)
        self.diretorio.mkdir(parents=True, exist_ok=True)
        self.dim = dim

        # `check_same_thread=False` porque o servidor MCP executa ferramenta
        # síncrona num pool de threads: a conexão nasce na thread da primeira
        # consulta e as seguintes chegam por outra, o que o padrão recusa com
        # "SQLite objects created in a thread can only be used in that same
        # thread". É seguro aqui e só aqui porque `sqlite3.threadsafety == 3`
        # (modo serializado): o próprio módulo serializa o acesso à conexão.
        # A verificação abaixo existe para que um ambiente com biblioteca
        # compilada em outro modo falhe alto, em vez de corromper em silêncio.
        if sqlite3.threadsafety != 3:  # pragma: no cover - depende do build local
            raise RuntimeError(
                f"sqlite3.threadsafety = {sqlite3.threadsafety}; este código presume 3 "
                "(serializado) para compartilhar a conexão entre threads"
            )
        self.con = sqlite3.connect(self.diretorio / "registro.db", check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        # WAL: leitor não bloqueia escritor. No journal padrão, um processo de
        # eval com o índice aberto derrubava a indexação com "database is
        # locked" no meio da passada — e o loop de background do LanceDB mantém
        # o processo vivo depois do fim do script, então esse leitor sobrevive
        # mais do que se espera. busy_timeout absorve a disputa transitória em
        # vez de abortar horas de trabalho.
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=15000")
        self.con.executescript(ESQUEMA)
        self._alinhar_colunas()
        self.con.commit()

        self._db = None
        self._tabela = None

    COLUNAS_ACRESCENTAVEIS = (
        ("familia_real", "TEXT DEFAULT ''"),
        ("extensao_mente", "INTEGER DEFAULT 0"),
        ("digitalizado", "INTEGER DEFAULT 0"),
        ("tem_sumario_nativo", "INTEGER DEFAULT 0"),
        ("tem_tabela", "INTEGER DEFAULT 0"),
        ("figuras_por_pagina", "REAL DEFAULT 0"),
        ("paginas", "INTEGER DEFAULT 0"),
        ("parser", "TEXT DEFAULT ''"),
    )

    def _alinhar_colunas(self) -> None:
        """Acrescenta em banco antigo as colunas que o esquema ganhou depois.

        `CREATE TABLE IF NOT EXISTS` não altera tabela existente, então um índice
        criado por versão anterior seguiria sem as colunas e o INSERT falharia
        com "no such column" — no meio de uma passada de horas. O default de cada
        coluna é o valor "não sei", nunca um valor que finja medição: documento
        indexado antes desta versão tem `digitalizado = 0` porque ninguém olhou,
        e não porque foi verificado.
        """
        existentes = {r["name"] for r in self.con.execute("PRAGMA table_info(documentos)")}
        for nome, tipo in self.COLUNAS_ACRESCENTAVEIS:
            if nome not in existentes:
                self.con.execute(f"ALTER TABLE documentos ADD COLUMN {nome} {tipo}")
                log.info("registro: coluna %s acrescentada", nome)
                if nome == "parser":
                    self._estampar_parser_inicial()

    def _estampar_parser_inicial(self) -> None:
        """Estampa `VERSAO_INICIAL` no índice que existia antes da coluna.

        É a única migração deste registro que precisa escrever valor em vez de
        deixar o default, e o motivo é o oposto do usual: aqui o "não sei" **não**
        é neutro. `parser = ''` não bate com nenhuma versão declarada, então a
        próxima passada repescaria o índice inteiro — 1.608 documentos, 39 h de
        parede — para reproduzir exatamente o texto que já está lá.

        A afirmação que a estampa faz é verificável: todo parser nasceu em
        `VERSAO_INICIAL`, e quem subiu de versão declarou isso no código. Logo o
        que estava indexado veio da versão inicial, exceto onde alguém subiu a
        versão de propósito — que é precisamente o que deve repescar.
        """
        from ..ingest.parsers import VERSAO_INICIAL

        n = self.con.execute(
            "UPDATE documentos SET parser = ? WHERE parser = '' OR parser IS NULL",
            (VERSAO_INICIAL,),
        ).rowcount
        self.con.commit()
        log.info("registro: %d documento(s) estampado(s) com parser=%s", n, VERSAO_INICIAL)

    # --- LanceDB, aberto sob demanda -------------------------------------

    @property
    def tabela(self):  # noqa: ANN201
        if self._tabela is None:
            import lancedb
            import pyarrow as pa

            self._db = lancedb.connect(str(self.diretorio / "vetores.lance"))
            # Abrir e cair para criar, em vez de listar antes: o retorno de
            # list_tables() mudou de lista de nomes para um objeto de resposta
            # paginado (0.37), e `nome in resposta` passou a ser sempre falso —
            # o que levava a tentar criar uma tabela que já existia.
            try:
                self._tabela = self._db.open_table(TABELA_VETORES)
                self._conferir_dimensao(self._tabela)
            except DimensaoIncompativel:
                raise
            except Exception:  # noqa: BLE001 — tabela ainda não existe
                esquema = pa.schema(
                    [
                        pa.field("id", pa.string()),
                        pa.field("path", pa.string()),
                        pa.field("ordinal", pa.int32()),
                        pa.field("kind", pa.string()),
                        pa.field("ext", pa.string()),
                        pa.field("mtime", pa.float64()),
                        # o modelo fica no vetor, não só no documento: durante uma
                        # troca de modelo interrompida a tabela contém vetores de
                        # dois espaços ao mesmo tempo, e a busca densa misturaria
                        # os dois em silêncio se não filtrasse por aqui
                        pa.field("model_id", pa.string()),
                        pa.field("vetor", pa.list_(pa.float32(), self.dim)),
                    ]
                )
                self._tabela = self._db.create_table(TABELA_VETORES, schema=esquema)
        return self._tabela

    def _conferir_dimensao(self, tabela) -> None:  # noqa: ANN001
        """Recusa índice construído com outro modelo, na abertura.

        Sem isto o erro aparece lá dentro do LanceDB, no meio da primeira busca
        — depois de carregar 2 GB de encoder e rodar metade do eval — como
        `query dim(384) doesn't match column dim(1024)`, que não diz o que fazer.
        Aconteceu em 13/08/2026: o `MODELO_PADRAO` mudou para `e5-large` e um
        `default="minilm"` esquecido no eval fez três medições falharem.

        Uma dimensão igual não garante o mesmo modelo — dois modelos de 768
        dimensões produzem espaços incomparáveis. A busca densa filtra por
        `model_id` para esse caso, e este método só pega o erro grosseiro, que é
        justamente o que passa despercebido por parecer configuração e não dado.
        """
        campo = tabela.schema.field(CAMPO_VETOR)
        dim = getattr(campo.type, "list_size", None)
        if dim and dim != self.dim:
            raise DimensaoIncompativel(
                f"índice em {self.diretorio} tem vetores de {dim} dimensões e o modelo "
                f"pedido produz {self.dim}. Use o modelo com que o índice foi construído "
                f"(--modelo), ou aponte --indice para outro diretório."
            )

    def fechar(self) -> None:
        self.con.commit()
        self.con.close()
        # soltar a referência do LanceDB: mantê-la viva prende o processo pelo
        # loop de background da biblioteca
        self._tabela = None
        self._db = None

    # --- registro ---------------------------------------------------------

    def path_ok_por_sha256(
        self, sha256: str, model_id: str, chunker: str, parser: str = ""
    ) -> str | None:
        """First path already embedded with this content, model, chunker and parser."""
        if not sha256:
            return None
        linha = self.con.execute(
            "SELECT path FROM documentos WHERE sha256 = ? AND status = 'ok' "
            "AND n_chunks > 0 AND model_id = ? AND chunker = ? AND parser = ? LIMIT 1",
            (sha256, model_id, chunker, parser),
        ).fetchone()
        return str(linha["path"]) if linha else None

    def estado_documento(self, path: str) -> EstadoDocumento | None:
        linha = self.con.execute(
            "SELECT path, tamanho, mtime, sha256, status, n_chunks, model_id, chunker, parser"
            " FROM documentos WHERE path = ?",
            (path,),
        ).fetchone()
        return EstadoDocumento(**dict(linha)) if linha else None

    def estados(self) -> dict[str, EstadoDocumento]:
        """Todo o registro de uma vez, para derivar o mapa restante.

        Uma consulta em vez de N: o mapa é recalculado por diferença a cada
        ciclo, e fazer `estado_documento` por arquivo transformaria a derivação
        no gargalo que ela existe para evitar.
        """
        return {
            r["path"]: EstadoDocumento(**dict(r))
            for r in self.con.execute(
                "SELECT path, tamanho, mtime, sha256, status, n_chunks,"
                " model_id, chunker, parser FROM documentos"
            )
        }

    def gravar_medicao(  # noqa: ANN001
        self, obs, *, execucao: int = 0, fingerprint: str = "", model_id: str = ""
    ) -> None:
        """Uma linha por documento processado. Nunca no caminho de consulta."""
        self.con.execute(
            "INSERT INTO medicoes (execucao, path, tipo, mb, n_chunks, tokens,"
            " s_parse, s_chunk, s_embed, s_grava, s_total_ativo, suspeito,"
            " perfil, fingerprint, model_id, situacao, status, quando)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                execucao,
                obs.rel,
                obs.tipo,
                obs.mb,
                obs.n_chunks,
                obs.tokens,
                obs.s_parse,
                obs.s_chunk,
                obs.s_embed,
                obs.s_grava,
                obs.s_total_ativo,
                1 if obs.suspeito else 0,
                obs.perfil,
                fingerprint,
                model_id,
                obs.situacao,
                obs.status,
                agora(),
            ),
        )

    def podar_medicoes(self, por_tipo: int = 500) -> int:
        """Reservatório: mantém as `por_tipo` mais recentes de cada tipo.

        Os acumuladores da calibragem não precisam das linhas — elas existem
        para reajuste, auditoria e para o autoteste. Sem poda, `medicoes` cresce
        junto com `documentos` para sempre.
        """
        cur = self.con.execute(
            "DELETE FROM medicoes WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id, row_number() OVER"
            "      (PARTITION BY tipo ORDER BY id DESC) AS pos"
            "    FROM medicoes"
            "  ) WHERE pos > ?"
            ")",
            (por_tipo,),
        )
        return cur.rowcount or 0

    COLUNAS_NATUREZA = (
        "familia_real",
        "extensao_mente",
        "digitalizado",
        "tem_sumario_nativo",
        "tem_tabela",
        "figuras_por_pagina",
        "paginas",
    )

    def registrar_documento(
        self,
        *,
        path: str,
        raiz: str,
        tamanho: int,
        mtime: float,
        status: str,
        sha256: str = "",
        detalhe: str = "",
        n_chunks: int = 0,
        model_id: str = "",
        chunker: str = "",
        parser: str = "",
        natureza=None,  # noqa: ANN001 — ingest.natureza.Natureza, importado tarde
    ) -> None:
        colunas = self.COLUNAS_NATUREZA
        valores_natureza = natureza.como_colunas() if natureza is not None else {}
        extras = tuple(valores_natureza.get(c, "" if c == "familia_real" else 0) for c in colunas)

        lista = ", ".join(colunas)
        marcas = ", ".join("?" * len(colunas))
        atualiza = ", ".join(f"{c}=excluded.{c}" for c in colunas)
        self.con.execute(
            f"""
            INSERT INTO documentos
                (path, raiz, tamanho, mtime, sha256, status, detalhe, n_chunks,
                 model_id, chunker, parser, indexado_em, {lista})
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?, {marcas})
            ON CONFLICT(path) DO UPDATE SET
                raiz=excluded.raiz, tamanho=excluded.tamanho, mtime=excluded.mtime,
                sha256=excluded.sha256, status=excluded.status, detalhe=excluded.detalhe,
                n_chunks=excluded.n_chunks, model_id=excluded.model_id,
                chunker=excluded.chunker, parser=excluded.parser,
                indexado_em=excluded.indexado_em, {atualiza}
            """,
            (
                path, raiz, tamanho, mtime, sha256, status, detalhe, n_chunks,
                model_id, chunker, parser, agora(),
            )
            + extras,
        )

    def registrar_quarentena(
        self,
        path: str,
        *,
        hash: str = "",
        motivo: str = "",
        agora: datetime | None = None,
        backoff_s: float | None = None,
    ) -> ItemQuarentena:
        """Record a poisonous-file failure and schedule the next retry.

        Same path, same hash: increment. Hash changed: the user replaced the
        file, so the count restarts. Tests pass `agora` and `backoff_s`.
        """
        instante = agora or datetime.now(timezone.utc)
        espera = BACKOFF_QUARENTENA_S if backoff_s is None else float(backoff_s)
        atual = self.quarentena_de(path)
        if atual is None or atual.hash != hash:
            tentativas = 1
        else:
            tentativas = atual.tentativas + 1
        if tentativas >= MAX_TENTATIVAS_QUARENTENA:
            proxima = instante + timedelta(days=365 * 100)
        else:
            proxima = instante + timedelta(seconds=espera * (2 ** (tentativas - 1)))
        item = ItemQuarentena(
            path=path,
            hash=hash,
            motivo=(motivo or "")[:500],
            tentativas=tentativas,
            ultima_tentativa=instante.isoformat(timespec="seconds"),
            proxima_tentativa=proxima.isoformat(timespec="seconds"),
        )
        self.con.execute(
            """
            INSERT INTO quarentena (path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                hash=excluded.hash, motivo=excluded.motivo, tentativas=excluded.tentativas,
                ultima_tentativa=excluded.ultima_tentativa, proxima_tentativa=excluded.proxima_tentativa
            """,
            (
                item.path,
                item.hash,
                item.motivo,
                item.tentativas,
                item.ultima_tentativa,
                item.proxima_tentativa,
            ),
        )
        return item

    def quarentena_de(self, path: str) -> ItemQuarentena | None:
        linha = self.con.execute(
            "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa "
            "FROM quarentena WHERE path = ?",
            (path,),
        ).fetchone()
        return ItemQuarentena(**dict(linha)) if linha else None

    def listar_quarentena(self) -> list[ItemQuarentena]:
        linhas = self.con.execute(
            "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa "
            "FROM quarentena ORDER BY path"
        )
        return [ItemQuarentena(**dict(l)) for l in linhas]

    def limpar_quarentena(self, path: str) -> None:
        self.con.execute("DELETE FROM quarentena WHERE path = ?", (path,))

    def deve_pular_quarentena(
        self,
        path: str,
        hash: str = "",
        *,
        agora: datetime | None = None,
    ) -> bool:
        """True when this file is still in backoff, or retries are exhausted.

        A different hash means the bytes changed — do not skip, and drop the row
        so the next failure starts the count again.
        """
        item = self.quarentena_de(path)
        if item is None:
            return False
        if hash and item.hash and hash != item.hash:
            self.limpar_quarentena(path)
            return False
        instante = agora or datetime.now(timezone.utc)
        try:
            proxima = datetime.fromisoformat(item.proxima_tentativa)
        except ValueError:
            return item.tentativas >= MAX_TENTATIVAS_QUARENTENA
        if proxima.tzinfo is None:
            proxima = proxima.replace(tzinfo=timezone.utc)
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        if item.tentativas >= MAX_TENTATIVAS_QUARENTENA:
            return True
        return instante < proxima

    def registrados(self, prefixo: str | None = None) -> dict[str, str]:
        """Caminho -> sha256 de tudo que está no registro, opcionalmente sob um prefixo."""
        if prefixo:
            linhas = self.con.execute(
                "SELECT path, sha256 FROM documentos WHERE path LIKE ? || '%'", (prefixo,)
            )
        else:
            linhas = self.con.execute("SELECT path, sha256 FROM documentos")
        return {r["path"]: r["sha256"] or "" for r in linhas}

    def esquecer_documento(self, path: str) -> int:
        """Remove chunks, vetores **e** a linha do registro.

        Diferente de `remover_documento`, que limpa os chunks mas mantém a linha
        para reindexar por cima. Aqui o documento deixa de existir para o
        sistema — é o que se faz quando o arquivo saiu do disco.
        """
        n = self.remover_documento(path)
        self.con.execute("DELETE FROM documentos WHERE path = ?", (path,))
        self.con.execute("DELETE FROM quarentena WHERE path = ?", (path,))
        return n

    def remover_documento(self, path: str) -> int:
        """Drop a document's chunks and vectors — makes reindexing idempotent."""
        n = self.con.execute("SELECT count(*) FROM chunks WHERE path = ?", (path,)).fetchone()[0]
        if n:
            self.con.execute("DELETE FROM chunks WHERE path = ?", (path,))
            escapado = path.replace("'", "''")
            try:
                self.tabela.delete(f"path = '{escapado}'")
            except Exception as exc:  # noqa: BLE001 — tabela vazia ou ainda inexistente
                log.debug("remoção de vetores sem efeito para %s: %s", path, exc)
        return n

    def gravar_textos(self, chunks: Sequence[Chunk]) -> None:
        """SQLite + FTS only — the lexical half of a two-pass run (R3.2).

        The vector table stays untouched so a MiniLM draft cannot land in an
        e5-large column (384 vs 1024). Search works the same day via bm25 and
        the filename ranker; pass 2 writes the final vectors on top.
        """
        if not chunks:
            return
        self.con.executemany(
            "INSERT OR REPLACE INTO chunks (id, path, caminho, ordinal, trilha, locator, kind, chars, texto)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    c.id,
                    c.doc_path,
                    caminho_pesquisavel(c.doc_path),
                    c.ordinal,
                    " > ".join(c.heading_path),
                    c.locator,
                    c.kind.value,
                    c.chars,
                    c.text,
                )
                for c in chunks
            ],
        )

    def gravar_vetores(
        self,
        chunks: Sequence[Chunk],
        vetores: Sequence[np.ndarray],
        mtime: float,
        model_id: str = "",
    ) -> None:
        if not chunks:
            return
        if len(chunks) != len(vetores):
            raise ValueError(f"{len(chunks)} chunks e {len(vetores)} vetores")
        extensao = Path(chunks[0].doc_path).suffix.lower()
        self.tabela.add(
            [
                {
                    "id": c.id,
                    "path": c.doc_path,
                    "ordinal": c.ordinal,
                    "kind": c.kind.value,
                    "ext": extensao,
                    "mtime": mtime,
                    "model_id": model_id,
                    "vetor": v.astype(np.float32).tolist(),
                }
                for c, v in zip(chunks, vetores)
            ]
        )

    def substituir_vetores(
        self,
        chunks: Sequence[Chunk],
        vetores: Sequence[np.ndarray],
        mtime: float,
        model_id: str = "",
    ) -> None:
        """Drop the dense rows for this document and write new ones. Chunks stay.

        Pass 2 of a two-pass run: the lexical side is already searchable, only
        the embedding model changed. Deleting chunks here would drop FTS.
        """
        if not chunks:
            return
        path = chunks[0].doc_path
        escapado = path.replace("'", "''")
        try:
            self.tabela.delete(f"path = '{escapado}'")
        except Exception as exc:  # noqa: BLE001 — no vector table yet is pass 1
            log.debug("substituição de vetores sem tabela para %s: %s", path, exc)
        self.gravar_vetores(chunks, vetores, mtime, model_id)

    def gravar_chunks(
        self,
        chunks: Sequence[Chunk],
        vetores: Sequence[np.ndarray],
        mtime: float,
        model_id: str = "",
    ) -> None:
        if not chunks:
            return
        if len(chunks) != len(vetores):
            raise ValueError(f"{len(chunks)} chunks e {len(vetores)} vetores")
        self.gravar_textos(chunks)
        self.gravar_vetores(chunks, vetores, mtime, model_id)

    def carimbar_modelo(self, path: str, model_id: str) -> None:
        """Pass 2: the bytes did not change, only the dense space did."""
        self.con.execute(
            "UPDATE documentos SET model_id = ?, indexado_em = ? WHERE path = ?",
            (model_id, agora(), path),
        )

    def pendentes_de_modelo(self, model_id: str) -> list[str]:
        """OK documents that have chunks and are not yet on `model_id`."""
        linhas = self.con.execute(
            "SELECT path FROM documentos WHERE status = 'ok' AND n_chunks > 0 "
            "AND (model_id IS NULL OR model_id != ?) ORDER BY path",
            (model_id,),
        )
        return [r["path"] for r in linhas]

    def documentos_para_ocr(self, versao: str) -> list[tuple[str, str]]:
        """Scans waiting for OCR, or OCR'd with an older engine. (path, raiz).

        `digitalizado` is already the mark — a second `precisa_ocr` column
        would duplicate it. The queue is: still on the PDF parser (full scan
        with no chunks, or mixed file with native chunks), or an older `ocr:*`.
        """
        # Mixed PDFs (native cover + scan body) already have chunks from the
        # native pages; `n_chunks = 0` would hide them. Anything still on the
        # PDF parser, or on an older `ocr:*`, is waiting.
        linhas = self.con.execute(
            "SELECT path, raiz FROM documentos WHERE digitalizado = 1 AND ("
            "parser IS NULL OR parser NOT LIKE 'ocr:%' OR parser != ?"
            ") ORDER BY path",
            (versao,),
        )
        return [(r["path"], r["raiz"]) for r in linhas]

    def cobertura_modelos(self) -> dict[str, int]:
        """How many OK documents sit on each model_id, plus the lexical-only count."""
        por: dict[str, int] = {}
        for linha in self.con.execute(
            "SELECT COALESCE(model_id, '') AS model_id, count(*) AS n "
            "FROM documentos WHERE status = 'ok' AND n_chunks > 0 GROUP BY 1"
        ):
            por[linha["model_id"] or "lexical"] = int(linha["n"])
        return por

    def commit(self) -> None:
        self.con.commit()

    def vetores_por_id(self) -> dict[str, np.ndarray]:
        """Every dense vector, keyed by chunk id. Used to compare two indices.

        `to_arrow` and not `to_pandas`: pandas não é dependência. `to_list` no
        LanceTable desta versão do lancedb não existe — só no resultado de
        `search`.
        """
        try:
            tabela = self.tabela.to_arrow()
        except Exception:  # noqa: BLE001 — tabela vazia
            return {}
        ids = tabela.column("id").to_pylist()
        vetores = tabela.column("vetor").to_pylist()
        return {
            i: np.asarray(v, dtype=np.float32) for i, v in zip(ids, vetores)
        }

    # --- execuções --------------------------------------------------------

    def iniciar_execucao(self, model_id: str, chunker: str, config: dict) -> int:
        cur = self.con.execute(
            "INSERT INTO execucoes (iniciada_em, model_id, chunker, config) VALUES (?,?,?,?)",
            (agora(), model_id, chunker, json.dumps(config, ensure_ascii=False)),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def encerrar_execucao(self, execucao: int, documentos: int, chunks: int, status: str) -> None:
        self.con.execute(
            "UPDATE execucoes SET terminada_em=?, documentos=?, chunks=?, status=? WHERE id=?",
            (agora(), documentos, chunks, status, execucao),
        )
        self.con.commit()

    # --- busca ------------------------------------------------------------

    def buscar_denso(
        self, vetor: np.ndarray, k: int, filtro: str | None = None, model_id: str | None = None
    ) -> list[Acerto]:
        consulta = self.tabela.search(vetor.astype(np.float32), vector_column_name="vetor").metric("cosine")
        if model_id:
            # nunca comparar vetores de espaços diferentes na mesma busca
            escapado = model_id.replace("'", "''")
            filtro = f"model_id = '{escapado}'" + (f" AND ({filtro})" if filtro else "")
        if filtro:
            consulta = consulta.where(filtro, prefilter=True)
        linhas = consulta.limit(k).to_list()
        return [
            Acerto(id=linha["id"], score=1.0 - float(linha.get("_distance", 0.0)), posicao=i)
            for i, linha in enumerate(linhas, start=1)
        ]

    def buscar_lexical(
        self, texto: str, k: int, pesos_colunas: tuple[float, float, float] | None = None
    ) -> list[Acerto]:
        """Busca lexical. `pesos_colunas` são os pesos de `texto`, `trilha` e `caminho`.

        `None` mantém `bm25(chunks_fts)` sem argumento — o padrão 1/1/1 do FTS5 e
        o SQL exato que mediu tudo de F1 a F4. A alternativa (passar 1,1,1
        sempre) daria o mesmo número em teoria e trocaria o caminho de código
        medido por um equivalente não medido, o que já custou caro aqui.

        Existe por causa de `C3.a`: com `caminho` valendo 1,0, o nome do arquivo
        pontua **dentro** do bm25 e **de novo** na fusão, pelo `RanqueadorDeNome`.
        O mesmo sinal vota duas vezes. Neste acervo, de nome informativo, isso
        passa; num acervo de `IMG_2034.pdf` é ruído dobrado. O peso é de consulta,
        não de índice — varrer não reindexa nada.
        """
        expressao = consulta_fts(texto)
        if not expressao:
            return []
        if pesos_colunas is None:
            score = "bm25(chunks_fts)"
            parametros: tuple[object, ...] = (expressao, k)
        else:
            score = "bm25(chunks_fts, ?, ?, ?)"
            parametros = (*(float(p) for p in pesos_colunas), expressao, k)
        linhas = self.con.execute(
            f"""
            SELECT c.id AS id, {score} AS score
            FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            parametros,
        ).fetchall()
        # bm25() do SQLite é negativo, mais negativo = melhor
        return [Acerto(id=l["id"], score=-float(l["score"]), posicao=i) for i, l in enumerate(linhas, start=1)]

    def chunk(self, chunk_id: str) -> ChunkArmazenado | None:
        linha = self.con.execute(
            "SELECT id, path, ordinal, trilha, locator, kind, texto FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        return ChunkArmazenado(**dict(linha)) if linha else None

    def ids_de_chunks(self, path: str) -> list[str]:
        """Só os ids de um documento, em ordem de leitura — sem carregar texto.

        Existe separado de `chunks_de` porque o ranqueador de nome pergunta isto
        para `candidatos` documentos por consulta, e só para saber quais trechos o
        documento tem. Trazer `texto` junto seria ler o documento inteiro do disco
        para descartá-lo, `candidatos` vezes, dentro do caminho de consulta.
        """
        linhas = self.con.execute(
            "SELECT id FROM chunks WHERE path = ? ORDER BY ordinal", (path,)
        ).fetchall()
        return [linha[0] for linha in linhas]

    def chunks_de(self, path: str) -> list[ChunkArmazenado]:
        linhas = self.con.execute(
            "SELECT id, path, ordinal, trilha, locator, kind, texto FROM chunks WHERE path = ? ORDER BY ordinal",
            (path,),
        ).fetchall()
        return [ChunkArmazenado(**dict(l)) for l in linhas]

    def vizinhos(self, chunk_id: str, janela: int = 1) -> list[ChunkArmazenado]:
        """Adjacent chunks in the same document — context expansion (F2)."""
        atual = self.chunk(chunk_id)
        if atual is None:
            return []
        linhas = self.con.execute(
            "SELECT id, path, ordinal, trilha, locator, kind, texto FROM chunks"
            " WHERE path = ? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (atual.path, atual.ordinal - janela, atual.ordinal + janela),
        ).fetchall()
        return [ChunkArmazenado(**dict(l)) for l in linhas]

    # --- grafo derivado (F4) ----------------------------------------------

    def registrar_mencoes(self, path: str, mencoes: Sequence[tuple[str, str, str]]) -> int:
        """Substitui as menções de um documento. Devolve quantas ficaram.

        Substitui em vez de acrescentar porque a passada do grafo é idempotente
        por documento: rodar duas vezes tem que dar o mesmo resultado, e um
        identificador que saiu do texto depois de uma edição tem que sair do
        grafo — senão a aresta sobrevive ao fato que a justificava.
        """
        self.con.execute("DELETE FROM mencoes WHERE path = ?", (path,))
        if mencoes:
            self.con.executemany(
                "INSERT OR REPLACE INTO mencoes(path, tipo, valor, chunk_id) VALUES (?,?,?,?)",
                [(path, t, v, c) for t, v, c in mencoes],
            )
        return len(mencoes)

    def mencoes_de(self, path: str) -> list[tuple[str, str, str]]:
        return [
            (l["tipo"], l["valor"], l["chunk_id"])
            for l in self.con.execute(
                "SELECT tipo, valor, chunk_id FROM mencoes WHERE path = ? ORDER BY tipo, valor",
                (path,),
            )
        ]

    def paths_do_registro(self) -> list[str]:
        """Todo documento conhecido, **inclusive** os sem chunk.

        `paths_com_chunks` responde "o que a busca alcança"; isto responde "o que
        existe". A diferença são os documentos de status `vazio`, `travado` ou
        `sem_parser` — e é justamente onde vive o PDF digitalizado cujo único
        sinal é o nome do arquivo.
        """
        return [
            l["path"]
            for l in self.con.execute("SELECT path FROM documentos ORDER BY path")
        ]

    def paths_com_mencoes(self) -> list[str]:
        return [
            l["path"]
            for l in self.con.execute("SELECT DISTINCT path FROM mencoes ORDER BY path")
        ]

    def frequencia_de_mencoes(self, path: str) -> list[tuple[str, str, int]]:
        """Para cada identificador citado por `path`, em quantos documentos ele
        aparece no acervo inteiro.

        É o insumo do peso da aresta. Um identificador que aparece em dois
        documentos liga os dois; o CNPJ da própria empresa aparece em todo
        contrato e não liga nada — descobrir qual é qual exige esta contagem, e
        é por isso que ela não pode ser estimada nem cacheada por documento.
        """
        return [
            (l["tipo"], l["valor"], l["docs"])
            for l in self.con.execute(
                "SELECT m.tipo, m.valor, COUNT(DISTINCT m.path) AS docs FROM mencoes m"
                " WHERE (m.tipo, m.valor) IN (SELECT tipo, valor FROM mencoes WHERE path = ?)"
                " GROUP BY m.tipo, m.valor",
                (path,),
            )
        ]

    def quem_cita(self, tipo: str, valor: str, excluir: str = "") -> list[tuple[str, str]]:
        """Documentos que citam este identificador, com o chunk onde citam."""
        return [
            (l["path"], l["chunk_id"])
            for l in self.con.execute(
                "SELECT path, chunk_id FROM mencoes WHERE tipo = ? AND valor = ? AND path != ?"
                " ORDER BY path",
                (tipo, valor, excluir),
            )
        ]

    def estatisticas_do_grafo(self) -> dict[str, object]:
        linha = self.con.execute(
            # Subconsulta em vez de concatenar tipo+valor com um separador
            # literal: qualquer separador escolhido pode aparecer dentro de um
            # valor, e aí dois identificadores diferentes contariam como um.
            "SELECT COUNT(*) AS mencoes, COUNT(DISTINCT path) AS documentos,"
            " (SELECT COUNT(*) FROM (SELECT DISTINCT tipo, valor FROM mencoes))"
            " AS identificadores FROM mencoes"
        ).fetchone()
        por_tipo = {
            l["tipo"]: l["n"]
            for l in self.con.execute(
                "SELECT tipo, COUNT(DISTINCT valor) AS n FROM mencoes GROUP BY tipo ORDER BY tipo"
            )
        }
        return {
            "mencoes": linha["mencoes"],
            "documentos": linha["documentos"],
            "identificadores": linha["identificadores"],
            "por_tipo": por_tipo,
        }

    # --- estado -----------------------------------------------------------

    def estatisticas(self) -> dict[str, object]:
        por_status = {
            l["status"]: l["n"]
            for l in self.con.execute("SELECT status, count(*) AS n FROM documentos GROUP BY status")
        }
        modelos = [
            l["model_id"]
            for l in self.con.execute(
                "SELECT DISTINCT model_id FROM documentos WHERE model_id != '' ORDER BY model_id"
            )
        ]
        return {
            "documentos": self.con.execute("SELECT count(*) FROM documentos").fetchone()[0],
            "chunks": self.con.execute("SELECT count(*) FROM chunks").fetchone()[0],
            "por_status": por_status,
            "modelos": modelos,
            "quarentena": self.con.execute("SELECT count(*) FROM quarentena").fetchone()[0],
        }

    def verificar_consistencia(self) -> dict[str, int]:
        """Compare registry and vector table — a mismatch is silent corruption.

        Found in practice: two indexers running against the same directory wrote
        13.458 vectors for 7.214 chunks. WAL let SQLite tolerate the concurrency,
        LanceDB has no such protection, and `remover + add` interleaved duplicated
        every vector. Dense search then returns the same chunk twice and inflates
        the fusion. Nothing errored — it just measured wrong.
        """
        chunks = self.con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        try:
            vetores = self.tabela.count_rows()
        except Exception:  # noqa: BLE001 — sem tabela ainda
            vetores = 0
        return {"chunks": chunks, "vetores": vetores, "diferenca": vetores - chunks}

    def paths_indexados(self) -> Iterable[str]:
        for linha in self.con.execute("SELECT path FROM documentos"):
            yield linha["path"]

    def mtimes(self) -> dict[str, float]:
        """Data de modificação por documento — o que decide qual versão é a vigente.

        Famílias de versão se separam por metadado, não por conteúdo: `_v6` e
        `_revisadaTI_GC` dizem quase a mesma coisa, e o que os distingue é
        janeiro contra agosto. Medido na condição C, é a causa da falha do caso
        `g010` (`docs/portas-f1-condicao-c.md`).
        """
        return {
            linha["path"]: linha["mtime"]
            for linha in self.con.execute("SELECT path, mtime FROM documentos")
        }

    def paths_com_chunks(self) -> list[str]:
        """Distinct paths that actually have chunks — what search can return.

        The name ranker builds on this rather than on `documentos`: a document
        registered with status `vazio` or `travado` has no chunk and can never be
        retrieved, and a chunk whose registry row is missing would silently lose
        its name signal. Ranking over what is retrievable keeps the two in step.
        """
        return [l["path"] for l in self.con.execute("SELECT DISTINCT path FROM chunks ORDER BY path")]
