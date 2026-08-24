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
| Desktop | `index/embeddings.py`, laço/pipeline de `index/indexer.py`, `index/esforco.py`, `index/smoke_cuda.py`, `index/prioridade.py`, `index/estimativa.py`, `ingest/parsers/ole_texto.py`, `requirements-gpu.txt` se existir, `docs/` de F3.6, de estimativa e de prioridade | Velocidade e política de fila, não ranking |
| Notebook | `retrieve/*`, `eval/*` **exceto** o exemplo sintético, docs gitignorados do acervo real, padrões de peso em `config.py` | Invariante 4 mora aqui |
| Um de cada vez | `mcp/server.py`, `painel/*`, schema de `config.py`, `ROADMAP.md` | Branch dedicada, merge, o outro puxa |
| Um de cada vez, **por formato** | `ingest/parsers/*` | Os dois lados precisam de formato novo. O dono é por arquivo de parser, declarado na §6 antes de começar |
| Só o notebook | `CLAUDE.md` | É o retomador do Claude Code. O desktop no máximo acrescenta um ponteiro |

Mudança que toca ranking **e** o laço do indexador = **dois PRs**, não um.

`ingest/parsers/*` entrou na tabela em 23/08/2026 porque a regra antiga
(“parser é do notebook, laço é do desktop”) não sobreviveu ao encontro dos PRs
#5 e #6: o notebook escreveu `mail.py`, o desktop escreveu `ole_texto.py`, e os
dois mexeram no despachante. Não houve conflito, e foi sorte. O dono é do
**arquivo de parser**, não da pasta; o despachante (`parsers/__init__.py`,
`supported_extensions()`) é “um de cada vez” como `mcp/server.py`.

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

