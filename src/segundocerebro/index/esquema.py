"""O esquema do registro — as tabelas, os índices, e a razão de cada um.

Saiu de `index/store.py` em 30/08/2026, ao abrir o `J.b1`. Não é arrumação:
`store.py` está na escada de `tests/test_tamanho_dos_modulos.py`, cuja tabela
**só desce**, e o `J.b1` precisa acrescentar um índice — o de
`documentos.sha256`, sem o qual resolver `doc_id -> caminhos[]` é varredura de
tabela. Arquivo que só desce não recebe linha nova, e o esquema é a parte do
`store.py` com razão de mudar própria: a forma dos dados, não o acesso a eles.

Os comentários de cada tabela vieram **verbatim**. Eles têm data e número, são
ADR embutida (`CLAUDE.md`, convenções), e refactor que apaga histórico de
decisão é reprovação mesmo com a suíte verde.

`Store.__init__` roda `executescript(ESQUEMA)` a cada abertura, então
`CREATE ... IF NOT EXISTS` alcança banco antigo sem migração — para tabela e
para índice. O que ele **não** alcança é coluna nova em tabela que já existe;
essa é a razão de `Store.COLUNAS_ACRESCENTAVEIS` existir ao lado.
"""

from __future__ import annotations

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

-- O `doc_id` público do `J.b1` é o prefixo deste hash, e a primeira coisa que
-- um agente faz com um id é resolvê-lo de volta para caminho. Sem índice, cada
-- resolução varre `documentos` inteira — é o N+1 deste repositório com outro
-- nome: a **forma** do acesso é a mesma no índice de quatro trechos da suíte e
-- no acervo de 2.156 documentos, e só o N muda.
--
-- O índice serve também à consulta por faixa de prefixo
-- (`sha256 >= id AND sha256 < sucessor`), que é como `acesso/registro.py`
-- resolve id curto. `LIKE 'prefixo%'` não serviria: a otimização de prefixo do
-- SQLite depende de `case_sensitive_like`, e faixa não depende de PRAGMA nenhum.
CREATE INDEX IF NOT EXISTS idx_documentos_sha256 ON documentos(sha256);

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

-- Vocabulário virtual: expõe frequência documental sem duplicar os postings.
-- A busca usa isto para não varrer termos cujo IDF o próprio FTS5 reduz a
-- 1e-6 por aparecerem em pelo menos metade dos chunks. É leitura dinâmica do
-- índice, não uma tabela derivada que precise de trigger ou reconstrução.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_vocab USING fts5vocab(chunks_fts, 'row');

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

-- FND-02b: journal of one document write across SQLite and LanceDB.
-- Inserted and committed BEFORE any Lance delete/add. A row that is not
-- finished is a crash: recovery either confirms the intended ids or aborts
-- the path so the next indexer pass reprocesses the file. Readers that do
-- not know this table ignore it. Never delete a pending row to "roll back
-- a version" — only a completed or aborted recovery removes it.
CREATE TABLE IF NOT EXISTS operacoes (
    id            TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    tipo          TEXT NOT NULL,
    etapa         TEXT NOT NULL,
    model_id      TEXT NOT NULL DEFAULT '',
    chunk_ids     TEXT NOT NULL DEFAULT '[]',
    documento     TEXT NOT NULL DEFAULT '{}',
    mtime         REAL NOT NULL DEFAULT 0,
    criada_em     TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operacoes_path ON operacoes(path);
"""
