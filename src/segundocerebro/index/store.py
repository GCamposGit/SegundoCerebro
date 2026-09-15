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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .integridade import DiagnosticoIntegridade

import numpy as np

from ..ingest.chunking import Chunk
from ..logger import get_logger
from .esquema import ESQUEMA
from .fts import caminho_pesquisavel, consulta_fts as consulta_fts
from .lancedb_recursos import fechar_store
from .quarentena import (
    BACKOFF_QUARENTENA_S as BACKOFF_QUARENTENA_S,
    MAX_TENTATIVAS_QUARENTENA as MAX_TENTATIVAS_QUARENTENA,
    ItemQuarentena as ItemQuarentena,
    aposentado,
)
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

# `ESQUEMA` morava aqui até 30/08/2026; ver `index/esquema.py`.

TABELA_VETORES = "vetores"
CAMPO_VETOR = "vetor"


class DimensaoIncompativel(RuntimeError):
    """O índice foi construído com um modelo de outra dimensão."""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    ocorrencia_id: str = ""
    root_id: str = ""


@dataclass(frozen=True)
class ChunkArmazenado:
    id: str
    path: str
    ordinal: int
    trilha: str
    locator: str
    kind: str
    texto: str
    ocorrencia_id: str = ""
    root_id: str = ""


