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

**Estado em 24/08/2026.** F1–F3.6 fechadas. F4 **em curso**, F6 (primeiro uso
leigo) **pode correr em paralelo**. `main` = `57d6f74` (PRs #2 a #9). O que
está aberto não se lista aqui: virou **pacote** no `ROADMAP.md` (seção
“Pacotes”). Esta seção só diz o que cada lado **pega agora**, para as listas
de path não se cruzarem.

### Agora — notebook

**F4-M fechado** (PR #10) e **F4-D reescopado** (PR #15): o dourado real cobre
25% do índice, e a resposta adotada **não** é escrever mais perguntas para este
acervo — é parar de escolher peso global a partir de qualquer acervo único. Ver
[`docs/dourado-cobertura.md`](dourado-cobertura.md) e o `ROADMAP.md`.

Onda 1 do notebook:

1. ~~**C4.5**~~ — **fechado em 24/08/2026**. O harness recorta `mesma-língua` vs
   `cross-lingual` em todo relatório, e `eval.ablacao_f2` ganhou as duas colunas
   de MRR. Medido: **recall@1 0.625 mesma-língua contra 0.333 cross-lingual**,
   razão em recall@5 **0.73** contra o 0.80 do critério. Ver
   [`fatia-cross-lingual.md`](fatia-cross-lingual.md).
2. **R9.3** — porta de latência. Linha de base já medida em 24/08: `search` sem
   rerank **p50 1.145 ms / p95 1.418 ms**; com rerank de 10 candidatos, p50
   8.019 ms. O notebook define a porta; o índice inflado vem do desktop.
   **É o que o notebook pega agora.**

Depois da onda 1: `C6` (família de versões ≠ grupo de formatos), `F4-P`+`C3.a`,
`R6.1`. **Não começar `retrieve/*` antes** — a régua tem de existir primeiro.

### Agora — desktop

**Cinco pacotes prontos para começar, nenhum bloqueado por nada.** A ordem é
sugestão; os três primeiros são a onda 1 e destravam as ondas 4 e 5.

1. **R9.1 + C5.b — perfis sintéticos.** Quatro perfis (`juridico`, `financeiro`,
   `pessoal` com nomes ruins tipo `Scan_001.pdf`, `engenharia`) + um bilíngue
   PT/EN. **O perfil bilíngue tem contrato desde 24/08:** o dourado gerado emite
   `idioma` e `idioma_fonte` (formato em `eval/golden/README.md`). Sem os dois
   campos a fatia cross-lingual sai de tamanho zero e o relatório parece
   aprovado — o harness não os detecta sozinho, e o porquê está em
   [`fatia-cross-lingual.md`](fatia-cross-lingual.md).
   **Versionar gerador + seed + manifesto** com hash do *texto extraído*;
   corpus gerado vai para o `.gitignore`. É o padrão que `eval/sintetico/` já
   segue — não commitar corpus. Determinismo obrigatório: seed única, iteração
   ordenada, sem depender de locale.
2. **C5.a — porta de custo do MIRACL.** Smoke de throughput **antes** de baixar
   qualquer coisa, publicado em `docs/custo-miracl.md`. Regra já acordada: custo
   por modelo acima de ~12 h (uma noite) ⇒ MIRACL sai da ablação, com a decisão
   registrada. Se entrar: amostrado, desktop-only, índice em diretório
   descartável — **nunca** uma `[[base]]` (invariante 7).
3. **F6-A / R8.1 — empacotamento.** `[project.dependencies]` com pins
   (`fastembed>=0.8,<0.9` — a lição do pooling CLS→mean já foi paga),
   `requirements.txt` vira lockfile de CI, extras `[gpu]`/`[ocr]`, matriz
   `windows`+`ubuntu`+`macos` no CI. Alvo: `pip install` + um comando sobe o
   servidor em venv limpa, sem `PYTHONPATH`.
4. **C7.a + C7.d — perda silenciosa em planilha.** `data_only=True` faz planilha
   nunca aberta pelo Excel vir com célula vazia: o Equity Value simplesmente não
   entra no índice. O aviso já existe em `sheets.py:420`; falta a rota de
   recálculo via LibreOffice headless — **mesmo binário do R1.1**. E `.csv` está
   registrado no parser de texto (`text.py:109`): depois da primeira janela as
   linhas ficam órfãs sem cabeçalho. Rota própria no pipeline de planilha.
   *Dimensionamento honesto:* no acervo corporativo são **2 CSVs**; os 85 do
   complemento vêm da varredura de disco inteiro, não de uma base.
5. **F4-L, F4-W, R1.4, R5.2, R3.2** — como já estavam, mais quarentena de
   arquivo venenoso, orçamento adaptativo de recursos e indexação em dois passes.

**Não começar** `[padrao]`, `Chunking`, `model_id`, `retrieve/*` — e **não
implementar `R1.3`**: o complemento mostrou que MinHash a 0,85 fundiria o que
`familias.py` separa de propósito e reintroduziria o `g045`. `R1.3` está
absorvido por `C6`, que é do notebook.

`config.py` e `painel/*` estão **livres** desde o merge do F4-M — mas continuam
"um de cada vez": declare aqui antes de pegar.

### Os dois documentos de recomendação

[`dossie-melhorias.md`](dossie-melhorias.md) (R1–R10) e
[`dossie-complemento-update-devs.md`](dossie-complemento-update-devs.md) (C1–C7)
são a especificação de cada pacote. **Ler o `ROADMAP.md` junto**: as premissas dos
dois foram conferidas contra o índice real, e sete não bateram — inclusive duas
que invertiam qual subconjunto do dourado é o mais fraco. As seções são "O dossiê
de melhorias, conferido contra o índice real" e "O complemento C1–C7, conferido no
código".

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
| Esperar a barra para escrever código | ociosidade; o parser com versão alcança o disco na passada seguinte |