Em 23/08/2026, tudo que a árvore antiga listava está em `main` (PRs #2 a #6).
A árvore vira histórico e o que vale é a regra: **uma branch por entrega, com
prefixo da fase e do lado que a conduz.**

```
main                    sempre verde; é o que o CI rodou   (677fa22)
 │
 │  fechadas e mergeadas
 ├─ onboarding-golden   desktop  PR #2   sintético + exemplo
 ├─ f4-grafo-neighbors  notebook PR #3   grafo derivado + neighbors
 ├─ f36-rerank-gpu      desktop  PR #4   rerank na GPU, limites por tipo
 ├─ f4-msg-eml          notebook PR #5   .msg/.eml + versão de parser
 └─ f36-fila-ondas      desktop  PR #6   fila em ondas + OLE legado
```

Branch mergeada é apagada — local e remota. As cinco acima ainda existem
localmente nos dois setups e só confundem: `git branch -vv` mostra
`[origin/…: gone]`, que é o sinal de que já foram.

 Ritmo, dos dois lados:

1. `git pull origin main`
2. trabalhar **só** na sua branch
3. push e abrir/atualizar o PR
4. esperar o CI (Windows, CPU, **sem** GPU e **sem** `perguntas.jsonl`)
5. merge
6. o outro lado puxa `main` antes de começar qualquer coisa

Nunca force-push em `main`. Nunca deixe o agente “limpar o histórico” de uma
branch compartilhada.

**Stash não é versão.** Entrega que ficou só no stash desta máquina não existe
para o outro lado — foi o que atrasou a fila em ondas até o PR #6. Cada fase
termina em commit na branch e PR; o notebook (e o desktop) só vê o que está em
`main`.

Teste que precisa de GPU ou do encoder real usa o marker `modelo` (já existe)
ou um marker `cuda` — fora da suíte padrão.

---

## 4. As nove regras que evitam retrabalho

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
8. **Achado no acervo do outro se reporta, não se corrige.** Um coeficiente de
   estimativa medido no corporativo vira nota no doc do notebook e ponteiro para
   `docs/estimativa-de-indexacao.md`; quem edita o arquivo é o dono dele. Vale
   nos dois sentidos. Feito assim em `docs/ablacao-f4-meetings.md` — a regra só
   registra o que já funcionou.
9. **O Git é a única cópia.** Stash, working tree suja e `config.toml` local
   não contam como entrega. Se não está em `main`, o outro computador não tem.

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
tê-lo. Protocolo, `verificar`, `comparar` (cosseno > 0,9999) e o pacote estão
em [`docs/portabilidade-f36.md`](portabilidade-f36.md).

---

## 6. O que cada lado faz nesta fase

**Estado em 24/08/2026.** F1, F2, F3, F3.5 e F3.6 fechadas. F4 **em curso**, e é
a única fase aberta. `main` = `677fa22`, PRs #2 a #6 mergeados. Suíte padrão
neste desktop depois do #6: **732** verdes (`tests/` + `eval/`). Índice
corporativo do notebook: **1.828 documentos, 97.981 trechos**.

Histórico das entregas fechadas (smoke CUDA, pipeline, sintético, portabilidade,
rerank na GPU, perfil leve, limites por tipo, painel 18787, grafo, `neighbors`,
`.msg`/`.eml`, versão de parser, fila em ondas, OLE legado) está nos PRs #2 a #6
e nos `docs/` que cada um cita. Não repetir a lista aqui: ela envelheceu duas
vezes em três dias. Esta seção passa a dizer só **o que está aberto**.

### Aberto — notebook

**1. `Meetings/`, a passada que está pausada agora.** É o número que o
fechamento do email deixou pendurado, e o levantamento está em
[`docs/ablacao-f4-meetings.md`](ablacao-f4-meetings.md): 1.009 arquivos, **169
reuniões**, 6,0 arquivos por reunião. A passada parou em **234 de 833**
documentos (`index/comando.txt` = `pausar`), e o que ela estava indexando no
momento da pausa é um `_context.txt` — **andaime**, o prompt que o aplicativo
monta, não a reunião.

Por isso o próximo passo não é “continuar”: é **cortar a fila por papel** e só
então continuar. O levantamento já mediu três redundâncias, todas antes de
gastar a passada — 280 arquivos de andaime, 177 PDFs que são 188/188 redundantes
com um `.txt` do próprio conjunto (381 dos 397 MB, 5 h a 11 h), e 263 duplicatas
exatas entre `Meetings/` e `09. Meetings/`. Sobram as transcrições, e delas há
**três renderizações do mesmo áudio** por reunião.

Isto encosta na fila em ondas do desktop (#6) e é o primeiro caso real em que
uma **regra de exclusão por papel dentro da pasta** não cabe em teto de MB nem
em extensão. Proposta do notebook, a validar: a exclusão mora na configuração da
base (`[base.excluir]` por padrão de nome), não em código do indexador — assim o
notebook não reescreve `indexer.py`, que é do desktop.

**2. Repescagem do legado com o parser do desktop.** O `ole_texto.py` do #6 e a
versão de parser no registro do #5 se encontram: `_precisa_indexar` já repesca
por `estado.parser != parser`, então os 10 `.doc`/`.xls` que a F4 tinha deixado
fora entram sozinhos na próxima passada. Falta **medir** no dourado corporativo.
Convergência não planejada dos dois lados — vale registrar que funcionou.

**3. O que resta da F4 depois disso:** SharePoint via pasta sincronizada,
watcher, e a porta 3 (“onde o bm25 se paga”). Multi-hop completo segue em 1 de 5.

### Aberto — desktop

**1. Estimativa em pasta de arquivo pequeno.** Achado do notebook em
`Meetings/` (regra 8, `docs/ablacao-f4-meetings.md`): a semente de `.txt` está
dez vezes baixa (496 s/MB, perto do DOCX), e com arquivos de ~19 kB o custo é
overhead por documento, não por byte. A barra chegou a pedir dezenas de dias
numa passada de horas. O arquivo a corrigir é
[`docs/estimativa-de-indexacao.md`](estimativa-de-indexacao.md) e
`index/estimativa.py` — dono: desktop. Não é `[padrao]`.

**2. Suíte que trava — não fica lenta — com a passada viva.** Os testes de
`eval/` esperam a trava de escrita do SQLite sem timeout. Pausar com
`comando.txt` fecha a suíte; o CI nunca vê, porque lá não há índice real. Falta
mensagem ou recusa explícita, para o próximo não gastar quarenta minutos.

**3. Não começar** `[padrao]`, `Chunking`, `model_id`, `retrieve/*`, nem
reabrir o laço do `indexer.py` enquanto o notebook corta `Meetings/` por papel.

### Aberto — os dois, e precisa de acordo

**`[base.excluir]` por padrão de nome.** Proposta do notebook para andaime e
PDF redundante em `Meetings/`: a exclusão mora na configuração da base, não no
laço. O desktop **concorda com o lugar** (config, não `indexer.py`). O schema
de `config.py` é “um de cada vez”: quem for escrever o PR declara antes.

**Nome real em documento público.** `docs/colaboracao.md` citava o nome de um
cliente real ao explicar o `parser=` do #6 (corrigido neste PR para “a base
privada do desktop”). O repositório é público e a regra de saneamento do
`CLAUDE.md` vale para os dois lados, não só para o acervo corporativo: nome de
cliente, de fornecedor ou de projeto real não entra em doc, docstring nem
mensagem de commit. O vocabulário de exemplo é a VCE.

### Não é de ninguém, daqui

F5 (segundo usuário real), segundo ataque isolado à `g036`, ligar rerank por
padrão no notebook.

**Prioridade registrada para o produto, não só para esta máquina:** Office
legado (`.doc` `.xls` `.ppt`) é caminho crítico em acervo de consultoria. Não
tratar como “F4 se o eval pedir”. Sem esses três a base indexa o OOXML e ignora
o arquivo que o usuário ainda abre no dia a dia.

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
| Deixar a entrega só no stash | o outro computador não tem; as ondas ficaram cegas até o #6 |