@dataclass(frozen=True)
class Acerto:
    id: str
    score: float
    posicao: int


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
        registro = self.diretorio / "registro.db"
        novo_registro = not registro.exists()
        self.con = sqlite3.connect(registro, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        from .fts import configurar_sqlite

        # ``auto_vacuum`` só pode mudar antes de WAL e da primeira tabela. A
        # ordem é contrato: invertê-la deixa o PRAGMA em 0 sem levantar erro.
        configurar_sqlite(self.con, novo=novo_registro)
        # WAL: leitor não bloqueia escritor. No journal padrão, um processo de
        # eval com o índice aberto derrubava a indexação com "database is
        # locked" no meio da passada — e o loop de background do LanceDB mantém
        # o processo vivo depois do fim do script, então esse leitor sobrevive
        # mais do que se espera. busy_timeout absorve a disputa transitória em
        # vez de abortar horas de trabalho.
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=15000")
        self._alinhar_colunas()
        self.con.executescript(ESQUEMA)
        from .ocorrencia import estampar_schema

        estampar_schema(self.con)
        self.con.commit()
        self._usa_ocorrencia_cache: bool | None = None
        self._usa_ocorrencia_cache = any(
            str(row["name"]) == "ocorrencia_id" and int(row["pk"]) == 1
            for row in self.con.execute("PRAGMA table_info(documentos)")
        )

        self._db = None
        self._tabela = None
        self._ann_ativo: bool | None = None
        from .operacoes import recuperar_ao_abrir

        recuperar_ao_abrir(self)

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

    COLUNAS_AUXILIARES = {
        "chunks": (("ocorrencia_id", "TEXT NOT NULL DEFAULT ''"),),
        "mencoes": (("ocorrencia_id", "TEXT NOT NULL DEFAULT ''"),),
        "quarentena": (("ocorrencia_id", "TEXT NOT NULL DEFAULT ''"),),
        "medicoes": (("ocorrencia_id", "TEXT NOT NULL DEFAULT ''"),),
        "operacoes": (("ocorrencia_id", "TEXT NOT NULL DEFAULT ''"),),
    }

    def _alinhar_colunas(self) -> None:
        """Acrescenta em banco antigo as colunas que o esquema ganhou depois.

        `CREATE TABLE IF NOT EXISTS` não altera tabela existente; o alinhamento
        vem antes do esquema para que índices novos encontrem colunas antigas.
        O default de cada
        coluna é o valor "não sei", nunca um valor que finja medição: documento
        indexado antes desta versão tem `digitalizado = 0` porque ninguém olhou,
        e não porque foi verificado.
        """
        existentes = {r["name"] for r in self.con.execute("PRAGMA table_info(documentos)")}
        for nome, tipo in (self.COLUNAS_ACRESCENTAVEIS if existentes else ()):
            if nome not in existentes:
                self.con.execute(f"ALTER TABLE documentos ADD COLUMN {nome} {tipo}")
                log.info("registro: coluna %s acrescentada", nome)
                if nome == "parser":
                    self._estampar_parser_inicial()
        for tabela, colunas in self.COLUNAS_AUXILIARES.items():
            existentes_tabela = {
                r["name"] for r in self.con.execute(f"PRAGMA table_info({tabela})")
            }
            for nome, tipo in (colunas if existentes_tabela else ()):
                if nome not in existentes_tabela:
                    self.con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
                    log.info("registro: coluna %s.%s acrescentada", tabela, nome)

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
                        pa.field("ocorrencia_id", pa.string()),
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
        tabela, db = self._tabela, self._db
        self._tabela = self._db = None
        self._ann_ativo = None
        fechar_store(self.con, tabela, db)

    def garantir_ann(self, n_vetores: int | None = None, *, limiar: int | None = None):  # noqa: ANN201
        from .ann import garantir_no_store

        return garantir_no_store(self, n_vetores, limiar=limiar)

    def otimizar_fts(self) -> bool:
        """Une segmentos FTS5 e recupera páginas aos poucos após a passada."""
        from .fts import otimizar_fts

        return otimizar_fts(self.con)

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
        from .ocorrencia import chave_de

        chave = chave_de(self, path)
        if self._usa_ocorrencia():
            linha = self.con.execute(
                "SELECT path, tamanho, mtime, sha256, status, n_chunks, model_id, chunker, parser, "
                "ocorrencia_id, root_id FROM documentos WHERE ocorrencia_id = ?",
                (chave,),
            ).fetchone()
        else:
            linha = self.con.execute(
                "SELECT path, tamanho, mtime, sha256, status, n_chunks, model_id, chunker, parser "
                "FROM documentos WHERE path = ?", (path,)
            ).fetchone()
        return EstadoDocumento(**dict(linha)) if linha else None

    def estado_documento_da_raiz(self, path: str, root_id: str) -> EstadoDocumento | None:
        """Path lookup scoped to one root; never guesses between homonyms."""
        from .ocorrencia import id_de

        if not self._usa_ocorrencia():
            return self.estado_documento(path)
        linha = self.con.execute(
            "SELECT path, tamanho, mtime, sha256, status, n_chunks, model_id, chunker, parser, "
            "ocorrencia_id, root_id FROM documentos WHERE ocorrencia_id = ?",
            (id_de(root_id, path),),
        ).fetchone()
        return EstadoDocumento(**dict(linha)) if linha else None

    def _usa_ocorrencia(self) -> bool:
        if self._usa_ocorrencia_cache is not None:
            return self._usa_ocorrencia_cache
        from .ocorrencia import usa_ocorrencia

        self._usa_ocorrencia_cache = usa_ocorrencia(self.con)
        return self._usa_ocorrencia_cache

    def _chave_ocorrencia(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> str:
        from .ocorrencia import chave_de

        return chave_de(
            self, path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )

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
        self,
        obs,
        *,
        execucao: int = 0,
        fingerprint: str = "",
        model_id: str = "",
        root_id: str = "",
        ocorrencia_id: str = "",
    ) -> str:
        """Uma linha por documento processado. Nunca no caminho de consulta."""
        if not ocorrencia_id and root_id and self._usa_ocorrencia():
            from .ocorrencia import id_de

            ocorrencia_id = id_de(root_id, obs.rel)
        self.con.execute(
            "INSERT INTO medicoes (execucao, ocorrencia_id, path, tipo, mb, n_chunks, tokens,"
            " s_parse, s_chunk, s_embed, s_grava, s_total_ativo, suspeito,"
            " perfil, fingerprint, model_id, situacao, status, quando)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                execucao,
                ocorrencia_id,
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
        from .ocorrencia import registrar as registrar_ocorrencia

        return registrar_ocorrencia(
            self,
            path=path,
            raiz=raiz,
            tamanho=tamanho,
            mtime=mtime,
            status=status,
            sha256=sha256,
            detalhe=detalhe,
            n_chunks=n_chunks,
            model_id=model_id,
            chunker=chunker,
            parser=parser,
            natureza=natureza,
        )

    def registrar_quarentena(
        self,
        path: str,
        *,
        root_id: str = "",
        ocorrencia_id: str = "",
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
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        atual = self.quarentena_de(path, root_id=root_id, ocorrencia_id=ocorrencia_id)
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
        if self._usa_ocorrencia():
            self.con.execute(
                """
                INSERT INTO quarentena
                    (ocorrencia_id, path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(ocorrencia_id) DO UPDATE SET
                    path=excluded.path, hash=excluded.hash, motivo=excluded.motivo,
                    tentativas=excluded.tentativas,
                    ultima_tentativa=excluded.ultima_tentativa,
                    proxima_tentativa=excluded.proxima_tentativa
                """,
                (
                    chave, item.path, item.hash, item.motivo, item.tentativas,
                    item.ultima_tentativa, item.proxima_tentativa,
                ),
            )
        else:
            self.con.execute(
                """
                INSERT INTO quarentena
                    (path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    hash=excluded.hash, motivo=excluded.motivo, tentativas=excluded.tentativas,
                    ultima_tentativa=excluded.ultima_tentativa, proxima_tentativa=excluded.proxima_tentativa
                """,
                (
                    item.path, item.hash, item.motivo, item.tentativas,
                    item.ultima_tentativa, item.proxima_tentativa,
                ),
            )
        return item

    def quarentena_de(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> ItemQuarentena | None:
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        if self._usa_ocorrencia():
            linha = self.con.execute(
                "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa "
                "FROM quarentena WHERE ocorrencia_id = ?", (chave,)
            ).fetchone()
        else:
            linha = self.con.execute(
                "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa "
                "FROM quarentena WHERE path = ?", (path,)
            ).fetchone()
        return ItemQuarentena(**dict(linha)) if linha else None

    def listar_quarentena(self) -> list[ItemQuarentena]:
        linhas = self.con.execute(
            "SELECT path, hash, motivo, tentativas, ultima_tentativa, proxima_tentativa "
            "FROM quarentena ORDER BY path"
        )
        return [ItemQuarentena(**dict(l)) for l in linhas]

    def limpar_quarentena(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> None:
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        self.con.execute(
            "DELETE FROM quarentena WHERE ocorrencia_id = ?"
            if self._usa_ocorrencia() else "DELETE FROM quarentena WHERE path = ?",
            (chave if self._usa_ocorrencia() else path,),
        )

    def deve_pular_quarentena(
        self,
        path: str,
        hash: str = "",
        *,
        root_id: str = "",
        ocorrencia_id: str = "",
        agora: datetime | None = None,
    ) -> bool:
        """True when this file is still in backoff, or retries are exhausted.

        A different hash means the bytes changed — do not skip, and drop the row
        so the next failure starts the count again.

        **Falha de recurso não aposenta** (30/08/2026): o teto é política de
        *arquivo podre*, e falha de ambiente é transitória — aposentar por ela
        tira o documento do acervo até alguém editá-lo. `MOTIVO_RECURSO` era
        escrito e nunca lido; agora é, e recurso só respeita o backoff.
        """
        item = self.quarentena_de(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        if item is None:
            return False
        if hash and item.hash and hash != item.hash:
            self.limpar_quarentena(
                path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
            return False
        instante = agora or datetime.now(timezone.utc)
        try:
            proxima = datetime.fromisoformat(item.proxima_tentativa)
        except ValueError:
            return aposentado(item)
        if proxima.tzinfo is None:
            proxima = proxima.replace(tzinfo=timezone.utc)
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        if aposentado(item):
            return True
        return instante < proxima

    def registrados(
        self,
        prefixo: str | None = None,
        *,
        root_ids: set[str] | None = None,
    ) -> dict[str, str]:
        """Caminho -> sha256 de tudo que está no registro, opcionalmente sob um prefixo."""
        raiz_coluna = "root_id" if self._usa_ocorrencia() else "raiz AS root_id"
        filtros: list[str] = []
        parametros: list[object] = []
        if prefixo:
            filtros.append("path LIKE ? || '%'")
            parametros.append(prefixo)
        if root_ids:
            marcas = ",".join("?" * len(root_ids))
            coluna_raiz = "root_id" if self._usa_ocorrencia() else "raiz"
            filtros.append(f"{coluna_raiz} IN ({marcas})")
            parametros.extend(sorted(root_ids))
        where = f" WHERE {' AND '.join(filtros)}" if filtros else ""
        linhas = self.con.execute(
            f"SELECT path, sha256, {raiz_coluna} FROM documentos{where}",
            parametros,
        )
        materializadas = list(linhas)
        duplicados = {
            r["path"] for r in materializadas
            if sum(x["path"] == r["path"] for x in materializadas) > 1
        }
        return {
            (
                f"{r['root_id']}\0{r['path']}"
                if self._usa_ocorrencia() and r["path"] in duplicados
                else r["path"]
            ): r["sha256"] or ""
            for r in materializadas
        }

    def esquecer_documento(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> int:
        """Remove chunks, vetores **e** a linha do registro.

        Diferente de `remover_documento`, que limpa os chunks mas mantém a linha
        para reindexar por cima. Aqui o documento deixa de existir para o
        sistema — é o que se faz quando o arquivo saiu do disco.
        """
        n = self.remover_documento(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        if self._usa_ocorrencia() and (root_id or ocorrencia_id):
            chave = self._chave_ocorrencia(
                path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
            self.con.execute("DELETE FROM documentos WHERE ocorrencia_id = ?", (chave,))
            self.con.execute("DELETE FROM quarentena WHERE ocorrencia_id = ?", (chave,))
        elif self._usa_ocorrencia():
            chave = self._chave_ocorrencia(path)
            self.con.execute("DELETE FROM documentos WHERE ocorrencia_id = ?", (chave,))
            self.con.execute("DELETE FROM quarentena WHERE ocorrencia_id = ?", (chave,))
        else:
            self.con.execute("DELETE FROM documentos WHERE path = ?", (path,))
            self.con.execute("DELETE FROM quarentena WHERE path = ?", (path,))
        return n

    def remover_documento(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> int:
        """Drop a document's chunks and vectors — makes reindexing idempotent."""
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        if self._usa_ocorrencia() and (root_id or ocorrencia_id):
            where, params = "ocorrencia_id = ?", (chave,)
        else:
            where, params = "path = ?", (path,)
        n = self.con.execute(
            f"SELECT count(*) FROM chunks WHERE {where}", params
        ).fetchone()[0]
        if n:
            self.con.execute(f"DELETE FROM chunks WHERE {where}", params)
            from .operacoes import apagar_vetores_do_path

            apagar_vetores_do_path(
                self, path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
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
            "INSERT OR REPLACE INTO chunks (id, ocorrencia_id, path, caminho, ordinal, trilha, locator, kind, chars, texto)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    c.id,
                    c.ocorrencia_id or c.doc_path,
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
        registros = [
                {
                    "id": c.id,
                    "ocorrencia_id": c.ocorrencia_id or c.doc_path,
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
        try:
            self.tabela.add(registros)
        except Exception as exc:  # noqa: BLE001 — old LanceDB schema may lack the owner column
            # An index made before FND-01b has no occurrence column. It is
            # still readable; migration is the operation that upgrades it.
            if "ocorrencia_id" not in str(exc).lower():
                raise
            for registro in registros:
                registro.pop("ocorrencia_id", None)
            self.tabela.add(registros)

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
        from .operacoes import apagar_vetores_do_path

        apagar_vetores_do_path(
            self,
            chunks[0].doc_path,
            root_id=chunks[0].root_id,
            ocorrencia_id=chunks[0].ocorrencia_id,
        )
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

    def carimbar_modelo(
        self, path: str, model_id: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> None:
        """Pass 2: the bytes did not change, only the dense space did."""
        if self._usa_ocorrencia() and (root_id or ocorrencia_id):
            chave = self._chave_ocorrencia(
                path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
            self.con.execute(
                "UPDATE documentos SET model_id = ?, indexado_em = ? WHERE ocorrencia_id = ?",
                (model_id, agora(), chave),
            )
        else:
            self.con.execute(
                "UPDATE documentos SET model_id = ?, indexado_em = ? WHERE path = ?",
                (model_id, agora(), path),
            )

    def pendentes_de_modelo(self, model_id: str) -> list[str]:
        """OK documents that have chunks and are not yet on `model_id`."""
        return [path for path, _, _ in self.pendentes_de_modelo_detalhes(model_id)]

    def pendentes_de_modelo_detalhes(
        self, model_id: str
    ) -> list[tuple[str, str, str]]:
        """The pass-two queue with enough identity to disambiguate homonyms."""
        if self._usa_ocorrencia():
            linhas = self.con.execute(
                "SELECT path, root_id, ocorrencia_id FROM documentos "
                "WHERE status = 'ok' AND n_chunks > 0 "
                "AND (model_id IS NULL OR model_id != ?) ORDER BY root_id, path",
                (model_id,),
            )
        else:
            linhas = self.con.execute(
                "SELECT path, raiz AS root_id, '' AS ocorrencia_id FROM documentos "
                "WHERE status = 'ok' AND n_chunks > 0 "
                "AND (model_id IS NULL OR model_id != ?) ORDER BY path",
                (model_id,),
            )
        return [
            (str(row["path"]), str(row["root_id"] or ""), str(row["ocorrencia_id"] or ""))
            for row in linhas
        ]

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
        self,
        vetor: np.ndarray,
        k: int,
        filtro: str | None = None,
        model_id: str | None = None,
        *,
        usar_ann: bool | None = None,
        nprobes: int | None = None,
        refine_factor: int | None = None,
    ) -> list[Acerto]:
        from .ann import buscar_denso

        return buscar_denso(
            self, vetor, k, filtro, model_id,
            usar_ann=usar_ann, nprobes=nprobes, refine_factor=refine_factor,
        )

    def buscar_lexical(
        self,
        texto: str,
        k: int,
        pesos_colunas: tuple[float, float, float] | None = None,
        filtro_path: str | None = None,
        mtime_min: float | None = None,
        mtime_max: float | None = None,
        *,
        podar_ubiquos: bool = True,
    ) -> list[Acerto]:
        from .fts import buscar_lexical

        return buscar_lexical(
            self,
            texto,
            k,
            pesos_colunas,
            filtro_path=filtro_path,
            mtime_min=mtime_min,
            mtime_max=mtime_max,
            podar_ubiquos=podar_ubiquos,
        )

    def chunk(self, chunk_id: str) -> ChunkArmazenado | None:
        consulta = (
            "SELECT c.id, c.path, c.ordinal, c.trilha, c.locator, c.kind, c.texto, "
            "c.ocorrencia_id, COALESCE(d.root_id, '') AS root_id "
            "FROM chunks c LEFT JOIN documentos d ON c.ocorrencia_id = d.ocorrencia_id "
            "WHERE c.id = ?"
            if self._usa_ocorrencia() else
            "SELECT id, path, ordinal, trilha, locator, kind, texto, ocorrencia_id "
            "FROM chunks WHERE id = ?"
        )
        linha = self.con.execute(consulta, (chunk_id,)).fetchone()
        if not linha:
            return None
        return ChunkArmazenado(**dict(linha))

    def chunks_por_id(self, ids: Sequence[str]) -> dict[str, ChunkArmazenado]:
        """Vários chunks numa ida ao banco. Id ausente simplesmente não aparece.

        `chunk()` faz uma consulta por trecho, e o caminho de consulta pede
        centenas: medido em 29/08/2026 no índice corporativo (2.156 documentos),
        `buscar_chunks(q, k=8, contexto=1)` gastava **350 `execute()` por
        consulta**, dos quais ~269 eram este mesmo `SELECT ... WHERE id = ?`
        repetido. A fusão precisa dos metadados de todo o poço de candidatos, e o
        poço tem `candidatos` (200) itens por ranqueador.

        Devolver dicionário e não lista preserva a semântica de `chunk()`: quem
        chama já tratava `None` para "está no vetorial e não no registro", e agora
        trata a ausência da chave — o mesmo caso, sem uma consulta por item.

        O lote existe porque `WHERE id IN (...)` tem teto de parâmetros no SQLite.
        900 fica bem abaixo do limite de qualquer build.
        """
        achados: dict[str, ChunkArmazenado] = {}
        unicos = list(dict.fromkeys(ids))
        for inicio in range(0, len(unicos), 900):
            lote = unicos[inicio : inicio + 900]
            marcas = ",".join("?" * len(lote))
            consulta = (
                "SELECT c.id, c.path, c.ordinal, c.trilha, c.locator, c.kind, c.texto, "
                "c.ocorrencia_id, COALESCE(d.root_id, '') AS root_id "
                "FROM chunks c LEFT JOIN documentos d ON c.ocorrencia_id = d.ocorrencia_id "
                f"WHERE c.id IN ({marcas})"
                if self._usa_ocorrencia() else
                "SELECT id, path, ordinal, trilha, locator, kind, texto, ocorrencia_id FROM chunks "
                f"WHERE id IN ({marcas})"
            )
            linhas = self.con.execute(consulta, lote).fetchall()
            for linha in linhas:
                armazenado = ChunkArmazenado(**dict(linha))
                achados[armazenado.id] = armazenado
        return achados

    def ids_de_chunks_por_path(
        self, paths: Sequence[str], *, root_id: str = ""
    ) -> dict[str, list[str]]:
        """`ids_de_chunks` para vários documentos de uma vez, em ordem de leitura.

        Mesmo motivo do método acima: o ranqueador de nome pergunta isto para
        `candidatos` documentos por consulta, e eram ~79 idas ao banco por
        consulta no acervo corporativo. Documento sem chunk não aparece no
        resultado — igual à lista vazia que `ids_de_chunks` devolvia.
        """
        por_path: dict[str, list[str]] = {}
        unicos = list(dict.fromkeys(paths))
        for inicio in range(0, len(unicos), 900):
            lote = unicos[inicio : inicio + 900]
            marcas = ",".join("?" * len(lote))
            if root_id and self._usa_ocorrencia():
                from .ocorrencia import id_de

                oid = [id_de(root_id, path) for path in lote]
                linhas = self.con.execute(
                    "SELECT path, id FROM chunks WHERE ocorrencia_id IN ("
                    + ",".join("?" * len(oid))
                    + ") ORDER BY path, ordinal",
                    oid,
                ).fetchall()
            else:
                linhas = self.con.execute(
                    f"SELECT path, id FROM chunks WHERE path IN ({marcas}) ORDER BY path, ordinal",
                    lote,
                ).fetchall()
            for linha in linhas:
                por_path.setdefault(linha["path"], []).append(linha["id"])
        return por_path

    def ids_de_chunks(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> list[str]:
        """Só os ids de um documento, em ordem de leitura — sem carregar texto.

        Existe separado de `chunks_de` porque o ranqueador de nome pergunta isto
        para `candidatos` documentos por consulta, e só para saber quais trechos o
        documento tem. Trazer `texto` junto seria ler o documento inteiro do disco
        para descartá-lo, `candidatos` vezes, dentro do caminho de consulta.
        """
        if self._usa_ocorrencia() and (root_id or ocorrencia_id):
            chave = self._chave_ocorrencia(
                path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
            linhas = self.con.execute(
                "SELECT id FROM chunks WHERE ocorrencia_id = ? ORDER BY ordinal",
                (chave,),
            ).fetchall()
        else:
            linhas = self.con.execute(
                "SELECT id FROM chunks WHERE path = ? ORDER BY ordinal", (path,)
            ).fetchall()
        return [linha[0] for linha in linhas]

    def chunks_de(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> list[ChunkArmazenado]:
        if self._usa_ocorrencia() and (root_id or ocorrencia_id):
            chave = self._chave_ocorrencia(
                path, root_id=root_id, ocorrencia_id=ocorrencia_id
            )
            linhas = self.con.execute(
                "SELECT c.id, c.path, c.ordinal, c.trilha, c.locator, c.kind, c.texto, "
                "c.ocorrencia_id, COALESCE(d.root_id, '') AS root_id "
                "FROM chunks c LEFT JOIN documentos d ON c.ocorrencia_id = d.ocorrencia_id "
                "WHERE c.ocorrencia_id = ? ORDER BY c.ordinal", (chave,)
            ).fetchall()
        else:
            linhas = self.con.execute(
                "SELECT id, path, ordinal, trilha, locator, kind, texto, ocorrencia_id "
                "FROM chunks WHERE path = ? ORDER BY ordinal", (path,)
            ).fetchall()
        return [ChunkArmazenado(**dict(l)) for l in linhas]

    def vizinhos(self, chunk_id: str, janela: int = 1) -> list[ChunkArmazenado]:
        """Adjacent chunks in the same document — context expansion (F2)."""
        atual = self.chunk(chunk_id)
        if atual is None:
            return []
        linhas = self.con.execute(
            "SELECT c.id, c.path, c.ordinal, c.trilha, c.locator, c.kind, c.texto, c.ocorrencia_id, "
            "COALESCE(d.root_id, '') AS root_id FROM chunks c "
            "LEFT JOIN documentos d ON c.ocorrencia_id = d.ocorrencia_id "
            "WHERE c.ocorrencia_id = ? AND c.ordinal BETWEEN ? AND ? ORDER BY c.ordinal",
            (atual.ocorrencia_id or atual.path, atual.ordinal - janela, atual.ordinal + janela),
        ).fetchall()
        return [ChunkArmazenado(**dict(l)) for l in linhas]

    def vizinhos_de(self, chunk_ids: Sequence[str], janela: int = 1) -> dict[str, list[ChunkArmazenado]]:
        """`vizinhos` para vários trechos numa ida ao banco — expansão de contexto.

        `vizinhos()` custa duas consultas por trecho (a do próprio, a da faixa), e
        `expandir_contexto` a chama uma vez por acerto: com `k = 8` eram 16 idas
        ao banco só para anexar o parágrafo seguinte. Aqui são duas, quantos
        forem os acertos.

        A faixa de cada acerto vira uma cláusula do mesmo `WHERE`, e não um
        `path IN (...)` seguido de filtro em Python: o documento pode ter milhares
        de trechos, e trazer o texto de todos para descartar quase todos seria
        trocar uma ida ao banco por muitos megabytes.

        Chave ausente no resultado é o mesmo que a lista vazia de `vizinhos()`:
        o trecho não está no registro.
        """
        alvos = self.chunks_por_id(chunk_ids)
        if not alvos:
            return {}

        condicoes: list[str] = []
        parametros: list[object] = []
        for alvo in alvos.values():
            condicoes.append(
                "(ocorrencia_id = ? AND ordinal BETWEEN ? AND ?)"
            )
            parametros += [
                alvo.ocorrencia_id or alvo.path,
                alvo.ordinal - janela,
                alvo.ordinal + janela,
            ]

        linhas = self.con.execute(
            "SELECT id, path, ordinal, trilha, locator, kind, texto, ocorrencia_id FROM chunks WHERE "
            + " OR ".join(condicoes)
            + " ORDER BY path, ordinal",
            parametros,
        ).fetchall()

        por_path: dict[str, list[ChunkArmazenado]] = {}
        for linha in linhas:
            armazenado = ChunkArmazenado(**dict(linha))
            por_path.setdefault(
                armazenado.ocorrencia_id or armazenado.path, []
            ).append(armazenado)

        # Uma faixa por acerto, recortada da lista do documento: dois acertos no
        # mesmo arquivo têm janelas diferentes, e podem se sobrepor.
        return {
            chunk_id: [
                c
                for c in por_path.get(alvo.ocorrencia_id or alvo.path, ())
                if alvo.ordinal - janela <= c.ordinal <= alvo.ordinal + janela
            ]
            for chunk_id, alvo in alvos.items()
        }

    # --- grafo derivado (F4) ----------------------------------------------

    def registrar_mencoes(
        self,
        path: str,
        mencoes: Sequence[tuple[str, str, str]],
        *,
        root_id: str = "",
        ocorrencia_id: str = "",
    ) -> int:
        """Substitui as menções de um documento. Devolve quantas ficaram.

        Substitui em vez de acrescentar porque a passada do grafo é idempotente
        por documento: rodar duas vezes tem que dar o mesmo resultado, e um
        identificador que saiu do texto depois de uma edição tem que sair do
        grafo — senão a aresta sobrevive ao fato que a justificava.
        """
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        if self._usa_ocorrencia():
            self.con.execute("DELETE FROM mencoes WHERE ocorrencia_id = ?", (chave,))
        else:
            self.con.execute("DELETE FROM mencoes WHERE path = ?", (path,))
        if mencoes:
            self.con.executemany(
                "INSERT OR REPLACE INTO mencoes(ocorrencia_id, path, tipo, valor, chunk_id) VALUES (?,?,?,?,?)",
                [(chave, path, t, v, c) for t, v, c in mencoes],
            )
        return len(mencoes)

    def mencoes_de(
        self, path: str, *, root_id: str = "", ocorrencia_id: str = ""
    ) -> list[tuple[str, str, str]]:
        chave = self._chave_ocorrencia(
            path, root_id=root_id, ocorrencia_id=ocorrencia_id
        )
        return [
            (l["tipo"], l["valor"], l["chunk_id"])
            for l in self.con.execute(
                "SELECT tipo, valor, chunk_id FROM mencoes WHERE ocorrencia_id = ? ORDER BY tipo, valor",
                (chave,),
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

    def verificar_consistencia(self) -> dict[str, Any]:
        """Compara integridade entre SQLite e LanceDB por identidade (FND-02a)."""
        from .integridade import verificar_consistencia

        return verificar_consistencia(self)

    def diagnosticar_integridade(self, lote: int = 1000) -> DiagnosticoIntegridade:
        """Diagnóstico paginado e detalhado de integridade entre stores (FND-02a)."""
        from .integridade import diagnosticar_integridade

        return diagnosticar_integridade(self, lote=lote)

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
        raiz_coluna = "root_id" if self._usa_ocorrencia() else "raiz AS root_id"
        linhas = list(self.con.execute(f"SELECT path, mtime, {raiz_coluna} FROM documentos"))
        duplicados = {
            r["path"] for r in linhas
            if sum(x["path"] == r["path"] for x in linhas) > 1
        }
        return {
            (
                f"{r['root_id']}\0{r['path']}"
                if r["path"] in duplicados
                else r["path"]
            ): r["mtime"]
            for r in linhas
        }

    def paths_com_chunks(self) -> list[str]:
        """Distinct paths that actually have chunks — what search can return.

        The name ranker builds on this rather than on `documentos`: a document
        registered with status `vazio` or `travado` has no chunk and can never be
        retrieved, and a chunk whose registry row is missing would silently lose
        its name signal. Ranking over what is retrievable keeps the two in step.
        """
        return [l["path"] for l in self.con.execute("SELECT DISTINCT path FROM chunks ORDER BY path")]
