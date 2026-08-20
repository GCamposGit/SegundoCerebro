# Colaboração — desktop (Grok) e notebook (Claude Code)

Dois setups, um repositório. Este arquivo é a **única** fonte das regras.
As skills só dizem *quem você é* e apontam para cá.

| Setup | Hardware | Acervo | Agente |
|-------|----------|--------|--------|
| **Desktop** | duas GTX 980 Ti (`sm_52`, driver 582.x) | corpus **novo**, sem o acervo corporativo | Grok Build |
| **Notebook** | i7-1355U, 15 W, CPU | acervo **corporativo** original e o conjunto dourado real | Claude Code |

O índice corporativo, `perguntas.jsonl` e os relatórios de ablação **não
viajam**. O que as duas máquinas compartilham é o código e o corpus sintético
em `eval/sintetico/`.

---

## 1. Quem mexe no quê

| Dono | Arquivos | Por quê |
|------|----------|---------|
| Desktop | `index/embeddings.py`, laço/pipeline de `index/indexer.py`, `index/esforco.py`, `index/smoke_cuda.py`, `requirements-gpu.txt` se existir, `docs/` de F3.6 e de estimativa | Velocidade, não ranking |
| Notebook | `retrieve/*`, `eval/*` **exceto** o exemplo sintético, docs gitignorados do acervo real, padrões de peso em `config.py` | Invariante 4 mora aqui |
| Um de cada vez | `mcp/server.py`, `painel/*`, schema de `config.py`, `ROADMAP.md` | Branch dedicada, merge, o outro puxa |
| Só o notebook | `CLAUDE.md` | É o retomador do Claude Code. O desktop no máximo acrescenta um ponteiro |

Mudança que toca ranking **e** o laço do indexador = **dois PRs**, não um.

`[padrao]` é compartilhado. `[[base]]` da base nova é do desktop. Algoritmo
(`hybrid.py`, `familias.py`, `rerank.py`, tamanho de chunk) afeta as duas bases
e só muda com número do notebook no conjunto corporativo.

---

## 2. O que nunca entra no Git

Já está no `.gitignore`. Não “ajudar” commitando:

- `config.toml`, `census.toml` — caminhos reais
- `/index/`, `/index-*/`, `models/`
- `eval/golden/perguntas.jsonl` e os markdowns de ablação/métrica listados no `.gitignore`

Caches e pesos de modelo também não vão para o Git. No desktop eles moram
fora do SSD do sistema, sem alterar o código:

- `PIP_CACHE_DIR` e `HF_HOME` (variáveis de usuário) → outro volume
- `models/` no repo é um *junction* para essa pasta; o `.gitignore` continua válido
- `.venv` **fica no SSD**, ao lado do código — Python e ONNX não vão para o HDD
- `indice` e `raizes` no `config.toml` local podem ser caminhos absolutos

O layout deste desktop é `E:\SegundoCerebro\` (`cache\`, `models\`, `index\`).
Não commitar essa letra de disco.

Cada máquina tem o **seu** `config.toml`, copiado de `config.example.toml` ou
de `config.sintetico.toml`. Diferença de hardware vai por ambiente, que o
carregador já aplica:

```
SEGUNDOCEREBRO_PERFIL
SEGUNDOCEREBRO_PROVIDER    # desktop: cuda   notebook: (vazio)
SEGUNDOCEREBRO_THREADS
SEGUNDOCEREBRO_LOTE
```

Não mandar `config.toml` por chat, e-mail ou gist.

---

## 3. Branches

Ninguém commita em `main`. Nem o agente.

```
main                         sempre verde; é o que o CI rodou
 ├─ f36-smoke-cuda           desktop, primeiro
 ├─ f36-pipeline             desktop, só depois do smoke passar
 ├─ onboarding-golden        desktop: sintético + exemplo (esta entrega)
 └─ f3-uso-real              notebook; o traço em si fica gitignorado
