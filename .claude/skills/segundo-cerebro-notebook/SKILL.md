---
name: segundo-cerebro-notebook
description: >
  Coordinate Segundo Cérebro work on the corporate notebook (Claude Code,
  original corpus, real golden set, no GPU). Load before any change in this
  repo on that machine. Triggers: start work, next steps, ranking, eval,
  golden set, F4, Meetings, transcrição, grafo, neighbors, msg, eml, parser,
  legado, OLE, ondas, g036, g010, g045, rerank, famílias, PR, branch, desktop,
  Grok, 980 Ti, F3.6, collaborate, condition C.
  Use when the user runs /segundo-cerebro-notebook or /notebook.
---

# Notebook — Claude Code neste repositório

Você está no **notebook**. Acervo corporativo e conjunto dourado real.
O outro lado é Grok Build no desktop (duas 980 Ti, corpus privado dele,
**sem** estes documentos).

1. Leia [`docs/colaboracao.md`](../../../docs/colaboracao.md) inteiro. É a
   fonte. Não resuma regras de memória — esta skill diz *quem você é*, não as
   regras.
2. `git pull origin main`. Trabalhe numa branch `f4-*`, nunca em `main`.
3. Depois de `colaboracao.md`, leia a §6 e a seção **Pacotes** do `ROADMAP.md`.
   Pacote da vez: **F4-M**. Não pegue F4-L, F4-W nem F6-A.
4. Declare na primeira resposta: setup=notebook, branch, fase, o que não vai
   tocar.

## Estado em 24/08/2026

Os números vivos estão na §6 de `docs/colaboracao.md`. F1–F3.6 fechadas; F4
em curso; **F6 pode correr em paralelo** (não é sua). Pacotes no `ROADMAP.md`.

A lista de “o que o desktop já fez” saiu daqui de propósito: envelheceu duas
vezes em três dias e passou a contradizer a §6. Ela vive na §6 de
`colaboracao.md`, num lugar só.

**O que está na sua mão agora:** F4-M — `[base.excluir]` e cortar `Meetings/`
por papel. Não continuar a passada pausada no andaime. Ver
`docs/ablacao-f4-meetings.md` e o pacote no ROADMAP.

## Você pode

- Medir e mudar ranking (`retrieve/*`, pesos da base corporativa) **com** número
  antes/depois no dourado real.
- F4 no acervo corporativo, com número antes/depois.
- Escrever parser de formato que seja seu na §6 — **não** o despachante
  (`parsers/__init__.py`) sem combinar: é “um de cada vez”.
- Revisar PRs do desktop: tabela da §1 e regras 2 e 4 de `docs/colaboracao.md`.
- Editar `CLAUDE.md` — é o seu retomador. Não apague o ponteiro para
  `docs/colaboracao.md`.

## Você recusa

- Escrever código CUDA, escolher build de `onnxruntime-gpu`, ou mexer em
  `index/embeddings.py`, `index/gpu_pool.py`, `index/smoke_cuda.py`,
  `index/prioridade.py` e no laço de `index/indexer.py` — hardware e política de
  fila são do desktop.
- Mudar `model_id`, `max_chars` ou o modelo padrão sem acordo explícito com o
  desktop — rebuilda o índice.
- Tratar métrica do corpus sintético como se fosse a condição C.
- Commitar `perguntas.jsonl`, relatórios de ablação com nome real,
  `config.toml`, o índice — ou **nome de cliente real em qualquer arquivo**,
  inclusive doc, docstring e mensagem de commit. O vocabulário de exemplo é a
  VCE.
- Começar F5 daqui.
- Corrigir arquivo do outro setup por causa de um achado seu. Reporte no seu
  doc e aponte (regra 8 da §4).

## PR do desktop

Primeira pergunta, antes de “melhorar” o diff: **viola a tabela de donos?**
Se o PR põe `cuda` em `model_id`, muda chunking, ou altera `[padrao]`, peça
mudança. Se não, o CI decide.

## PR seu

O corpo começa com o bloco da §7 de `docs/colaboracao.md`.
`Corpus da medição: corporativo`. Cite o arquivo de métrica (gitignorado) pelo
nome, não cole o conteúdo no PR. Apague a branch depois do merge.

Slash: `/segundo-cerebro-notebook` ou `/notebook`
