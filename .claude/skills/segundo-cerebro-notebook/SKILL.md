---
name: segundo-cerebro-notebook
description: >
  Coordinate Segundo Cérebro work on the corporate notebook (Claude Code,
  original corpus, real golden set, no GPU). Load before any change in this
  repo on that machine. Triggers: start work, next steps, ranking, eval,
  golden set, F4, Meetings, transcrição, grafo, neighbors, msg, eml, parser,
  legado, OLE, ondas, g036, g010, g045, rerank, famílias, PR, branch, desktop,
  Grok, 980 Ti, F3.6, collaborate, condition C, regra de ouro, base desconhecida,
  E1, E5, efeito mínimo, foco, prioridade.
  Use when the user runs /segundo-cerebro-notebook or /notebook.
---

# Notebook — Claude Code neste repositório

Você está no **notebook**. Acervo corporativo e conjunto dourado real.
O outro lado é Grok Build no desktop (duas 980 Ti, corpus privado dele,
**sem** estes documentos).

1. Leia [`docs/regra-de-ouro.md`](../../../docs/regra-de-ouro.md) **primeiro**.
   Ela tem precedência sobre prioridade herdada de dossiê, guia ou fila: o produto
   é para um leigo apontando uma pasta que nunca vimos.
2. Leia [`docs/colaboracao.md`](../../../docs/colaboracao.md) inteiro. É a
   fonte. Não resuma regras de memória — esta skill diz *quem você é*, não as
   regras.
3. `git pull origin main`. Trabalhe numa branch `f4-*` (ou `e*-*`), nunca em
   `main`.
4. Depois de `colaboracao.md`, leia a §6 e a seção **Pacotes** do `ROADMAP.md`.
   Pacote da vez: **`E1` endurecido** (as sete condições do laudo). A `F4-P` corre
   em paralelo **só** como conserto do caminho entregue. Não pegue F4-L, F4-W nem
   F6-A.
5. Declare na primeira resposta: setup=notebook, branch, fase, o que não vai
   tocar — e **o que isto muda para quem instala amanhã numa base que não
   conhecemos**. Se a resposta a essa última só existe em termos do nosso acervo,
   diga isso em voz alta: é pacote de laboratório, e ele fica atrás de qualquer
   item de produto.

## Estado em 25/08/2026

Os números vivos estão na §6 de `docs/colaboracao.md`. F1–F3.6 fechadas; F4 em
curso; a **F6 virou porta de fase** — nenhuma fase F4+ fecha sem o teste em
máquina que não é nossa. Os pacotes dela seguem sendo do desktop e do painel, mas
a porta é de todos. Pacotes no `ROADMAP.md`.

A lista de “o que o desktop já fez” saiu daqui de propósito: envelheceu duas
vezes em três dias e passou a contradizer a §6. Ela vive na §6 de
`colaboracao.md`, num lugar só.

**O que está na sua mão agora:** o **`E1` endurecido** — gerador sintético como
código versionado, as sete condições de
[`docs/avaliacao-pacote-e1.md`](../../../docs/avaliacao-pacote-e1.md). Ele passou à
frente da `F4-P` em 25/08/2026 porque é o instrumento de base desconhecida; a
ordem anterior era `E5` → `F4-P` → `E1`.

A **`F4-P` encolheu ao defeito** e continua valendo: reconciliar os dois caminhos
de recuperação, com aceite binário — `buscar_chunks` alcança o que `search`
alcança (cross-lingual recall@20 de 0,750 para 1,000), sem derrubar o piso. **A
varredura de peso por tipo de fonte saiu do escopo:** melhor caso teórico +0,032
de MRR agregado, efeito concentrado em 11 perguntas, que é a forma que o `E5`
provou indetectável. Não regredir o que já está em curso nela.

## Você pode

- Medir e mudar ranking (`retrieve/*`, pesos da base corporativa) **com** número
  antes/depois no dourado real.
- F4 no acervo corporativo, com número antes/depois.
- Escrever parser de formato que seja seu na §6 — **não** o despachante
  (`parsers/__init__.py`) sem combinar: é “um de cada vez”.
- Revisar PRs do desktop: tabela da §1 e regras 2 e 4 de `docs/colaboracao.md`.
- **Declarar hipótese, fatia e efeito mínimo antes de medir** — e encerrar o
  pacote no empate, com "hipótese refutada" no doc. Isso é entrega, não desistência.
- **Generalizar defeito**: ao achar um, entregar a classe e o método que a pega
  sozinha, não só o caso (regra 12).
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
- **Rodar varredura cujo efeito esperado é menor que o ruído medido da fatia.**
  Fazer a conta e registrar que ela não se paga é o trabalho; a grade não é.
- **Adotar em `[padrao]` ganho medido num acervo só** — a não ser que seja custo
  zero por consulta e independente de acervo (regra 10).
- **Reabrir porta já refutada** sem instrumento novo ou acervo novo. A porta 3 já
  foi varrida três vezes.
- **Fechar pacote com conserto pontual** sem dizer que classe de defeito ficou
  fechada e o que passa a pegá-la (regra 12).
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

O corpo começa com o bloco da §7 de `docs/colaboracao.md` — que desde 25/08 tem
três linhas novas: base desconhecida, efeito mínimo, classe generalizada.
`Corpus da medição: corporativo`. Cite o arquivo de métrica (gitignorado) pelo
nome, não cole o conteúdo no PR. Apague a branch depois do merge.

Slash: `/segundo-cerebro-notebook` ou `/notebook`
