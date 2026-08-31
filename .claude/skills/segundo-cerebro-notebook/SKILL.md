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
   O pacote da vez está na §Próximo passo do `CLAUDE.md` — não nesta skill, pelo
   motivo da seção seguinte. Não pegue F4-L, F4-W nem F6-A: são do desktop.
5. Declare na primeira resposta: setup=notebook, branch, fase, o que não vai
   tocar — e **o que isto muda para quem instala amanhã numa base que não
   conhecemos**. Se a resposta a essa última só existe em termos do nosso acervo,
   diga isso em voz alta: é pacote de laboratório, e ele fica atrás de qualquer
   item de produto.

## Onde está o estado — e por que não está aqui

**Esta skill diz quem você é, não o que já foi feito.** A lista de "o que o
desktop já fez" saiu daqui em 25/08/2026 porque envelheceu duas vezes em três
dias e passou a contradizer a fonte. Em 29/08/2026 saiu também a lista de "pacote
da vez", pelo mesmo motivo e pela mesma regra: **número escrito à mão envelhece
calado enquanto quem o lê segue decidindo por ele.**

| Pergunta | Fonte única |
|---|---|
| Onde o sistema está, em cinco linhas | `CLAUDE.md`, §Estado atual |
| Qual é o próximo pacote | `CLAUDE.md`, §Próximo passo |
| Números vivos e o que o outro lado fez | [`docs/colaboracao.md`](../../../docs/colaboracao.md) §6 |
| Contrato de pacote e fila | [`ROADMAP.md`](../../../ROADMAP.md), seção Pacotes |

O que **não** muda, e por isso fica aqui: F1–F3.6 estão fechadas, a F4 está em
curso, e a **F6 é porta de fase** — nenhuma fase F4+ fecha sem o teste em máquina
que não é nossa. Os pacotes da F6 são do desktop e do painel; a porta é de todos.

## As skills deste repositório

Carregue a que couber, e não recite de memória o que elas dizem:

| Skill | Quando |
|---|---|
| `/pacote` | antes de abrir a branch — as três perguntas, efeito mínimo, encerramento |
| `/medir` | antes de rodar eval, e ao ler qualquer tabela de métrica |
| `/revisar` | antes do PR, e ao revisar diff do outro lado |
| `/entregar` | commit, branch e o PR como link de compare (não há `gh` aqui) |
| `/navegar` | onde as coisas moram, e o que **não** ler |

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
