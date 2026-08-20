---
name: segundo-cerebro-notebook
description: >
  Coordinate Segundo Cérebro work on the corporate notebook (Claude Code,
  original corpus, real golden set, no GPU). Load before any change in this
  repo on that machine. Triggers: start work, next steps, ranking, eval,
  golden set, F2, F3, g036, g010, rerank, famílias, PR, branch, desktop,
  Grok, 980 Ti, F3.6, collaborate, condition C.
  Use when the user runs /segundo-cerebro-notebook or /notebook.
---

# Notebook — Claude Code neste repositório

Você está no **notebook**. Acervo corporativo e conjunto dourado real.
O outro lado é Grok Build no desktop (duas 980 Ti, corpus novo, **sem** estes documentos).

1. Leia `docs/colaboracao.md` inteiro. É a fonte. Não resuma regras de memória.
2. `git fetch origin && git checkout onboarding-golden && git pull`. Esta branch
   é a entrega do desktop (F3.6 + sintético + skills). **Não** edite
   `index/indexer.py`, `index/embeddings.py`, `index/gpu_pool.py` nem
   `index/smoke_cuda.py` até ela estar em `main`.
3. Depois de `colaboracao.md`: `docs/portabilidade-f36.md` e `docs/smoke-cuda.md`.
4. Declare na primeira resposta: setup=notebook, branch, fase, o que não vai tocar.

## O que o desktop já fez (20/08/2026) — não refazer

- Smoke CUDA passou nas 980 Ti. MiniLM no CUDA = NaN; e5-large finito.
- Pipeline: parse em threads + um processo de embed por GPU.
- Corpus sintético + `perguntas.example.jsonl` + `config.sintetico.toml`.
- Painel: retomada no logon (checkbox), Pausar/Continuar/Cancelar.
- Índice sintético GPU **não** está no Git. F3.6 **fechada** em 20/08: vetor
  1,0000; recall@1 0,850 / recall@10 1,000 idênticos nos dois lados; consulta
  no notebook sem reembeddar. Ver `docs/portabilidade-f36.md`.

## Sua vez

- Fechar a F3: uma pergunta multi-hop real, traço gitignorado em
  `docs/traco-f3-uso-real.md`.
- Revisar esta branch pela tabela de donos (seção 1 de `colaboracao.md`).
- Ranking só com número antes/depois no dourado **corporativo**.
  Métrica do sintético (`corpus=sintetico`) não substitui a condição C.

## Você pode

- Medir e mudar ranking (`retrieve/*`, pesos da base corporativa) **com** número antes/depois no dourado real.
- Fechar a F3: uma pergunta multi-hop real, traço em `docs/traco-f3-uso-real.md` (gitignorado).
- Revisar PRs do desktop: tabela da seção 1 e regras 2 e 4 de `docs/colaboracao.md`.
- Editar `CLAUDE.md` — é o seu retomador. Não apague o ponteiro para `docs/colaboracao.md`.

## Você recusa

- Escrever código CUDA, escolher build de `onnxruntime-gpu`, ou “adiantar” o pipeline da F3.6 a partir da documentação.
- Mudar `model_id`, `max_chars` ou o modelo padrão sem acordo explícito com o desktop — rebuilda o índice.
- Tratar métrica do corpus sintético como se fosse a condição C.
- Commitar `perguntas.jsonl`, relatórios de ablação com nome real, `config.toml` ou o índice.
- Começar F4/F5 daqui enquanto a F3 não tem traço e a F3.6 não tem smoke.

## PR do desktop

Primeira pergunta, antes de “melhorar” o diff: **viola a tabela de donos?**
Se o PR põe `cuda` em `model_id`, muda chunking, ou altera `[padrao]`, peça mudança.

## PR seu

O corpo começa com o bloco da seção 7 de `docs/colaboracao.md`.
`Corpus da medição: corporativo`. Cite o arquivo de métrica (gitignorado) pelo nome, não cole o conteúdo no PR.

Slash: `/segundo-cerebro-notebook` ou `/notebook`
