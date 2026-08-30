# Segundo Cérebro

[![tests](https://github.com/GCamposGit/SegundoCerebro/actions/workflows/tests.yml/badge.svg)](https://github.com/GCamposGit/SegundoCerebro/actions/workflows/tests.yml)
[![coverage](https://img.shields.io/badge/coverage-%E2%89%A5_80%25-informational)](.github/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

Servidor **MCP** de recuperação de alta precisão sobre uma base de conhecimento
pessoal e corporativa. Pastas em disco e SharePoint, com PDF, Word, Excel e
PowerPoint. Não gera texto e não tem interface própria: ele expõe ferramentas
de busca, o modelo de linguagem vem do cliente MCP que você já usa.

## A ideia em um parágrafo

O gargalo de um RAG corporativo raramente é o modelo, é o custo por consulta e
a dependência de fornecedor que ele cria. Este projeto inverte a arquitetura
usual: em vez de um app que chama uma API de geração a cada pergunta, o
**modelo vem do cliente MCP já pago por assento** (Claude Code, Claude Desktop,
qualquer cliente MCP), e o servidor só recupera. Embeddings e reranking rodam
localmente. Resultado: **custo marginal zero por consulta**, troca de modelo
sem alterar uma linha de código, e raciocínio multi-hop nativo porque o loop
de agente é do cliente, não algo que o servidor precisa reimplementar.

Nenhum documento sai da máquina. O servidor devolve trechos com procedência
(arquivo, seção, id estável); quem escreve a resposta final é o assistente que
o usuário já usa.

## O que ele faz — e o que deliberadamente não faz

| Faz | Não faz |
|---|---|
| Busca híbrida: denso (significado) + BM25 (termo exato) + nome de arquivo, fundidos por RRF ponderado | Gerar, resumir ou opinar sobre o conteúdo — isso é trabalho do cliente MCP |
| Reranking opcional com cross-encoder como quarto ranqueador | Chamar qualquer API paga no caminho de consulta |
| Expansão de contexto (parágrafo antes/depois) e vizinhos por identificador derivado | Orquestrar multi-hop — o loop de agente já faz isso |
| Isolamento físico entre bases (índice + processo de servidor por base) | Misturar bases por filtro de metadado numa consulta compartilhada |
| Painel local para ajustar pesos e medir, sem escrever código | Ficar no caminho de consulta — o servidor MCP funciona com o painel desinstalado |

## Arquitetura em uma imagem

```
Cliente MCP (Claude Code, Claude Desktop, ...)
  │  modelo de linguagem, loop de agente, geração — tudo aqui
  ▼
Servidor MCP (search · read_note · neighbors)
  │  recuperação híbrida, reranking, expansão de contexto — tudo local
  ▼
Índice: LanceDB (vetores) + SQLite FTS5 (lexical, grafo, metadados)
  │
  ▼
Documentos: pastas em disco + SharePoint sincronizado (PDF, DOCX, XLSX, PPTX, MD)
```

Decisões e justificativas completas em [ARCHITECTURE.md](ARCHITECTURE.md).

## Invariantes de projeto

Sete regras que qualquer mudança precisa respeitar — o motivo de cada uma está
em [ARCHITECTURE.md](ARCHITECTURE.md):

1. Nenhuma chamada a API paga no caminho de consulta.
2. Nenhuma ferramenta que gere texto (`answer`, `summarize` não existem aqui).
3. Multi-hop é do cliente — o servidor oferece primitivas componíveis.
4. Toda mudança em chunking, embedding ou ranking passa pelo eval; sem número
   antes/depois, a mudança não entra.
5. Todo retorno de ferramenta carrega procedência e id estável.
6. O painel de ajuste está fora do caminho de consulta — há teste provando que
   o servidor MCP funciona com o painel desinstalado.
7. Isolamento entre bases é físico (diretório de índice + processo de servidor
   próprios), nunca um filtro sobre uma consulta compartilhada.

## Resultados medidos

Toda otimização de precisão neste projeto é validada contra um conjunto de
perguntas com fonte conhecida, com métrica antes/depois (invariante 4).

**A progressão da F1 à F2**, corpus corporativo de então (1.601 documentos,
92 mil chunks), medida entre 13 e 20/08/2026:

| Configuração | recall@1 | MRR@10 |
|---|---:|---:|
| Baseline (busca por nome de arquivo) | 0,467 | 0,592 |
| + recuperação híbrida (denso + BM25 + nome) | 0,600 | 0,736 |
| + famílias de versão (F2) | 0,644 | — |
| + reranking com cross-encoder (F2) | **0,678** | **0,785** |

**A configuração que o produto entrega hoje é outra, e o número também.** O
corpus cresceu para 2.156 documentos e o **reranking está desligado por custo**:
ele vale +0,011 de nDCG@5 e custa 6,9× por consulta, o que contradiz a razão de
existir do projeto. A linha de base atual, corpus corporativo, sem rerank, é
recall@1 **0,551** e MRR **0,680** no caminho `search`, e 0,551 / 0,696 no
caminho que o cliente MCP executa — os números vivos ficam na §6 de
[`docs/colaboracao.md`](docs/colaboracao.md), num lugar só.

As duas tabelas medem corpora diferentes e **não são comparáveis entre si**: um
conjunto dourado de 62 perguntas alcança 38,5% das pastas do índice atual, então
crescer o corpus baixa a métrica sem nada ter piorado. É por isso que a cobertura
passou a ser medida a cada relatório em vez de escrita à mão
([`docs/dourado-cobertura.md`](docs/dourado-cobertura.md)).

A lição que se repetiu duas vezes durante o projeto: **o consenso de
ranqueadores independentes vale mais que qualquer juiz isolado** — aconteceu
com o BM25 e de novo com o cross-encoder, que só melhora o resultado quando
entra como um quarto voto na fusão, nunca como substituto da ordenação.

**1.288 testes automatizados** (`pytest`) em 29/08/2026, rodando em CI a cada
push junto de `ruff` e `pyright`. A data está aí de propósito: número escrito à
mão envelhece calado, e este envelheceu de 480 para 1.288 sem ninguém notar.

## Stack

Python 3.12 · [`mcp`](https://modelcontextprotocol.io/) · `fastembed`
(multilingual-e5-large / MiniLM) · `bge-reranker-v2-m3` · LanceDB · SQLite FTS5
· `pymupdf4llm` · `python-docx` · `openpyxl` · `python-pptx` · Starlette +
Uvicorn (painel) · `pytest`

## Estrutura

```
src/segundocerebro/
  ingest/      parsers PDF/DOCX/XLSX/PPTX/MD, chunking, natureza do documento
  index/       LanceDB (vetores) + SQLite (registro, FTS5), estimativa e retomada
               indexer.py é o laço; cli/trava/travas/repesca/resultado ao redor dele
  retrieve/    híbrido, RRF, famílias de versão, ranqueador de nome, reranking
               contrato.py — `Hit` e `Retriever`, que o eval importa (nunca o contrário)
  mcp/         superfície de ferramentas MCP e geração de .mcp.json
  painel/      tela local de ajuste (Starlette) — opcional, fora do caminho de consulta
eval/
  golden/      formato do conjunto dourado (o conteúdo real não é versionado — ver abaixo)
  rodar.py, comparar.py, harness.py, metrics.py, baselines.py, entregue.py
  gerador/     corpus sintético versionado (camada 2 — base desconhecida)
conftest.py    o que vale para as duas suítes: recusa índice em escrita, devolve os.environ
tests/         isolados com tmp_path e monkeypatch; guardas de fronteira e de tamanho
docs/          decisões, ablações e métricas — índice em docs/README.md
```

## Como rodar

```bash
pip install -e .

# 1. Censo do acervo — quantos arquivos, de que tipo, antes de indexar
cp census.example.toml census.toml   # preencher com as raízes reais
segundocerebro-censo --config census.toml --out docs/censo.md

# 2. Indexar
segundocerebro-indexar

# 3. Servir via MCP
segundocerebro-mcp

# 4. (opcional) Painel local para ajustar pesos sem código
segundocerebro-painel
```

Múltiplas bases (pessoal, trabalho, ...) e pesos de recuperação são
configurados em `config.toml` — ver [`config.example.toml`](config.example.toml)
e a seção de bases em [ARCHITECTURE.md](ARCHITECTURE.md) §2.

## Testes

```bash
py -m pytest tests/ eval/ -q        # suíte padrão — ~2 min, sem GPU e sem modelo
py -m pytest -m modelo              # com o encoder real — baixa ~2 GB na 1ª vez
```

## Documentação

| Arquivo | Conteúdo |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Decisões de projeto e justificativas |
| [ROADMAP.md](ROADMAP.md) | Fases com critérios de saída verificáveis |
| [CLAUDE.md](CLAUDE.md) | Guia de desenvolvimento e estado atual, fase a fase |
| [docs/arquitetura-tecnica.md](docs/arquitetura-tecnica.md) | Substituições de catálogo, por que FTS5 e não BM25 vetorial |
| [docs/painel-de-ajuste.md](docs/painel-de-ajuste.md) | Proposta e regras do painel local |
| [docs/estimativa-de-indexacao.md](docs/estimativa-de-indexacao.md) | Método de estimativa de tempo/esforço de indexação |
| [docs/usar-o-mcp.md](docs/usar-o-mcp.md) | Como registrar e usar o servidor num cliente MCP |
| [docs/truncagem-silenciosa.md](docs/truncagem-silenciosa.md) | Post-mortem de um defeito que custou 80% do texto indexado |
| [docs/colaboracao.md](docs/colaboracao.md) | Dois setups (desktop GPU + notebook): donos, branches, o que não commitar |
| [docs/smoke-cuda.md](docs/smoke-cuda.md) | F3.6: smoke CUDA nas 980 Ti, pin ORT 1.18, MiniLM=NaN |
| [docs/portabilidade-f36.md](docs/portabilidade-f36.md) | Índice sintético feito no desktop, consulta no notebook sem reembeddar |

### Sobre o conjunto de avaliação

O conjunto dourado real (`eval/golden/perguntas.jsonl`) e os relatórios de
ablação que o citam por conteúdo **não estão neste repositório** — ver
[`eval/golden/README.md`](eval/golden/README.md).

Um clone fresco usa o exemplo sintético (`eval/golden/perguntas.example.jsonl`
+ `eval/sintetico/corpus/` + `config.sintetico.toml`). Ele demonstra o formato
e alimenta o CI; não mede o acervo de ninguém.

## Licença

[MIT](LICENSE).
