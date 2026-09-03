# Colaboração — desktop (Grok) e notebook (Claude Code)

Dois setups, um repositório. Este arquivo é a **única** fonte das regras.
As skills só dizem *quem você é* e apontam para cá.

> **Estado vigente desde 02/09/2026.** O notebook original (i7-1355U) foi
> desativado em 01/09. Este notebook (i7-14700HX, 8P+12E) retomou em 02/09, com
> o acervo corporativo e o dourado real. O Desktop continua ativo. A tabela de
> donos da §1 volta a distribuir trabalho. CUDA e `index/embeddings.py` seguem
> do Desktop. Nenhum dado privado migra para o Desktop ou para o Git.

| Setup | Hardware | Acervo | Agente |
|-------|----------|--------|--------|
| **Desktop** | duas GTX 980 Ti (`sm_52`, driver 582.x) | corpus **novo**, sem o acervo corporativo | Grok Build |
| **Notebook** | i7-14700HX (8P+12E), Windows 11 | acervo **corporativo** original e o conjunto dourado real | Claude Code |

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

## 4. As doze regras que evitam retrabalho

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
10. **Ganho de um acervo não vira `[padrao]`.** Medido num acervo só, o ganho é
   daquele acervo: entra como `[[base]]` opcional, como prior do autotune
   (`R6.1`), ou espera o segundo acervo. **Exceção declarada:** custo zero por
   consulta e estruturalmente independente de acervo — foi o caso de famílias de
   versão e do glossário, os dois maiores ganhos da F2. O reranking, que custa
   6,8×, não é desse tipo.
11. **Hipótese sem efeito mínimo declarado não gera varredura.** Fatia e valor
   antes de olhar a tabela; o veredito sai do Δ pareado de `eval.comparar`, e
   **empate encerra o pacote** — "meça mais" não é resposta. Porta já refutada só
   reabre com instrumento novo ou acervo novo, nunca com outra grade (a porta 3 já
   foi varrida três vezes).
12. **Defeito se generaliza, não se remenda.** Todo defeito achado em teste ou
   medição sai do pacote como **classe**, com o método que passa a pegá-la
   sozinho. O remendo entra junto, mas não é a entrega. O padrão é o
   `_CAMPOS_DE_MONTAGEM` do `E5`: o conserto que importou não foi completar a
   lista de campos, foi o teste que confere o contrato contra o código-fonte.
   Defeito que só some no nosso acervo volta na base do usuário.

As regras 10 a 12 são de 25/08/2026 e vêm de
[`regra-de-ouro.md`](regra-de-ouro.md), que tem precedência sobre prioridade
herdada de dossiê, guia ou fila de pacotes.

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

