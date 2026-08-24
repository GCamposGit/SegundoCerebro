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
2. ~~**R9.3**~~ — **portas definidas em 24/08/2026.** Instrumento em
   `eval/latencia.py`, portas em `eval/portas-latencia.toml`, raciocínio em
   [`porta-de-latencia.md`](porta-de-latencia.md). São **duas**: alvo de produto
   (hoje reprovado, é o que `R4.1`/`R3.3` perseguem) e piso de regressão **por
   máquina nomeada**. Medido: `search` p95 **1.840 – 2.877 ms** conforme o estado
   térmico — a faixa reconcilia a linha de base de 1.145 ms que o ROADMAP
   registrava, que estava sem protocolo.

   **Falta o índice inflado de 1M trechos, que é do desktop.** Quando ele
   existir, `py -m eval.latencia --base <id> --maquina <nome> --porta` mede lá e
   grava um `[regressao.<maquina>]` próprio — o arquivo já aceita quantas
   máquinas existirem, e um piso medido num setup **não** vale no outro.

Depois da onda 1: `C6` (família de versões ≠ grupo de formatos), `F4-P`+`C3.a`,
`R6.1`. **Não começar `retrieve/*` antes** — a régua tem de existir primeiro.

**O que o notebook pega agora:** `F4-P`, depois `C6` e `R6.1` — a onda 2, agora
que a régua da onda 1 existe.

`C3.a` **fechado em 24/08/2026, com a hipótese refutada** —
[`ablacao-c3a-pesos-fts.md`](ablacao-c3a-pesos-fts.md). A dupla contagem do nome
do arquivo existe no mecanismo e não é ela que produz o efeito: o grupo de reunião
é **14× mais sensível** ao peso do ranqueador de nome que à coluna `caminho` do
bm25, e zerar a coluna custa de 0,023 a 0,062 de MRR agregado. `fts_caminho` fica
em 1,0.

**Nada foi aplicado, e a régua da onda 1 é o motivo.** A primeira leitura desta
varredura recomendou `nome = 0,25` — sobe agregado, nDCG@5 e reunião. Com a fatia
cross-lingual na tabela, ele **derruba a ponte PT↔EN** (MRR 0,496 → 0,475), e a
recomendação está retirada. O ranqueador de nome é sinal **agnóstico a idioma**:
identificador, código e data casam igual em PT e EN, e o bm25 não casa `contrato`
com `agreement`. Sem o recorte que `C4.5` construiu na onda 1, esta troca teria
entrado em `main` como melhoria.

Quatro coisas que a onda 2 herda:

- **A linha de base de `F4-P` é a de hoje** (`nome` 0,5 · MRR 0,680 · recall@1
  0,551 · reunião 0,287). O 0,5 saiu de um dourado sem perguntas de reunião e
  precisava ser rederivado — e a rederivação o **reconfirmou**, por dois motivos
  em vez de um.
- **Teto de oráculo de +0,032** de MRR agregado para o peso por tipo de fonte, com
  a folga toda na reunião: a referência já é o ótimo do escritório.
- **3 das 11 perguntas de reunião são cross-lingual** — o teto não desconta isso, e
  `F4-P` tem de medir a interseção.
- **`fts_caminho = 0,3` é candidato registrado para a lacuna cross-lingual:** razão
  do `C4.5` de 0,73 para 0,79 com as duas fatias subindo, custo zero por consulta,
  contra as rotas caras que estavam previstas (`R3.1`, `R6.2`/`C4.2`). Uma pergunta
  de doze — confirmar no perfil bilíngue do `R9.1`, que é do desktop.

**Um recado para o desktop, sobre `R9.1`:** o perfil bilíngue passou a ter um
segundo consumidor. Além do contrato de emitir `idioma` e `idioma_fonte`, é ele que
vai dizer se o `fts_caminho = 0,3` se sustenta — aqui a fatia tem 12 perguntas e o
efeito é de uma.

### `F4-P.0` — o eval passou a medir o caminho entregue (24/08/2026)

Achado ao começar o `F4-P`, com três consultas no índice real, antes de escrever
uma linha dele: **a ferramenta `search` do MCP chama `buscar_chunks`, onde o
`RanqueadorDeNome` não participa.** Mudar `peso_nome` de 0,5 para 0 não altera
nada ali, e altera a ordem em `search` em todas. O peso do nome é **inerte em
produção**, e `painel/medir.py:79` herda a cegueira.

