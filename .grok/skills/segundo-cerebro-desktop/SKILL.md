---
name: segundo-cerebro-desktop
description: >
  Coordinate Segundo Cérebro work on the GPU desktop (two GTX 980 Ti, new
  private corpus, no corporate data, Grok Build). Load before any change in
  this repo on this machine. Triggers: start work, next steps, F3.6, CUDA,
  980 Ti, smoke test, pipeline, index, embeddings, ranking, PR, branch,
  collaborate, notebook, Claude Code, synthetic corpus, golden set, config.
  Use when the user runs /segundo-cerebro-desktop or /desktop.
---

# Desktop — Grok neste repositório

Você está no **desktop**. Duas 980 Ti, corpus novo, **sem** o acervo corporativo.
O outro lado é Claude Code no notebook, dono dos números corporativos.

1. Leia `docs/colaboracao.md` inteiro. É a fonte. Não resuma regras de memória.
2. `git pull origin main`. Trabalhe numa branch `f36-*` ou `onboarding-*`, nunca em `main`.
   A entrega atual desta máquina está em `onboarding-golden`.
3. Declare na primeira resposta: setup=desktop, branch, fase, o que não vai tocar.

## Você pode

- F3.6: smoke CUDA primeiro (`py -m segundocerebro.index.smoke_cuda`). Pipeline só depois de passar.
- Corpus sintético, `perguntas.example.jsonl`, `config.sintetico.toml`.
- Uma `[[base]]` nova para o acervo **privado deste computador**. Não mexa em `[padrao]`.
- Recalibrar estimativa de indexação em GPU.

## Você recusa

- Alterar `retrieve/*`, pesos padrão em `config.py`, `Chunking`, o modelo padrão.
- Colocar `cuda` (ou threads, ou provider) em `model_id`.
- Editar `CLAUDE.md` além de um ponteiro de uma linha para `docs/colaboracao.md`.
- Inventar números da condição C. Você não tem o conjunto dourado corporativo.
- Começar F4, F5, glossário corporativo, ou um juiz de rerank que reordene sozinho.
- Commitar `config.toml`, `census.toml`, `perguntas.jsonl`, índices, ou caminhos do acervo privado.

## PR

O corpo começa com o bloco da seção 7 de `docs/colaboracao.md`.
CI é Windows + CPU + sem `perguntas.jsonl`: a suíte padrão tem que passar sem GPU.

CUDA 11.8 ou 12.x, nunca 13. Driver 582.x: não subir para 590+.
`sm_52` não tem FP16/INT8 úteis. Int8 é ideia do notebook.

Slash: `/segundo-cerebro-desktop` ou `/desktop`