**Estado em 25/08/2026.** F1–F3.6 fechadas. F4 **em curso**, e a F6 (primeiro uso
leigo) deixou de ser trilha paralela: virou **porta de fase** — nenhuma fase F4+
fecha sem o teste em máquina que não é nossa. `main` = `57d6f74` (PRs #2 a #9). O que
está aberto não se lista aqui: virou **pacote** no `ROADMAP.md` (seção
“Pacotes”). Esta seção só diz o que cada lado **pega agora**, para as listas
de path não se cruzarem.

### A regra de ouro entrou, e a fila mudou de critério (25/08/2026)

**Decisão do usuário.** O trabalho estava derivando para dentro do acervo
conhecido — muito tempo em detalhe de etapa, teste enviesado ao que já foi
superado, e as portas menos relevantes de cada fase. A correção está em
[`regra-de-ouro.md`](regra-de-ouro.md) e é de processo, não de rigor: o `E5`, o
piso `dourado-v1` e "sem número não entra" continuam de pé.

Três consequências que o desktop precisa saber:

1. **As regras 10, 11 e 12 da §4 valem para os dois lados.** A 10 muda quem pode
   mexer em `[padrao]`: nem o notebook, com número do acervo corporativo, se o
   ganho não for de custo zero e independente de acervo.
2. **A ordem `E5` → `F4-P` → `E1` virou `E5` → `E1` → `F4-P`.** O `E1` é o
   instrumento de base desconhecida; a `F4-P` encolheu ao **defeito** (reconciliar
   os dois caminhos de recuperação, aceite binário) e a varredura de peso por tipo
   de fonte saiu do escopo — no melhor caso teórico ela vale +0,032 de MRR
   agregado com efeito concentrado em 11 perguntas, que o `E5` mostrou ser a forma
   indetectável.
3. **O bloco de PR da §7 ganhou três linhas.** Base desconhecida, efeito mínimo e
   classe generalizada. Vale para PR dos dois lados, e o
   `.github/PULL_REQUEST_TEMPLATE.md` já vem preenchido com elas.

**Paths deste PR (notebook):** `CLAUDE.md`, `docs/regra-de-ouro.md` (novo),
`docs/historico-decisoes.md` (novo), `docs/colaboracao.md`, `ROADMAP.md`,
`docs/guia-engenharia-5-estrelas.md`,
`.claude/skills/segundo-cerebro-notebook/SKILL.md`,
`.github/PULL_REQUEST_TEMPLATE.md`. **Zero código.** `ROADMAP.md` e este arquivo
são "um de cada vez" e estão devolvidos no merge.

### Agora — notebook

**F4-M fechado** (PR #10) e **F4-D reescopado** (PR #15): o dourado real cobria
18,2% do índice pelo teto por pasta (51 perguntas, 24/08/2026 — hoje são 62, e o
instrumento do `F4-D` mede 38,5% de teto contra 3,3% de piso), e a resposta
adotada **não** é escrever mais perguntas para este
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

   **Índice inflado do desktop (02/09/2026).** Método em `index/inflar.py`
   (perturba vetores já gravados, sem encoder). Piso `desktop-980ti` gravado:
   `search` p95 9 200 ms @ 1M trechos. O artefacto `/index-*/` continua
   gitignorado. Um piso medido num setup **não** vale no outro.

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

**Consertado em 25/08/2026**, na ordem que este parágrafo pediu: `_script()` passa
a usar `sysconfig.get_path("scripts")`, sem `skipif`. `tests/test_pacote.py` volta
a 4 verdes. O resto do `Q2` — lockfile e extras — continua do desktop; aqui foram
duas linhas de auxiliar de teste, sem tocar `pyproject.toml` nem produto.

**E um segundo achado, que este bloco não tinha e que é de produto.** O bloco
mediu que o `.exe` roda quando invocado pelo caminho inteiro. Ele **não** roda
quando invocado pelo nome: o `PATH` desta máquina tem `…\Python312` e não tem
`…\Python312\Scripts`, e `Get-Command segundocerebro-mcp` não acha nenhum dos
quatro. Ou seja, `pip install -e .` numa instalação de usuário entrega pontos de
entrada que o shell não alcança — **falha da régua de prontidão item 1** (instala
frio), não coincidência de layout de CI. Duas consequências:

1. **`mcp/registrar.py` tem de continuar emitindo `py -m segundocerebro.mcp.server`,
   e não o console script.** Trocar por `segundocerebro-mcp` parece modernização e
   quebraria o registro nesta classe de instalação.
2. **`docs/comecar.md` (`F6-D`) não pode mandar digitar `segundocerebro-painel`
   sem dizer o que fazer quando não resolve.** É o primeiro comando que o leigo
   digita, e hoje ele falha nesta máquina.

   **Atendido em 25/08/2026.** A página ensina a forma `py -m segundocerebro.painel`
   como a principal — não como contorno — e trata o atalho numa caixa própria, com
   o comando que imprime a pasta a acrescentar ao `PATH`. O que fechou a classe não
   foi a caixa: foi `tests/test_docs_do_usuario.py`, que confere cada
   `py -m <modulo>` das duas páginas de usuário contra um ponto de entrada que
   exista de fato. Doc que manda digitar comando inexistente agora reprova.

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

### `E5` fechado em 24/08/2026 — e a porta 5 não rodava

[`rigor-estatistico.md`](rigor-estatistico.md). Instrumento em
[`eval/estatistica.py`](../eval/estatistica.py): bootstrap **pareado** de
percentil, 1.000 reamostragens, semente fixa. Duas tabelas novas — ruído por
recorte em `eval.rodar`, Δ ± IC95 com veredito em `eval.comparar`.

**A regra de adoção passou a ser escrita:** a mudança ganha na fatia que ela mira
se o IC95 do Δ pareado **exclui zero**; empate resolve por simplicidade, que é
não adotar. Vale para os dois lados, e vale para as ablações R/C pendentes.

**O que o desktop precisa saber:**

- **Nada mudou no produto.** Nenhuma linha de `retrieve/*`, `mcp/server.py` ou do
  caminho de consulta. Só existe medição nova, e ela é aditiva: toda tabela
  anterior continua igual, com seções a mais.
- **A porta 5 estava inexecutável desde o bloco A da F3.5.** `eval.comparar`
  levantava `AttributeError` em qualquer recuperador que não fosse o baseline —
  o arremedo de `Args` que ela monta para reusar `rodar._montar` não tinha
  acompanhado quatro campos (`base_cfg`, `glossario`, `rerank`, `sem_rerank`).
  Nenhum teste pegou porque todos montam `Resultado` à mão e nunca passam por
  `_montar`. Mesma família do `F4-P.0`: o teste é bom e é cego ao caminho que o
  produto executa.

  O conserto tem duas partes, e a segunda é a que importa: `_CAMPOS_DE_MONTAGEM`
  declara o contrato, e um teste o confere lendo o código-fonte de
  `rodar._montar`. **A próxima fase que acrescentar um campo quebra o teste**, que
  é barato, em vez de quebrar a porta, que não é. Se o desktop acrescentar um
  argumento em `rodar._montar`, é lá que ele aparece.
- **`eval.comparar` ganhou `--base`, `--glossario`, `--rerank`, `--rerank-depois`
  e `--sem-rerank`.** O `--rerank-depois` é o que permite braço **assimétrico**,
  sem o qual não se mede "esta feature vale a pena?".
- **`--peso-denso`/`--peso-nome` ausentes deixaram de virar constante de módulo** e
  passaram a significar "o que a base configura", como em `eval.rodar`. Com os
  `fts_*` do `C3.a` no `[base.pesos]`, a porta 5 mediria pesos de fábrica contra
  uma base que configura outros.
- **Uma armadilha de leitura, para os dois lados:** `eval.rodar` imprime o
  intervalo de um braço **isolado**, largo de propósito. **Dois intervalos que se
  sobrepõem não provam empate.** Quem compara duas configurações lê o Δ pareado
  de `eval.comparar`, e só ele.

**Dois números que o desktop vai querer, e que valem para os dois acervos:**

- **A re-análise do reranking da F2 deu empate.** Δ MRR **+0,012 [−0,031; +0,055]**,
  Δ nDCG@5 **+0,022 [−0,010; +0,054]**, n=59. O ganho está reproduzido em tamanho e
  cruza zero. Não muda nada — o reranking já estava desligado por custo — mas quem
  for atacar `R6.2`/`C4.2` na GPU precisa saber que **o alvo não é "recuperar 3,4
  pontos"**, é sair do empate. E que **Δ recall@1 é +0,000 em todo recorte**: com
  peso 0,25 o cross-encoder reordena a cauda e não desloca o 1º lugar.
- **A única fatia que acende é a cross-lingual**, e em uma métrica de três, sem ter
  sido declarada antes. É **pista para `C4.2`**, com número de partida (+0,031 de
  MRR), não resultado. Com oito recortes na tabela, a chance de um acender por
  acaso sob hipótese nula é ~34% — daí a regra de declarar a fatia-alvo no pacote,
  antes de rodar.

**E um achado que muda como se lê qualquer fatia pequena, nos dois lados:** o que
n=11 detecta depende da **forma** do efeito, não só do tamanho. Δ de +0,273
concentrado em três perguntas dá **empate**; de +0,150 espalhado pelas onze,
**ganha**. Quem propuser mudança de peso numa fatia pequena olha *quantas*
perguntas se moveram, não só o Δ.

**Paths devolvidos:** `eval/estatistica.py` (novo), `eval/harness.py`,
`eval/comparar.py`, `eval/test_*.py`, `ROADMAP.md`.

### O pacote E entrou no plano, e o notebook assumiu o gerador (24/08/2026)

Chegaram dois documentos novos:
[`relatorio-avaliacao-resiliente.md`](relatorio-avaliacao-resiliente.md) (pacotes
E1–E6, que declaram substituir `R9.1`/`R9.2` e `C5`) e
[`guia-engenharia-5-estrelas.md`](guia-engenharia-5-estrelas.md) (Q1–Q10, eixo de
qualidade de engenharia, ortogonal ao ranking). Os dois estão absorvidos no
`ROADMAP.md`.

Junto veio o código do `E1`. O notebook **executou** antes de planejar, e o laudo
é [`avaliacao-pacote-e1.md`](avaliacao-pacote-e1.md): oito achados, todos de
execução. Os três que mudam o trabalho do desktop:

- **`--n-por-fatia 30` não termina.** O espaço de siglas tem 26 elementos, não
  26³ — 7, 11 e 17 são coprimos de 26, então `b mod 26` é bijeção. Em `i = 26` o
  laço não sai. A suíte do zip passa porque todo teste usa `n ≤ 11`. É a lição do
  `schtasks` da F3.5-D outra vez.
- **A fatia cross-lingual sai de tamanho zero.** `idioma_fonte` nunca é emitido, e
  `idioma: "pt->en"` não é código aceito — `carregar_perguntas` levanta
  `ValueError`. É palavra por palavra o que o contrato de `R9.1` avisou em
  `eval/golden/README.md` no mesmo dia.
- **Zero perguntas de reunião e de email**, medido: `{'escritório': 234,
  'misto': 26}`. Sem `.msg`, `.eml`, `.vtt` nem pasta de transcrição.

**Quem faz o quê a partir de agora:**

- **O gerador (`eval/gerador/`) passou a ser do notebook.** `R9.1` + `C5.b` estão
  absorvidos pelo `E1` e saíram da fila do desktop — **não pegar**. É o mesmo
  padrão do `C3.a` com `store.py`: o notebook pega, entrega no PR, e o dono volta
  a ser combinável depois. O motivo de ser aqui é que o `E1` só serve se medir
  reunião, email e cross-lingual, e os três recortes (`eval/fonte.py`,
  `eval/idioma.py`, o harness) são do notebook.
- **`C5.a` (porta de custo do MIRACL) continua do desktop**, sem mudança. Ele
  vira a camada 3 do protocolo `E3` — alarme, nunca decisão.
- **`E6.1` precisa do censo do desktop.** As distribuições de formato, tamanho e
  profundidade de pasta parametrizam o gerador. Hoje o corpus sintético é 80%
  `.txt` contra os 74% PDF+DOCX do acervo real, e mede um caminho de código que o
  produto quase não executa.

**Ordem que o notebook segue, e o motivo de não ser a do relatório.** O relatório
manda instrumento antes de conclusão, e lido ingenuamente isso seria `E1` antes de
`F4-P`. A execução desmente: o sintético não mede nenhum dos dois grupos que a
`F4-P` decide, então rodá-lo antes não protegeria a `F4-P` de nada. O que protege
é o intervalo de confiança sobre o dourado corporativo, que já é o piso declarado.

**`E5` → `F4-P` → `E1` endurecido.**

**Paths que o notebook declara agora:** `eval/metrics.py`, `eval/harness.py` e os
`eval/test_*.py` (pacote `E5`); depois `retrieve/hybrid.py` e `index/store.py` só
em `buscar_chunks` (pacote `F4-P`); depois `eval/gerador/*` (pacote `E1`). O
`ROADMAP.md` foi editado neste PR e está devolvido.

Um recado sobre os pacotes **Q**: são ortogonais e nenhum decide ranking, então
não entram na fila de ondas e podem correr a qualquer momento dos dois lados.
`Q2` é do desktop e já andou no PR #14 — sobra o lockfile, os extras e `R8.1.b`.

### `E1` fechado em 25/08/2026 — a camada 2 existe, e a `F6-E` fechou junto

As sete condições do laudo, em três PRs (`E1.a`, `E1.b`, `E1.c`). O que o desktop
precisa saber, em quatro linhas:

- **`eval/gerador/` é código versionado; o corpus não.** Regenerar com
  `py -m eval.gerador --seed 42 --n-por-fatia 30 --out <dir>`, e `--so-texto`
  (alias do antigo `--sem-docx`) para o CI. O selo é **seed + `n` + `caps`**, e
  `caps` mudou de significado: são quatro formatos agora, não só `docx`.
- **`eval/adaptador_sintetico.py` converte para o harness e recusa eixo
  colapsado.** Nenhum eixo declarado pode ter pergunta no balde "não declarado".
  Vale para `fatia` e `armadilha_fatia`; quem chama escolhe, porque no dourado
  real `armadilha_fatia` nasce vazio e isso é correto.
- **`harness.Pergunta` ganhou `armadilha_fatia`**, campo novo com default vazio —
  o **terceiro** eixo de recorte. `fatia` continua sendo idioma, para não
  reescrever o `C4.5`.
- **A ordem `E5` → `E1` → `F4-P` cumpriu-se.** A `F4-P` é o próximo pacote do
  notebook, encolhida ao defeito e com aceite binário.

**A revisão de completude (`E1.d`/`E1.e`/`E1.f`) mudou três coisas que te
afetam:**

- **`tests/cfb.py` mudou de casa** para `eval/gerador/cfb.py`, e continua
  existindo como reexport de duas linhas. O gerador passou a precisar do mesmo
  construtor de CFB para emitir `.msg`, `.doc` e `.ppt`. **Isso é do seu `F4-L`**:
  ele declara `tests/cfb.py` na lista de paths, e o arquivo segue lá funcionando —
  mas quem for **estender** a fixture, estenda `eval/gerador/cfb.py`.
- **O `F4-L` ganhou fixture.** Até agora o pacote estava aberto sem nenhum arquivo
  legado contra o qual rodar. O corpus tem `.doc` e `.ppt` válidos (via OLE, lidos
  pelo `ole_texto`), e as duas formas hostis de `.xls` que o pacote persegue: o
  CFB que o `xlrd` recusa (`XLRDError: Expected BOF record`) e o HTML com extensão
  trocada — que o parser de planilha, medido, **lê**. Nenhum parser foi tocado.
- **A `F6-E` fechou**, absorvida pelo `E1.e`. Ela era porta de fase e estava com
  "dono a combinar"; o gerador é o montador de pastas, e manter as duas separadas
  produziria duas fixtures da mesma classe.

**O que isso te dá:** um corpus de 1.174 documentos e 651 perguntas em `n=30`, com
as 17 extensões que o produto lê, os 9 estados de `ParseStatus` cobertos ou
declarados, e os 7 mecanismos de `retrieve/` exercitados. Ele roda no desktop sem
nada do acervo corporativo — é o que `docs/colaboracao.md` §5 sempre prometeu e
agora vale a pena rodar.

**Um recado sobre o `R9.1`, que é seu.** O corpus sintético agora cruza os dois
eixos: reunião × cross-lingual = 10 e email × cross-lingual = 10 em `n=30`, na
proporção do dourado real (3 das 11). Quando o perfil bilíngue existir, ele tem um
segundo conjunto contra o qual se conferir — e é onde o `fts_caminho = 0,3` deixa
de depender de uma pergunta em doze.

### `F4-P` fechada em 25/08/2026 — e o desktop precisa saber disto

[`ablacao-f4p-nome-no-entregue.md`](ablacao-f4p-nome-no-entregue.md). O
`RanqueadorDeNome` passou a existir em `buscar_chunks`, que é o caminho que a
ferramenta MCP executa. **Nenhum valor de `[padrao]` mudou** — `PESO_NOME` já era
0,5. O que mudou é que agora ele faz alguma coisa nos dois caminhos, e não só em
`search`.

Por que isto é do desktop também, e não só uma nota de rodapé do notebook:

- **Todo número de peso de nome que o desktop tenha medido em `buscar_chunks`
  antes desta data mediu zero**, porque o sinal era inerte ali. Números medidos
  em `search` continuam válidos e continuam sendo a série histórica.
- **O caminho entregue mudou de patamar**: MRR@10 0,671 → 0,696, e ele agora bate
  o `search` (0,680) no acervo corporativo. Quem for comparar caminhos precisa
  refazer a comparação, não reusar a tabela de 24/08.
- **`eval.comparar` ganhou dois botões**: `--entregue`, que põe **os dois** braços
  no caminho do cliente, e `--peso-nome-depois`, o braço assimétrico do peso de
  nome — a irmã de `--rerank-depois`.
- **A varredura de peso por tipo de fonte deixou de estar cortada pela regra 11.**
  O efeito mínimo que faltava apareceu: nDCG@5 de reunião **−0,089 [−0,172,
  −0,017]**. Ela continua bloqueada pela outra metade, que é do `E1` — saber se o
  peso generaliza para acervo que não é este. **Não começar sem os perfis
  sintéticos.**

### `F4-P.1` bloqueada por falta de parser, e dois recados (27/08/2026)

Laudo em [`fatia-reuniao-invisivel.md`](fatia-reuniao-invisivel.md). Auditando o
`index-e1` **antes** de gastar a medição: a fatia `reunião` da camada 2 tem
**n=0**, não n≈100. As 100 perguntas apontam para `.vtt`, e `.vtt`/`.srt`/`.sbv`
não estão em `supported_extensions()` — não existe parser de transcrição. Rodar a
medição declarada daria empate, e o critério de encerramento fecharia o pacote com
"hipótese refutada" cumprindo todas as regras.

**1. `F4-T` fechado, e eu toquei o despachante — leiam esta linha.**
`ingest/parsers/vtt.py` (novo, `.vtt`/`.srt`/`.sbv`) é do notebook pelo contrato de
dono por arquivo. **E `ingest/parsers/__init__.py` mudou**, que é "um de cada vez":
uma linha, o `import vtt` no `_load_all`. Parser não registrado é código morto,
então sem ela o pacote não existiria — e o usuário deu o sinal para seguir em vez
de esperar.

**O que preciso que vocês confiram:** se o `F4-O.2` encostar em
`ingest/parsers/__init__.py` (o plano prevê "só se a versão exigir"), o conflito é
essa linha e nada mais — resolvam mantendo as duas entradas na lista de import. Se
preferirem que eu reverta e vocês registrem no PR de vocês, digam e eu reverto; o
`vtt.py` sozinho não conflita com nada.

**Efeito mínimo cumprido, medido:** fatia `reunião` do `index-e1` de **0 para 100**
perguntas com fonte indexada, 3 para 103 documentos candidatos, 17 para 20
extensões suportadas. A passada de reindexação **não terminou** (máquina a 89% de
memória, ver o recado 2) e quarentenou 4 documentos de `escritório` que antes
estavam `ok` — recuperáveis na próxima passada, porque quarentena é repescada.

**Três guardas deste repositório reprovaram sozinhas** quando
`supported_extensions()` cresceu, e é o melhor aval do desenho: a cobertura de
formato do gerador (`ValueError: formato desconhecido: sbv`), o teste que exige
`docs/comecar.md` listar exatamente o que o produto lê, e o `escrita.py` recusando
escrever formato que não conhece. **E uma quarta estava desarmada:** o round-trip
de `test_gerador_sintetico.py` pulava `.vtt` com `continue` e um comentário
errado ("é texto puro"), enquanto a docstring prometia que todo formato volta pelo
despachante. Virou `assert`. Detalhe em
[`fatia-reuniao-invisivel.md`](fatia-reuniao-invisivel.md).

**Paths do `F4-T`:** `src/segundocerebro/ingest/parsers/vtt.py` (novo),
`src/segundocerebro/ingest/parsers/__init__.py` (**uma linha** — o ponto de
acordo), `eval/gerador/transcricao.py` (novo), `eval/gerador/{escrita,fatias,formatos}.py`,
`tests/test_vtt.py` e `tests/test_gerador_transcricao.py` (novos),
`tests/test_gerador_sintetico.py` (o `continue` desarmado), `docs/comecar.md` (a
lista de formatos, obrigada por teste). Suíte: **1.196 passando**, 2 falhas — as duas
de `test_ocr.py`, as duas presentes na `main` limpa (`4abe045`), ver o recado 2. Nada de `retrieve/*`,
nada de `[padrao]`, nada de chunking.

Vale para os dois lados como regra, e não como episódio: **`.vtt`/`.srt` são a
saída nativa de Teams, Zoom e Meet.** Hoje o registro guarda o documento com zero
chunk, a barra conta o arquivo e a busca nunca o devolve — item 2 da régua de
prontidão, "falhar é aceitável, mentir em silêncio não".

**2. Dois testes de OCR passam ou falham só em função da memória livre — e isso é
o achado, não o incidente.**
`tests/test_ocr.py::test_indexar_ocr_depois_do_texto` falha em `6377a0a` **e** em
`cb4e1f7`, consistentemente, três tentativas. E depois do PR #42
`test_indexar_misto_com_ocr_junta_as_paginas` entrou com a **mesma** fragilidade:
as duas falham na `main` limpa em `4abe045`, aqui. A causa não é lógica: o subprocesso
de parse isolado morre com `OpenBLAS error: Memory allocation still failed after
10 retries`, e a quarentena marca o documento como `erro` em vez de `ok`.

Medido nesta máquina, mesmo commit, mesma suíte, no mesmo dia:

| memória livre | `tests/test_ocr.py` |
|---|---|
| 2,7 GB de 16,8 GB (84% usada) | **2 falhas** |
| 2,7 GB, repetido três vezes | 2 falhas, consistente |
| memória liberada pelo usuário | **1.208 passando, 0 falhas** |

Ou seja: o veredito da suíte é função do que mais estava aberto na máquina. **O produto se comportou certo** —
quarentenou em vez de quebrar. O teste é que afirma `status == "ok"` supondo que o
subprocesso isolado consegue alocar, e por isso confunde "o pipeline de OCR
funciona" com "a máquina tinha memória".

`tests/test_ocr.py` é do desktop (OCR), então **não** consertei — regra 8. Que a
`F4-O.2` tenha acrescentado um segundo teste com a mesma suposição é o argumento
para tratar isso como classe e não como caso: o próximo teste de OCR vai nascer
com ela. Sugestão,
para não virar teste intermitente que todo mundo aprende a ignorar: distinguir
`erro` por quarentena de falha de pipeline, ou declarar o piso de memória que o
teste exige. É a mesma classe do `F4-R` que fechei hoje: **braço que não registra o
regime da máquina mede a janela** — aqui, a janela de memória.

**E não é só o teste.** A reindexação do `index-e1` para o `F4-T` morreu pela mesma
causa: `OpenBLAS error: Memory allocation still failed after 10 retries` em série,
com subprocessos de parse estourando 150 s e 60 s e sendo quarentenados. Com esta
máquina neste estado **o indexador não completa passada**, e isso é informação de
produto: 16,8 GB com 89% em uso é notebook corporativo comum, e o modo de falha que
o usuário vê é documento quarentenado sem nenhuma menção a memória. Candidato a
entrada de pacote junto do `F4-R.1` e do teto de RAM do `F4-O.2`, que é de vocês.

### `F4-P.1` fechada por especificação, não por empate (27/08/2026)

Laudo: [`ablacao-f4p1-nome-por-fonte.md`](ablacao-f4p1-nome-por-fonte.md). A
medição rodou depois que a `F4-T` encheu a fatia, e deu `+0.000 [+0.000, +0.000]`
em **todas** as células. Intervalo de largura zero não é empate — é ausência de
manipulação: no corpus sintético o ranqueador de nome não pontua um único
documento de reunião, então zerar o peso dele não tinha em que agir.

E o achado que fecha o pacote: na camada 1, onde o dano de −0,089 existe, os
documentos que passam à frente da fonte de reunião são **11 de escritório contra 1
de reunião**. A alavanca zerava o peso nas vítimas. O contrato derivou o efeito
mínimo de uma fatia definida pelo grupo da **fonte esperada** e aplicou a alavanca
ao grupo do **candidato**; o nome igual escondeu que são populações diferentes.

**O que isto muda para vocês**, e é a parte que vale além deste pacote:

1. **`eval/comparar.py` passa a distinguir empate de insensibilidade.** Quando os
   dois braços devolvem o mesmo ranking em toda pergunta do recorte, a célula sai
   `∅` e o relatório diz, em texto, que a regra de encerramento **não se aplica**.
   Se um braço de vocês sair todo `∅`, é sinal de que a bandeira não está agindo —
   não de que a hipótese caiu.
2. **O relatório do `--entregue` mentia.** Ele afirmava que o ranqueador de nome
   não participa de `buscar_chunks`, coisa que a `F4-P` mudou em 25/08. Qualquer
   ablação de vocês nesse caminho saía com esse parágrafo. Corrigido, e com teste
   que lê o fonte e reprova se a prosa negar o código.
3. **`--entregue` com `--antes` no default (`baseline`) quebrava** com
   `AttributeError` na primeira consulta, depois de carregar índice e modelo. Passa
   a recusar na montagem.
4. **O indexador vaza nome de usuário para o `.mcp.json`, que é versionado.**
   Indexar uma base nova acrescenta uma entrada com o caminho absoluto do
   interpretador. Revertido aqui; guarda estrutural nova em
   `tests/test_saneamento.py`, porque a que existia é pulada quando a lista local
   está vazia — num clone limpo não havia guarda nenhuma. **Confiram se a passada
   de vocês fez o mesmo antes do próximo commit.**
### A afinidade: 16.1 retratado, e o notebook pega `esforco.py` emprestado (27/08/2026)

Laudo em
[`afinidade-e-estado-de-maquina.md`](afinidade-e-estado-de-maquina.md). Em uma
linha: **o achado 16.1 media a janela, não a máscara.** A mesma máscara do perfil
`normal` mede 0,141 e 3,19 s/chunk no mesmo notebook, conforme um regime de
agendamento do Windows que o produto não observa — e no regime benigno ela custa
**zero**. A causa que o 16.1 propôs (colisão de threads intra-op do ORT) está
refutada, e a minha hipótese substituta (reaplicar afinidade sobre threadpool
viva, `indexer.py:925`) também.

Três coisas que o desktop precisa saber:

1. **Não existe "~12× de vazão" esperando um conserto de máscara.** Quem tratar
   o 16.1 como pendência de otimização vai afinar máscara contra uma janela. O
   bloco na spec está marcado como retratado, com ponteiro para o laudo.
2. **A medição da estimativa v2 nas 980 Ti muda de requisito.** Ela era "modelo
   sequencial vs pipeline GPU" (spec §14); passa a precisar do regime gravado em
   cada observação, senão mede o mesmo artefato num hardware onde ninguém vai
   procurar por ele. No desktop o regime provavelmente é constante — o que é uma
   informação, e vale registrar como tal em vez de assumir.
3. **`index/esforco.py` fica emprestado ao notebook neste pacote**, pelo contrato
   que já rodou duas vezes (o `C3.a` com `store.py`, o `C5.a` com `eval/`):
   declarado aqui antes de começar, devolvido no merge. O motivo não é
   conveniência — é que **o desktop não tem bateria nem CPU híbrida**, e o defeito
   é condicional ao regime de agendamento de um notebook. Quem conserta tem de ser
   quem consegue reproduzir. Se o desktop preferir ficar com o arquivo, o pacote
   volta a ser dele e o notebook entrega só a medição; diga na §7.

**Nada de código de produto neste PR** — o instrumento vai versionado, o
conserto não. `eval/regime.py` é o harness que recusa o método que produziu a
conclusão errada: braços intercalados obrigatórios, contraste recusado com menos
de duas réplicas por braço, e regime de energia no relato de toda observação.
Máscara **não** muda aqui: o estado lento ainda não é reproduzível sob comando, e
trocar a máscara antes disso mede a janela outra vez. O item 1 do pacote é achar o
gatilho do EcoQoS; a ordem inteira, com efeito mínimo declarado e regra de
encerramento, está no laudo.

**Paths deste PR (notebook):** `docs/afinidade-e-estado-de-maquina.md` (novo),
`eval/regime.py` + `eval/test_regime.py` (novos), `docs/spec-estimativa-v2.md`
(bloco 16.1 marcado como retratado), `ROADMAP.md` (pacote `F4-R`), este arquivo,
`CLAUDE.md`. `ROADMAP.md` é "um de cada vez" e volta no merge. Nada de
`retrieve/*`, nada de `[padrao]`, nada de `index/esforco.py` **neste** PR.

### `F4-O.3` bloqueada, e o motivo é de vocês (28/08/2026)

Laudo: [`ocr-no-acervo-bloqueado.md`](ocr-no-acervo-bloqueado.md). Tentei a
medição do dourado de OCR. **O motor de vocês está verde aqui** — os 4 testes do
`F4-O.1` com `-m ocr` passam nesta máquina em 21 s. O que bloqueia é o indexador.

**A passada com `--ocr` não completa, e não falha: ela quarentena o acervo.** Duas
tentativas, mesma assinatura — processo principal em 0% de CPU, contador de chunks
parado, e a cada 61 s um documento vai para quarentena. A 666 PDFs isso é 11 h de
timeout puro com o índice piorando o tempo todo.

A cadeia, com o traceback na mão:

1. `isolamento.deve_isolar` manda todo PDF para subprocesso, por extensão;
2. o filho faz `runpy.run_module('segundocerebro.index.indexer')`, que importa
   `embeddings` e o **fastembed inteiro** — para parsear um documento, o filho
   carrega o encoder;
3. o OpenBLAS não aloca no filho (`Memory allocation still failed after 10
   retries`), porque o pai já segura o `e5-large`;
4. o filho não responde, o timeout de 61 s dispara, e o documento é **quarentenado**;
5. repete.

**O teto de RAM do `F4-O.2` não vale no Windows.** `_worker_parse` aplica
`resource.setrlimit` sob `os.name != "nt"`. O `plano-ocr.md` já dizia que a
hipótese (c) seria medida sem Job Object; esta passada é o número que faltava para
decidir se o Job Object se paga — e ele se paga.

**Três consertos, em ordem de custo, e os três são de vocês:** não isolar (ou reusar
processo de parse) quando o filho não couber; Job Object no Windows; e **falhar alto
quando o filho morre por memória, em vez de quarentenar** — documento que não pôde
ser lido por falta de RAM não é documento defeituoso, e tratar os dois igual é o que
transforma pressão de memória em perda de índice.

**E os dois testes de `tests/test_ocr.py` que oscilam são a canária disso** — mesma
mensagem do OpenBLAS, mesma causa. Passam com memória livre, falham sem. Vale tratar
como sinal.

Do meu lado ficou pronto o que a `F4-O.3` vai precisar quando a passada completar: o
índice `antes` congelado e `eval.comparar --indice-depois`, porque "com e sem OCR" é
diferença de **índice** e a ferramenta só aceitava um para os dois braços. As três
perguntas continuam `fora_de_escopo: ocr` — tirar a anotação sem a fonte indexada
criaria a fatia vazia que a `F4-P.1` acabou de ensinar a não criar.

### Passada de refatoração de base, e três coisas que são de vocês (29/08/2026)

Uma passada estrutural sobre as 45.731 linhas de Python, **sem mudar
funcionalidade**. Sete commits, cada um com a classe generalizada que o fecha; o
que não entrou virou os pacotes `Q11`–`Q19` do `ROADMAP.md`. O detalhe está lá; o
que muda para vocês está aqui.

**A suíte de `main` estava vermelha, e agora não está.** 7 falhas → 1. As seis do
`tests/test_watcher.py` eram o `aplicar_provider` que eu tinha reportado em 28/08
e que ficou sem conserto pela regra 8 — como ele é de `index/*`, eu não devia
mexer. **Mexi, e o motivo é que o mandato desta passada era a base inteira.** O
conserto preserva o comportamento: `resolver_provider()` responde "qual provider
vence" sem escrever, `aplicar_provider()` mantém nome, assinatura e a condição
exata de escrita, e o docstring passa a dizer que só o `main()` de um processo
pode chamá-la. Se vocês preferirem outra forma, o teste que fecha a classe é meu
e continua valendo: `conftest.py` da raiz tira foto de `os.environ` antes de cada
teste e devolve depois. A falha que sobra é `eval/test_golden.py` — duas fontes do
dourado saíram do disco na troca de notebook.

**O que passou a reprovar, e vale para os dois lados:**

| Guarda nova | Reprova quando |
|---|---|
| `tests/test_pacote.py` | qualquer módulo de `src/` importa `eval/` — varredura de AST, enxerga import dentro de função |
| `tests/test_tamanho_dos_modulos.py` | módulo novo acima de 500 linhas, função nova acima de 60, ou um dos grandes cresce |
| `tests/test_hybrid.py` | uma consulta gasta mais de 12 idas ao SQLite |
| `tests/test_painel.py` | abrir o painel carrega `fastembed`, `onnxruntime` ou o indexador |
| `conftest.py` (raiz) | — não reprova, restaura: `os.environ` volta ao que era depois de cada teste, em `tests/` **e** em `eval/` |

O `select` do `ruff` cresceu para `["E","F","BLE","S603","DTZ"]`. `BLE` custou
zero erro e deu sentido a 77 `noqa` que não suprimiam nada; `S603` custou cinco
`noqa` com motivo escrito. Os 264 que sobram, e a escada medida para ligá-los,
estão no `Q18`.

**`eval/arquivo/`** recebeu `varredura.py`, `varredura_fts.py`, `custo_miracl.py`
e `alarme_externo.py` — instrumento de pacote encerrado, fora da suíte padrão pelo
marcador `arquivo`, no mesmo desenho de `modelo`, `cuda` e `ocr`. Continuam
reproduzíveis: `py -m pytest -m arquivo`. `varredura.py` não tinha **nenhum**
importador nem teste, e o `ruff` e o `pyright` a liam a cada PR.

**As três que são de vocês, reportadas e não corrigidas (regra 8):**

1. **`Q15`, e é P0 de produto.** Sob pressão de memória o `pymupdf` falha ao
   carregar **dentro do filho de parse**, e o erro chega como
   `ModuleNotFoundError: No module named 'mupdf'`. O produto classifica como *sem
   parser*: o documento fica `vazio`, `digitalizado` nunca é marcado, a fila de
   OCR sai vazia, `progresso.ocr` é 0 — e **não há linha de quarentena**. No PDF
   misto o disfarce é melhor ainda: fica `ok` com os chunks das páginas nativas.
   Medido aqui em cinco passadas seguidas de `tests/test_ocr.py`: **2 reprovaram
   com 3,5–3,6 GB livres e 3 passaram com ~3,9 GB**, sem uma linha mudar. Liga na
   `F4-O.3`, que está bloqueada por vocês. A suíte já não confunde as duas coisas
   (`PISO_RAM_OCR_MB` faz o teste **pular** com o número, em vez de reprovar pela
   janela); o produto continua confundindo.
2. **`Q14`.** `SEGUNDOCEREBRO_OCR_FAKE` (`ingest/ocr.py:43,149`) desvia o motor de
   OCR sem nenhuma guarda de "só em teste". Variável herdada de sessão de shell
   muda o comportamento de produção sem uma linha no log.
3. **`mcp/registrar.py` ainda grava `PYTHONPATH=src` e `cwd` do repositório** no
   `.mcp.json` e no config do Claude Desktop. Desde o `pip install -e .` isso
   deixou de ser necessário, e para quem instalou por `pip` está **errado**:
   aponta o cliente para uma pasta que não existe. É item de `F6`, não de higiene,
   e eu não mexi porque muda o que o produto escreve no disco do usuário.

**Nada disso toca ranking.** `buscar_chunks` e `search` foram despejados para JSON
em 5 consultas contra o índice corporativo, antes e depois do lote de consultas, e
o `diff` saiu limpo — id, path, score com 9 casas, origem, antes e depois.

### Os pacotes `Q` da auditoria, executados — e quatro números dela que estavam errados (30/08/2026)

Cinco commits fecharam `Q11`, `Q12`, metade do `Q13`, `Q17` e `Q19`, mais a
superfície de pontos de entrada. Suíte: **1 falha / 1.232 passes → 1 falha /
1.361 passes**, mesma falha de dado, e o tempo de **143,5 s para 113,6 s**.

**O que muda para vocês, em ordem de quanto pode atrapalhar:**

| Guarda nova | Reprova quando |
|---|---|
| `tests/test_config_chaves.py` | chave desconhecida em qualquer nível do `config.toml` deixa de levantar, ou a lista declarada discorda do que a função leitora lê (AST) |
| `tests/test_isolamento_da_suite.py` | um arquivo de teste é importado por outro — dublê vai para `tests/falsos.py`, fixture vai para um `conftest.py` |
| `tests/test_pacote.py` | um `[project.scripts]` do `pyproject.toml` não virou executável instalado. A lista é **derivada** do TOML |
| `tests/test_documentacao.py` | link markdown em arquivo versionado aponta para arquivo que o Git não tem |
| `tests/test_config.py` | um valor do `config.example.toml` diverge do padrão do código; a porta do painel aparece em `scripts/`; o `index.html` embute tabela de tetos |

**Duas coisas que podem te pegar de surpresa no próximo rebase:**

- **`from tests.test_index import ...` não existe mais.** `DIM`, `EmbedderFalso`,
  `chunk`, `corpus`, `bytes_pdf` e `bytes_pdf_misto` moram em `tests/falsos.py`;
  `RecuperadorFixo` em `eval/falsos.py`; a fixture `store` em
  `tests/conftest.py`. Eram 18 sítios em 14 arquivos.
- **`config.py` (1.081 linhas) e `census.py` (978) estão no teto exato da
  escada.** Qualquer linha que vocês acrescentem a esses dois reprova até que a
  costura do `Q16` correspondente saia. Não é rigidez: foi o que forçou
  `config_escrita.py`, e é o que hoje bloqueia a outra metade do `Q13`.

**O que continua sendo de vocês** — o `Q15` (P0, o OCR que some em silêncio sob
pressão de memória), o `Q14` (`SEGUNDOCEREBRO_OCR_FAKE` sem guarda) e o
`mcp/registrar.py` gravando `PYTHONPATH=src`. Nada disso mudou; o relato de
29/08 acima continua valendo inteiro.

**Uma decisão que precisa dos dois, com o número que faltava.** O `Q18`
perguntava "apagar os `noqa` inertes ou ligar as regras?", e dizia que a escolha
não era óbvia. Medi o que faltava: em `src`, ligar
`ANN001,ANN201,ANN202,ANN401,ARG001,ARG002,T201,B007,N801,RET` faz **75 dos 92**
`noqa` inertes passarem a suprimir algo de verdade, ao custo de **40 correções**.
Apagar destruiria esse valor. Só que 8 desses 40 arquivos são de vocês —
`indexer.py`, `gpu_pool.py`, `smoke_cuda.py`, `estimativa.py`, `ocr.py`,
`ole_texto.py`, mais `registrar.py` e `painel/app.py`, que são "um de cada vez".
Ligar a regra obriga vocês a anotar os arquivos de vocês, então **não liguei**.
Recomendo ligar; em `tests/` e `eval/` a rota continua sendo apagar, porque lá
`per-file-ignores` mantém as regras desligadas.

**Um achado novo, fora de pacote:** `scripts/abrir-painel.cmd` ainda faz
`set PYTHONPATH=src`. É a mesma classe do item 3 acima, e sobreviveu ao `F6-A`
porque ninguém varreu `scripts/`. Não removi porque decidir como um clone sem
`pip install -e .` abre o painel encosta na `F6-B`, que é de vocês.

**Nada disso toca ranking.** Nenhum dos cinco commits entra em `retrieve/*`, em
peso, em chunking ou no caminho de consulta.

### `F4-D` fechada como instrumento, e um defeito de suíte que é de vocês (29/08/2026)

**O que muda nos relatórios dos dois lados.** `eval.rodar`, `eval.comparar` e
`eval.ablacao_f2` passam a trazer um bloco **Cobertura do conjunto dourado**, com
dois números: alcance por pasta (teto — pasta com ≥1 pergunta conta inteira) e
fontes esperadas (piso — só o documento-alvo). Medidos aqui em 29/08: **38,5%** e
**3,3%** sobre 1.900 documentos em 30 pastas. `eval/cobertura.py` também roda
sozinho — `py -m eval.cobertura --base <id>`, segundos, sem abrir o modelo.

**Por que isto era pacote e não enfeite:** o número da cobertura vivia escrito à
mão em dois documentos e estava errado nos dois (18,2% e 25%). Enquanto isso o
`recall@1` era citado como se valesse para o acervo inteiro, e crescer o corpus
**baixava** a métrica sem nada ter piorado. `render_markdown` sem cobertura agora
imprime "não medida" em vez de omitir — a classe fechada é "ressalva que envelhece
calada enquanto o número que ela qualifica segue circulando".

**Nada disso toca ranking.** Piso reproduzido na mesma passada: recall@1 0,551 e
MRR 0,680, iguais à série.

**O defeito que é de vocês, reportado e não corrigido (regra 8).**
`index/cuda_runtime.py::aplicar_provider` escreve `os.environ["SEGUNDOCEREBRO_PROVIDER"]`
no processo e nunca desfaz. Consequência medida aqui: rodando `py -m pytest tests/`
inteiro, **6 a 8 testes de `tests/test_watcher.py` falham** com
`RuntimeError: Não achei placa NVIDIA` — o mesmo arquivo passa verde sozinho. Um
teste que exercita `aplicar_provider("cuda")` envenena todos os que rodam
`indexar()` depois dele.

**E o modo de falha é assimétrico entre os dois setups:** no desktop
`diagnosticar()` diz `ok` e a suíte fica verde; aqui, sem placa, ela fica vermelha.
Quem só roda no desktop nunca vê. O conserto pertence a vocês porque `index/*` é de
vocês; a forma que eu sugeriria é a função **não** escrever no ambiente do processo
e devolver o provider para quem a chamou aplicar no escopo dele.

### O notebook assumiu os pacotes do desktop (30/08/2026)

**Autorização explícita do usuário**, e o motivo é de calendário: os créditos do
Grok da semana acabaram e o sistema precisa fechar em dois dias. A regra 8
continua valendo — *achado no acervo do outro se reporta, não se corrige* —, e o
que a suspende aqui é a decisão de quem é dono dos dois lados, não a minha
conveniência. Fica registrado para que a próxima sessão não trate isto como
precedente.

O que foi assumido e fechado, tudo em `ingest/ocr.py`, `index/isolamento.py`,
`mcp/registrar.py` e `scripts/`:

- **`Q15` (P0)** — sob pressão de memória o OCR sumia em silêncio. Causa: um
  `except Exception` devolvendo `None`, e `None` já significava "esta instalação
  não tem OCR". Fechado, **com resto declarado no `Q15.a`**: o status final do
  documento ainda fica `vazio` depois de uma fase de OCR quarentenada, e a causa
  é a ordenação de fases do indexador — que é o laço, e é de vocês. Não toquei.
- **`Q14`** — `SEGUNDOCEREBRO_OCR_FAKE` só vale sob `PYTEST_CURRENT_TEST` e
  avisa em toda passada com o texto que injeta.
- **`F6` no registrador do MCP** — ele gravava `PYTHONPATH=src`,
  `--config <raiz>/config.toml` e `cwd=<raiz>` **sempre**. Para quem instalou por
  `pip`, os três apontam para dentro do `site-packages`. Agora `PYTHONPATH` só
  num checkout, e `--config`/`cwd` vêm do config que o usuário de fato carregou.
- **`F6-B`** — o estágio 0 do painel ganhou a prova de ponta a ponta que faltava.

**O piso de RAM de `tests/test_ocr.py` saiu.** Se a suíte de vocês reprovar ali,
leiam a mensagem: ela carrega o regime da máquina, e a regra agora é *"ou o OCR
produziu texto, ou existe linha de quarentena com motivo de recurso"* — nunca
mais um skip por janela de memória.

**Uma coisa que continua sendo de vocês, e ficou mais fácil:** o `Q15.a` acima, e
o `F6-C` (hardware). E o `Q18`, que segue precisando de acordo — ligar as dez
regras baratas do `ruff` obriga a anotar oito arquivos de vocês, e a medição
(75 dos 92 `noqa` passam a valer por 40 correções) está no `ROADMAP.md`.

### O pacote J chegou, e a tabela de donos dele já nasce velha (30/08/2026)

Documento novo do usuário:
[`pacote-j-camada-acesso-corpus.md`](pacote-j-camada-acesso-corpus.md), marcado
*FINAL*. Ele acrescenta um **segundo modo de consumo** ao produto — ingestão
integral dirigida por agente, o *"escreva um paper sobre esta pasta"* — que
nenhuma das três tools de hoje serve. A peça central é o **Parse Store**: a
representação canônica de cada documento, persistida, promovida de cache interno
a camada de produto.

Conferi contra o código antes de tocar no plano, como os dossiês `R` e `C`
foram conferidos. O laudo é [`plano-pacote-j.md`](plano-pacote-j.md) e o resumo
está no `ROADMAP.md`. **Nada foi implementado nesta passada.** O que vocês
precisam saber, em quatro pontos:

1. **`J.a`, `J.b` e `J.f` estão atribuídos ao desktop na especificação**, e são
   os três P0 de infraestrutura. Com o crédito do Grok parado, ou vocês pegam
   quando voltar, ou o notebook assume também. **Não comecei nenhum dos três** —
   `J.a`/`J.f` tocam o laço de `index/indexer.py`, que é de vocês por §1, e
   assumir isso de novo precisa de autorização nova, não da de 30/08.
2. **A dependência `J.d → R1.3` não vale aqui.** `R1.3` continua absorvido por
   `C6` e continua *não implementar* — MinHash a 0,85 refaz a `g045`. O conceito
   de canônico que o `pack_folder` precisa já existe em `retrieve/familias.py`,
   por nome, e é do notebook.
3. **Se vocês pegarem o `J.a`, a chave da entrada tem de carregar a versão do
   motor externo, não só `parser_version`.** Três rotas do produto passam por
   binário que não é nosso — LibreOffice (`R1.1`/`C7.a`), OCR (`R1.2`) e o
   recálculo de planilha. Um upgrade de sistema que troca o soffice deixa o cache
   servindo parse velho **para sempre**, e a mitigação que a especificação propõe
   (regra de PR no bump) não dispara: ninguém commitou nada. É o único risco
   sub-declarado do pacote, e é da família de falha silenciosa que este
   repositório já pagou duas vezes.
4. **O que o notebook começa, e que não cruza com vocês:** `J.b1` (o `doc_id`
   público sobre `documentos.sha256`, que já é coluna) e `J.c-mapa` (`outline` e
   `list_folder`, servidos do registro). Paths: `index/store.py`, `mcp/server.py`
   — que é "um de cada vez" e volta no merge —, e um `mcp/leitura.py` novo,
   porque `construir` já tem 148 linhas e a escada do
   `tests/test_tamanho_dos_modulos.py` só desce.

Três números medidos aqui que mudam o desenho, e que valem para o acervo de
vocês também:

- **29 de 2.156 documentos (1,3%) não têm `sha256`** — 27 `sem_parser`, 2
  `travado`. `doc_id` derivado de hash não cobre o acervo inteiro, e
  `list_folder` promete id justamente para o item que nunca foi aberto.
- **223 de 2.127 caminhos (10,5%) são byte-idênticos a outro.** O "um preferido"
  é 1 em 10, e hoje quem escolhe é a ordem de indexação.
- **Chunk não reconstrói documento:** 14.399 caracteres viram 9 chunks somando
  15.999, **+11,1%** pela sobreposição de 200. `get_document` precisa do store;
  não há atalho pelos chunks.


### Agora — desktop

**Neste PR (`f4-w-usn`, `R5.1`):** o observador recupera o que mudou com o
processo desligado, via journal USN. Catch-up em `index/usn.py`; o vivo
continua watchdog. Sem elevação — `FSCTL_READ_UNPRIVILEGED_USN_JOURNAL` +
`OpenFileById`. Apagado com o observador desligado continua sendo uma
passada de **Indexar** (o ioctl sem privilégio não traz o nome).
**Não toca o laço do indexador.** Nada de `retrieve/*`, nada de `[padrao]`.
A passada do acervo privado segue no fundo; não interromper. Não commitar
`.mcp.json`.

**Paths deste PR:** `src/segundocerebro/index/usn.py` (novo),
`src/segundocerebro/index/watcher.py`, `tests/test_usn.py` (novo),
`tests/test_watcher.py`, `docs/comecar.md`, este arquivo, `ROADMAP.md`.
`ROADMAP.md` é "um de cada vez" e volta no merge.

**Cinco pacotes prontos para começar, nenhum bloqueado por nada.** A ordem é
sugestão; os três primeiros são a onda 1 e destravam as ondas 4 e 5.

1. ~~**R9.1 + C5.b — perfis sintéticos.**~~ **Absorvido pelo `E1` em 24/08/2026 e assumido pelo notebook** — ver a seção acima e [`avaliacao-pacote-e1.md`](avaliacao-pacote-e1.md). **Não pegar.** O que sobra para o desktop aqui é `E6.1`: as distribuições do censo que parametrizam o gerador. O texto original fica abaixo porque o contrato do perfil bilíngue continua valendo, agora como condição de entrada do `E1`.

   Quatro perfis (`juridico`, `financeiro`,
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
2. ~~**C5.a — porta de custo do MIRACL.**~~ **Fechado em 26/08/2026.**
   [`docs/custo-miracl.md`](custo-miracl.md). O MIRACL publicado **não tem `pt`**
   (18 línguas, Zhang et al. 2023) — a porta descobre isso sem baixar. MIRACL sai
   da ablação por `lingua_ausente`; a conta de 12 h fica para o próximo corpus PT
   da mesma ordem (semente GPU: 1M ≈ 22,5 h, 100k ≈ 2,2 h). O smoke (`--medir`)
   recusa trava viva e **não rodou** nesta passada: a indexação do acervo privado
   segue no fundo.

   **Paths deste PR:** `eval/custo_miracl.py`, `eval/test_custo_miracl.py`,
   `docs/custo-miracl.md`, este arquivo, `ROADMAP.md`. `eval/` é do notebook; o
   desktop pega estes dois arquivos neste PR e devolve no merge — o mesmo
   contrato do `C3.a` com `store.py`. Nada de `retrieve/*`, nada de `[padrao]`,
   nada de encoder no caminho padrão da suíte.

   **C5.c — sucessor do MIRACL, fechado na mesma passada.** Camada 3 =
   `quati-50k` (~1,1 h, nativo, CC-BY-4.0). Pirá 2.0 = canário PT↔EN. mMARCO-pt,
   Quati-1M e JurisTCU fora. Sem download. Paths a mais: `eval/alarme_externo.py`,
   `eval/test_alarme_externo.py`, `docs/alarme-externo.md`.
3. **F6-A / R8.1 — empacotamento.** `[project.dependencies]` com pins
   (`fastembed>=0.8,<0.9` — a lição do pooling CLS→mean já foi paga),
   `requirements.txt` vira lockfile de CI, extras `[gpu]`/`[ocr]`, matriz
   `windows`+`ubuntu`+`macos` no CI. Alvo: `pip install` + um comando sobe o
   servidor em venv limpa, sem `PYTHONPATH`.
4. ~~**C7.a + C7.d — perda silenciosa em planilha.**~~ **C7.d** PR #34, **C7.a**
   PR #35. Recálculo via LibreOffice headless — **mesmo binário do R1.1**.
5. ~~**R1.4 + R5.2 + R3.2**~~ — **fechado no PR #36.** Quarentena, orçamento,
   dois passes (rascunho = parse+FTS).
6. ~~**F4-L / R1.1**~~ — **fechado no PR #37.** Converter legado via o mesmo
   soffice do C7.a.
7. ~~**F4-O / R1.2 — porta (`f4-o-ocr`).**~~ PR #38. Fila depois das ondas
   de texto, extra `[ocr]`, suíte sem o extra idêntica. Motor falso.
8. ~~**F4-O plano (`f4-o-plano`).**~~ PR #40. Contrato O.1/O.2/O.3 em
   [`plano-ocr.md`](plano-ocr.md).
9. **F4-O.1 — neste PR (`f4-o1-motor`).** RapidOCR no raster de produção
   (`Matrix(2,2)`) recupera identificador VCE plantado (`NN-VCE-001`) numa
   página-imagem, **sem** `OCR_FAKE`. Marker `ocr` fora da suíte padrão e
   do CI. **Não começa O.2.**

   **Paths deste PR:** `ingest/ocr.py` (API 1.3–1.4 pinada em comentário),
   `tests/test_ocr_motor.py` (novo), `pyproject.toml` (marker `ocr`),
   `docs/plano-ocr.md`, `docs/comecar.md`, este arquivo, `ROADMAP.md`.
   `ROADMAP.md` é "um de cada vez" e volta no merge. Nada de `retrieve/`,
   nada de `[padrao]`, nada de `parsers/__init__.py`.

   **Estimativa v2 nas 980 Ti:** a passada do acervo privado ainda é o
   processo da v1 (GPUs ocupadas). Não interromper. Medição da spec §14
   fica para a próxima passada com o código novo.

**Não começar** `[padrao]`, `Chunking`, `model_id`, `retrieve/*` — e **não
implementar `R1.3`**: o complemento mostrou que MinHash a 0,85 fundiria o que
`familias.py` separa de propósito e reintroduziria o `g045`. `R1.3` está
absorvido por `C6`, que é do notebook. **Não começar C7.b/C7.c** (onda 5,
pede ablação).

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
Serve base desconhecida: (que defeito isto conserta para quem instala amanhã)
Efeito mínimo declarado: (fatia, valor, e o veredito que o E5 daria)
Classe generalizada: (que classe de defeito fecha, e o que passa a pegá-la)
```

As três últimas linhas são de 25/08/2026 e vêm das regras 10 a 12 da §4. Linha em
branco é resposta aceita **só** com motivo escrito ao lado — "pacote de laboratório,
não serve base desconhecida" é motivo; deixar vazio não é.

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
| Afinar peso no acervo corporativo porque é o que temos medido | ganho de um acervo só, que o usuário leigo não herda (regra 10) |
| Varrer uma grade "para ver o que dá" | um dia de análise para um efeito menor que o ruído — foi o `C3.a` (regra 11) |
| Consertar o caso e fechar o pacote | a classe volta na base do usuário, onde ninguém está olhando (regra 12) |
