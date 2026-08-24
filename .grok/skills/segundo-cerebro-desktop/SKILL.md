---
name: segundo-cerebro-desktop
description: >
  Coordinate Segundo Cérebro work on the GPU desktop (two GTX 980 Ti, new
  private corpus, no corporate data, Grok Build). Load before any change in
  this repo on this machine. Triggers: start work, next steps, F3.6, F4,
  CUDA, 980 Ti, smoke test, pipeline, index, embeddings, estimativa, ondas,
  prioridade, OLE, legado, PR, branch, collaborate, notebook, Claude Code,
  synthetic corpus, golden set, config.
  Use when the user runs /segundo-cerebro-desktop or /desktop.
---

# Desktop — Grok neste repositório

Você está no **desktop**. Duas 980 Ti, corpus novo, **sem** o acervo corporativo.
O outro lado é Claude Code no notebook, dono dos números corporativos.

1. Leia [`docs/colaboracao.md`](../../../docs/colaboracao.md) inteiro. É a
   fonte. Não resuma regras de memória — esta skill diz *quem você é*, não as
   regras.
2. `git pull origin main`. Trabalhe numa branch `f36-*` ou `onboarding-*`,
   nunca em `main`. **Não deixe trabalho só no stash:** cada fase vira commit
   na branch e PR. O notebook só vê o que está em `main`.
3. Depois de `colaboracao.md`, leia a §6 e a seção **Pacotes** do `ROADMAP.md`.
   Um pacote = um PR = lista de paths. Não pegue pacote do notebook. Se precisar
   editar o ROADMAP, avise antes.
4. Declare na primeira resposta: setup=desktop, branch, fase, o que não vai
   tocar.

## Estado em 24/08/2026

`main` = `677fa22`. F1, F2, F3, F3.5 e F3.6 fechadas; **F4 é a única fase
aberta**. PRs #2 a #6 em `main`, inclusive `f36-fila-ondas` (#6). Suíte padrão
neste clone: 732 verdes (`tests/` + `eval/`).

A lista de entregas fechadas vive na §6 de `colaboracao.md`, num lugar só.
Não repetir aqui — envelhece.

**O que está na sua mão agora:** pacotes F4-L (OLE que mente), F4-W (watcher)
e F6-A (`pip install` sem `PYTHONPATH`). A indexação da base privada deste desktop corre no fundo e
**não** é desculpa para ficar ocioso. **Não** pegar F4-M (`config.py`, painel).

## Você pode

- Hardware, CUDA, `index/embeddings.py`, `index/gpu_pool.py`,
  `index/smoke_cuda.py`, `index/esforco.py`, `index/estimativa.py`,
  `index/prioridade.py` e o laço de `index/indexer.py`.
- Parser que seja seu na §6: hoje `ingest/parsers/ole_texto.py`. **Não** o
  despachante (`parsers/__init__.py`) sem combinar: é “um de cada vez”.
- Corpus sintético, `perguntas.example.jsonl`, `config.sintetico.toml`.
- Uma `[[base]]` nova para o acervo **privado deste computador**. Não mexa em
  `[padrao]` sem o notebook medir.
- Recalibrar estimativa de indexação. Ranking não.

## Você recusa

- Alterar `retrieve/*`, pesos padrão em `config.py`, `Chunking`, o modelo
  padrão.
- Colocar `cuda` (ou threads, ou provider) em `model_id`.
- Editar `CLAUDE.md` além de um ponteiro de uma linha para
  `docs/colaboracao.md`.
- Inventar números da condição C. Você não tem o conjunto dourado corporativo.
- Começar F5, glossário corporativo, ou um juiz de rerank que reordene sozinho.
- Commitar `config.toml`, `census.toml`, `perguntas.jsonl`, índices, caminhos
  do acervo privado — ou **nome de cliente real** em doc, docstring ou
  mensagem de commit. O vocabulário de exemplo é a VCE.
- Corrigir arquivo do outro setup por causa de um achado seu. Reporte no seu
  doc e aponte (regra 8 da §4).

## PR

O corpo começa com o bloco da §7 de `docs/colaboracao.md`.
CI é Windows + CPU + sem `perguntas.jsonl`: a suíte padrão tem que passar sem
GPU. Apague a branch depois do merge.

CUDA 11.8 ou 12.x, nunca 13. Driver 582.x: não subir para 590+.
`sm_52` não tem FP16/INT8 úteis. Int8 é ideia do notebook.

Slash: `/segundo-cerebro-desktop` ou `/desktop`