`eval/entregue.py` + `--entregue` no `eval.rodar` medem o caminho entregue, de
forma **aditiva** — `search` continua sendo a série F0 → F4, porque trocar o
recuperador canônico apagaria a comparabilidade entre fases. Leitura em
[`ablacao-caminho-entregue.md`](ablacao-caminho-entregue.md).

**O que o desktop precisa saber:**

- **Nada mudou no produto.** Nenhuma linha de `mcp/server.py` ou do caminho de
  consulta. Só existe medição nova.
- **O achado de manchete de `C4.5` foi corrigido**, e isso muda o alvo de `C4.2`
  (rerank cross-lingual, onda 7): *"recall@20 é 1.000, o documento é alcançado e
  mal ordenado"* vale só em `search`. No caminho entregue é **0,750** — três das
  doze perguntas cross-lingual não são alcançadas no top-20. Quem for atacar
  cross-lingual precisa saber que, no produto, parte do problema é alcance e não
  ordenação.
- **Vale conferir o mesmo para todo sinal**, dos dois lados, e a verificação é
  barata: varie o peso e veja se a saída muda. O princípio já estava escrito em
  `ablacao-familias.md` desde 16/08 e não tinha sido aplicado fora dele.
- `F4-P` foi **reescopado** e o teto de +0,032 caiu — era calculado sobre `search`.

Um pedaço de `C3.b–d` (expansão morfológica, frases, stoplist) **continua do
desktop** na onda 6 e não foi tocado aqui — só `C3.a`.

**Reportado e não corrigido, pela regra 8 da §4.** Depois do merge do PR #14,
três testes de `tests/test_pacote.py` falhavam neste notebook. O notebook rodou
`pip install -e .` como pedido — e **dois continuam vermelhos**, o que muda o
diagnóstico. O `pip install` conserta `test_import_sem_pythonpath_de_system32`; os
outros dois falham por um segundo defeito, independente:

`_script()` usa `Path(sys.executable).parent` para achar o console script. Num
venv isso acerta, porque o `python.exe` mora dentro de `Scripts/`. Numa instalação
base do Windows, não: o `pip` põe os `.exe` em `sysconfig.get_path("scripts")`,
que é `…\Python312\Scripts`, um nível abaixo do interpretador. Medido aqui: os
quatro `.exe` existem, `segundocerebro-mcp.exe --help` roda de
`C:\Windows\System32` sem `PYTHONPATH` e devolve 0, e o teste continua vermelho.
**O CI passa porque roda em venv** — o acerto é coincidência de layout.

Registrei como `R8.1.b` no `ROADMAP.md`, com a ordem: consertar a busca pelo
script **antes** do `skipif`, senão o `skipif` mascara o defeito num setup onde o
pacote está instalado e funcionando.

**Ordem dentro da onda 2, e o motivo de não ser a da lista.** `C3.a` vem primeiro
porque é a hipótese mais barata da onda e ela pode tornar as outras duas menores:
se a dupla contagem do nome do arquivo explica a troca medida nas perguntas de
reunião, a correção é um número de consulta, não uma classificação de documento
no caminho de ranking. `R6.1` vem por último porque a grade do autotune tem de
saber quais botões existem — `C3.a` e `F4-P` decidem isso.

**Dois arquivos "um de cada vez" que o notebook pegou para o `C3.a`**, e devolve
no merge:

- `index/store.py`, só `buscar_lexical` — ganhou os pesos de coluna do `bm25()`.
  O complemento já avisava que `store.py` é compartilhado e pedia combinar antes.
  Nada do laço de indexação, nada de embedding.
- schema de `config.py` — três campos novos em `[base.pesos]` (`fts_texto`,
  `fts_trilha`, `fts_caminho`), todos em 1,0, que é o padrão do FTS5. **Não é
  classe cara:** peso de coluna é de consulta e não reindexa nada.

**A dependência que a fila declara e que o notebook não vai fingir que não existe.**
A fila marca `F4-P` e `R6.1` como "depois de `R9.1`", e `R9.1` (perfis sintéticos)
é do desktop e ainda não começou — não há branch. `C3.a` **não** depende dela: é
medição no dourado corporativo. `F4-P` também mede aqui e o corporativo é o piso.
Quem depende de verdade é o critério de aceite de `R6.1`, que pede dois acervos de
características opostas (nome informativo contra `IMG_2034.pdf`) para provar que o
autotune converge para pesos diferentes. Isso o notebook **não tem** e não pode
inventar. Então `R6.1` entrega o mecanismo medido no corporativo e declara o
critério de generalização como pendente de `R9.1`, em vez de dar o pacote por
fechado com meia prova.

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
