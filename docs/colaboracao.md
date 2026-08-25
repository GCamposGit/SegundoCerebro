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

### `R8.1.b` medido — o console script não é alcançável por nome (25/08/2026)

**Recado para o desktop.** O `R8.1.b` estava registrado como suspeita ("o defeito
de `_script()` achar o console script pelo `sys.executable`"). Ele tem medição
agora, e é **falha da régua de prontidão item 1** — instala frio.

Medido no notebook, no PowerShell, que é o shell do usuário:

- `pyproject.toml` declara quatro console scripts (`segundocerebro-mcp`, `-painel`,
  `-indexar`, `-censo`) e os quatro `.exe` **existem**, em
  `…\Programs\Python\Python312\Scripts\`.
- O `PATH` desta máquina tem `…\Python312`, e **não** tem `…\Python312\Scripts`.
- `Get-Command segundocerebro-mcp` → **não encontrado**. Os quatro, idem.

Numa instalação de usuário do Python (não em venv), `pip install -e .` põe os
pontos de entrada num diretório que o `PATH` não vê. O leigo que siga uma página
dizendo `segundocerebro-painel` recebe "comando não encontrado" — silencioso
quanto à causa, que é o pior modo de falha e é o mesmo que a `RELATIVO` de
`mcp/registrar.py` já documenta para o `ModuleNotFoundError`.

**Duas consequências que valem mais que o conserto:**

1. **`mcp/registrar.py` tem de continuar emitindo `py -m segundocerebro.mcp.server`,
   e não o console script.** Trocar por `segundocerebro-mcp` parece modernização e
   quebraria o registro de todo cliente nesta classe de instalação. Fica escrito
   aqui para ninguém "melhorar" nessa direção.
2. **O `.mcp.json` versionado não é o defeito.** Conferido por execução: ele sobe,
   resolve a base e acha o índice, de `C:\Windows\System32` e sem `PYTHONPATH`. O
   `PYTHONPATH = "src"` que ele carrega é obsoleto desde o PR #14 e é inerte —
   `tests/test_pacote.py` já garante que o pacote importa sem ele. Não vale um PR.

**Dono: desktop** (`Q2`, tabela dos pacotes Q). O notebook não conserta por conta
da regra 8 da §4. Não vem teste de reprodução junto por escolha do usuário — o
número acima é de **uma** máquina, e a segunda medição é de quem tem a segunda
máquina.

### Agora — desktop

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