```

 Ritmo, dos dois lados:

1. `git pull origin main`
2. trabalhar **só** na sua branch
3. push e abrir/atualizar o PR
4. esperar o CI (Windows, CPU, **sem** GPU e **sem** `perguntas.jsonl`)
5. merge
6. o outro lado puxa `main` antes de começar qualquer coisa

Nunca force-push em `main`. Nunca deixe o agente “limpar o histórico” de uma
branch compartilhada.

Teste que precisa de GPU ou do encoder real usa o marker `modelo` (já existe)
ou um marker `cuda` — fora da suíte padrão.

---

## 4. As sete regras que evitam retrabalho

1. **Padrão de ranking não muda** sem o notebook medir antes/depois no
   conjunto corporativo.
2. **Chunk size, modelo de embedding e `model_id` não mudam** sem os dois
   lados concordarem — rebuildam o índice corporativo.
3. **`[padrao]` é compartilhado; `[[base]]` não.** Ajuste da base nova fica
   dentro dela.
4. **Hardware nunca entra em `model_id`.** Hoje é
   `e5-large:1024:fastembed0.8.0`. `cuda` no id faz o notebook reembeddar tudo.
5. **Um dono de fase por vez.** Com `f36-pipeline` aberto, o notebook não
   reescreve `indexer.py`.
6. **Grok não edita `CLAUDE.md`** além de um ponteiro. Claude Code não inventa
   código CUDA a partir da documentação.
7. **Número sem corpus é mentira.** “recall@1 = 0,678” sem “condição C,
   corporativo, 16/08” não é referência. Número do sintético diz
   `corpus=sintetico` e **não substitui** a condição C.

---

## 5. Corpus sintético — o que as duas máquinas compartilham

`eval/sintetico/corpus/` + `eval/golden/perguntas.example.jsonl` +
`config.sintetico.toml`.

Empresa fictícia **Várzea Clara Energia (VCE)**. Nenhum nome, contrato ou
trecho do acervo corporativo.

Serve para três coisas, e só essas:

1. CI e clone fresco têm uma régua (invariante 4 não fica sem arquivo)
2. Prova de portabilidade da F3.6: índice feito no desktop, consulta no
   notebook, **sem reembeddar**
3. Demonstrar o formato do conjunto dourado — não mede recuperação de um
   acervo real

```bash
py -m segundocerebro.index.indexer --config config.sintetico.toml --base sintetico
py -m eval.rodar --config config.sintetico.toml --base sintetico --retriever baseline
```

Copiar o índice sintético entre máquinas é o experimento conjunto da F3.6.
Copiar o índice **corporativo** para o desktop é proibido: o desktop não pode
tê-lo. Protocolo, pacote e o `eval.sintetico.verificar` estão em
[`docs/portabilidade-f36.md`](portabilidade-f36.md).

---

## 6. O que cada lado faz nesta fase

**Estado em 20/08/2026, branch `onboarding-golden`.** O desktop já entregou o
bloco abaixo. O notebook puxa esta branch, lê este arquivo e a skill em
`.claude/skills/segundo-cerebro-notebook/SKILL.md`, e **não** reabre o laço
do indexador.

**Desktop — feito nesta branch**

1. Smoke CUDA nas 980 Ti (`docs/smoke-cuda.md`). Pin `onnxruntime-gpu==1.18.0`
   + CUDA 11.8 + cuDNN 8. MiniLM quantizado = NaN; e5-large finito.
   `model_id` sem `cuda`.
2. Pipeline: parse em threads + `EmbedFila` (um processo por GPU).
3. Corpus sintético versionado + `perguntas.example.jsonl`.
4. Estimativa com semente GPU (`FATOR_GPU = 28`, medido).
5. Painel: checkbox de retomada no logon; Pausar / Continuar / Cancelar
   (arquivo `comando.txt` ao lado do índice, sem IPC).
6. Pacote de portabilidade: `docs/portabilidade-f36.md`. O zip do índice
   **não** vai no Git (é `index-*/`); viaja por `E:\SegundoCerebro\portabilidade-f36.zip`.

**Notebook — agora**

1. `git fetch && git checkout onboarding-golden && git pull`.
2. **Não** editar `index/indexer.py`, `index/embeddings.py`, `gpu_pool.py`,
   `smoke_cuda.py` enquanto esta branch não estiver em `main`.
3. Usar o sistema no acervo corporativo. Traço multi-hop em
   `docs/traco-f3-uso-real.md` (gitignorado) — fecha a F3.
4. Opcional, prova F3.6: copiar o índice sintético GPU e medir **sem**
   reembeddar — `docs/portabilidade-f36.md`.
5. Revisar o PR: tabela da seção 1 e regras 2 e 4. Primeira pergunta:
   viola a tabela de donos?

**Nenhum dos dois, daqui**

F4 (`neighbors`, grafo, MSG/OCR), F5, glossário de siglas corporativas,
segundo ataque isolado à `g036`, ligar rerank por padrão no notebook.

---

## 7. Como o outro agente deve ser avisado

No começo de cada sessão, o agente declara em uma linha: *setup, branch,
fase, o que não vai tocar*.

Ao abrir um PR, o resumo começa com:

```
Setup: desktop | notebook
Fase: F3.6 | F3 | onboarding | …
Toca: (lista de paths)
Não toca: retrieve/, CLAUDE.md, … 
Corpus da medição: sintetico | corporativo | nenhum
```

O outro lado, ao ver o PR, pergunta só isto primeiro: **viola a tabela da
seção 1?** Se sim, pede mudança. Se não, o CI decide.

---

## 8. Tentação → custo

| Tentação | Custo |
|----------|--------|
| `cuda` em `model_id` | notebook reembedda o índice corporativo |
| Mudar `max_chars` porque a GPU é rápida | todos os ids de chunk mudam; evals velhos deixam de ser comparáveis |
| Ajustar `[padrao]` no corpus novo | recall corporativo se move e só o notebook vê |
| Os dois editarem `ROADMAP.md` no mesmo dia | decisão perdida no merge |
| Commitar perguntas ou caminhos do acervo novo privado | o mesmo vazamento que tirou o dourado corporativo do Git |
| Começar o pipeline GPU antes do smoke | dias de código sobre runtime que o Maxwell não carrega |
