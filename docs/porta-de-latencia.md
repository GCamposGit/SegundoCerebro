# A porta de latência — R9.3

**24/08/2026, notebook.** Condição C: acervo corporativo, índice com 2.156
documentos e **98.326 trechos**, `e5-large`, CPU. Máquina `notebook-15w`:
i7-1355U de 15 W, 12 fios, 10 para a busca. Sem GPU.

"Rápido, para não ficar perdido em buscas enormes" é requisito do usuário desde
o começo, e até hoje nenhuma porta o media. Este documento é a saída do pacote
`R9.3` de [`dossie-melhorias.md`](dossie-melhorias.md): o instrumento
(`eval/latencia.py`), as portas (`eval/portas-latencia.toml`) e as três coisas
que a medição corrigiu na proposta.

---

## O que o sistema faz hoje

Braço medido sozinho, consultas do conjunto dourado, 3 descartadas no
aquecimento. **A faixa não é ruído de arredondamento: é a máquina.** Cinco
passadas independentes do braço `search` no mesmo índice deram p95 de 1 840,
1 916, 2 713, 2 847 e 2 877 ms, e a diferença entre as pontas é o estado térmico
do notebook — ver a correção 2. Uma passada só, apresentada como "o que o sistema
faz", seria o mesmo tipo de número indefensável que este pacote existe para
acabar.

| Operação | n por passada | p50 | p95 | porta original (24/08) | distância original |
|---|---:|---:|---:|---:|---:|
| `search` | 186 | 1 363 – 2 506 ms | **1 840 – 2 877 ms** | 300 ms | **6,1× a 9,6×** |
| `search+rerank` (10 cand.) | 62 | 10 119 ms | **11 331 ms** | 800 ms | **14,2×** |
| `read_note` | 186 | 0,3 – 0,4 ms | **0,9 – 2,8 ms** | 100 ms | passa por 36× ou mais |
| `neighbors` | 186 | 0,2 ms | **1,6 – 2,1 ms** | 100 ms | passa por 48× ou mais |

Esta tabela é o registro da proposta original. A decisão de 04/09, ao fim deste
documento, substitui `search = 300 ms` por um orçamento fim a fim de 4 s e retira
a porta de produto do rerank até existir uma implementação adequada para CPU.

`search+rerank` tem uma passada só, no regime quente; a faixa dele não foi
medida.

**Todo o orçamento de latência é `search`.** `read_note` e `neighbors` passam a
porta de produto por mais de uma ordem de grandeza em qualquer regime, e não
voltam a ser assunto até alguém trocar consulta indexada por varredura. Otimizar
qualquer um dos dois é tempo gasto onde não há problema.

E um número derivado que decide um pacote inteiro: reranquear 10 candidatos
custa cerca de `10 119 − 2 506 = 7 613 ms`, ou **~761 ms por par
documento-consulta**. A subtração cruza duas passadas, porque cada uma mede um
braço só — mas as duas são do mesmo regime quente e seguidas, e a ordem de
grandeza é o que decide. Não é um custo que se ajusta: é a classe do modelo
neste hardware.

## As três correções que a medição faz na proposta

### 1. Duas portas, não uma

O dossiê propõe `search` p95 abaixo de 300 ms. Medido, o p95 fica entre **6×**
e **9,6×** isso, conforme o estado da máquina — e num índice **10× menor** que o
alvo de 1M trechos. Nem a ponta mais favorável chega perto. Uma porta que a
máquina reprova no dia em que é escrita não guarda nada: fica vermelha para
sempre, e ninguém repara quando piora.

Então são duas, e só a segunda pode falhar:

- **porta de produto** — o alvo, hardware-neutro. Hoje reprovada. É o número que
  `R4.1` (ANN) e `R3.3` (quantização) têm de alcançar, e existe para dizer
  quanto falta.
- **piso de regressão** — o que *esta* máquina faz, mais margem. É a porta que
  vale agora, a que `--porta` usa para sair com código 1.

### 2. Número sem máquina é mentira — e sem estado térmico também

A regra 7 de [`colaboracao.md`](colaboracao.md) diz que número sem corpus é
mentira. Latência tem duas dimensões a mais, e a segunda foi surpresa.

**Máquina** era esperado: 2 713 ms num i7 de 15 W não diz nada sobre o desktop,
e um piso medido lá reprovaria aqui todo dia. Por isso o piso é por máquina
nomeada e `--porta` exige `--maquina`.

**Estado térmico** não era. O mesmo código, no mesmo índice, no mesmo dia:

| Passada | p95 de `search` | contexto |
|---|---:|---|
| 3 rodadas, máquina fria de verdade | **1 515 ms** | n=186, acrescentada ao rodar a porta do `C3.a` |
| 3 rodadas, máquina descansada | 1 840 ms | n=186 |
| 1 rodada, máquina descansada | 1 916 ms | n=62 |
| 3 rodadas, logo após outra passada | 2 713 ms | n=186 |
| 1 rodada, logo após outra passada | 2 847 ms | n=62 |
| 3 rodadas, logo após outra passada | 2 877 ms | n=186 |
| interleavada com reranking | 4 394 ms | ver correção 3 |

Entre a mais fria e a mais quente há **1,9×**, e entre a fria e a contaminada,
**2,9×**. Nenhuma linha de código mudou entre elas.

A primeira linha entrou em 24/08/2026, ao rodar a porta antes de fundir o `C3.a`
(que **não** toca o caminho de consulta com a configuração padrão). Ela não
corrige nada acima: **amplia** a faixa para baixo, e é o argumento inteiro deste
documento aparecendo mais uma vez. Se o piso desta máquina tivesse sido ajustado à
passada de 1 840 ms — que na hora parecia "a fria" —, a régua já estaria 18% acima
do que a máquina realmente faz descansada, e a próxima passada quente reprovaria
uma mudança inocente. **Piso na ponta quente, sempre**, e a faixa se lê como faixa.

E a deriva **não é dentro da passada**: numa passada de três rodadas as p50
saíram 1 404 → 1 394 → 1 310 ms, amplitude de 7%. O que decide o regime é o que
rodou nos minutos **anteriores** — o chip de 15 W chega saturado ou descansado, e
fica no regime em que começou. É por isso que a série por rodada, sozinha, não
autoriza a conclusão "medição estável": ela diz que o regime não mudou durante
aquela passada, e nada sobre qual regime era.

**Isto reconcilia a linha de base de 1.145 ms / 1.418 ms que o `ROADMAP.md`
registra.** Ela não está errada: está sem protocolo. Foi medida num estado que
não foi declarado, e por isso não é reproduzível — que é exatamente o problema
que `R9.3` existe para resolver, demonstrado no próprio número do projeto. O
registro novo declara máquina, braço, rodadas, aquecimento e n.

Duas consequências práticas:

- O relatório passou a imprimir **p50 por rodada, na ordem**. Ela não resolve o
  problema — a deriva é entre passadas, não dentro delas — mas separa os dois
  casos: uma série que cresce diz que a máquina esquentou *durante* a medição,
  uma série plana diz que o regime não mudou, e nenhuma das duas diz qual regime
  era. Sem a série, os dois viram o mesmo número agregado.
- O piso desta máquina é deliberadamente posto na **ponta quente** (1,15× o pior
  p95 observado), para nunca piscar vermelho por causa do ventilador. O preço é
  que ele é uma guarda **grossa** neste hardware: pega regressão de ~15% sobre o
  pior caso, não de 5%. Uma máquina com envelope térmico estável — o desktop —
  carrega um piso muito mais apertado. É mais um motivo para o piso ser por
  máquina.

### 3. Um braço por passada

A primeira versão media `search` e `search+rerank` no mesmo laço. `search` saiu
a **4 394 ms**; medido sozinho, o mesmo braço no mesmo índice dá **2 713 ms**.
São 53% de diferença, e a causa é o cross-encoder saturando o pacote térmico —
o braço barato paga a conta do caro.

Instrumento cujo braço barato depende de qual outro braço rodou junto não mede
nada. E o pior é que **o número contaminado é plausível**: 4,4 s não parece
absurdo para uma busca, então passaria. Agora é um braço por passada, e o
relatório diz qual.

Houve um segundo caso da mesma família, achado no mesmo dia: a primeira versão
media `recursos.busca`, que herda o reranker que a base configura, e chamava o
resultado de `search`. O braço rotulado "sem rerank" saiu **6,6× mais lento** que
a linha de base do ROADMAP, com o rótulo mentindo. Rótulo de braço tem que
descrever o braço, não o que a configuração calhou de ter.

## Os pisos, e de onde saiu a margem

```toml
[regressao.notebook-15w.p95]
search           = 3300
"search+rerank"  = 13000
read_note        = 50
neighbors        = 50
```

- **`search` = 3 300 ms.** 1,15× o **pior** p95 de cinco passadas independentes
  do braço isolado (o pior é 2 877 ms). Deliberadamente na ponta quente: um piso
  ajustado à passada fria (1 840 ms) reprovaria a máquina toda vez que alguém
  medisse depois de indexar, e um gate que pisca vermelho por causa do ventilador
  é desligado em uma semana.

  O preço está declarado: sobre a **passada fria** este piso tolera 79% de
  regressão. Ele é uma guarda grossa neste hardware. A alternativa — medir sempre
  em estado térmico controlado — não é executável num notebook de trabalho.
- **`search+rerank` = 13 000 ms.** 1,15× o p95 medido (11 331 ms), com **10
  candidatos** — o que a base serve, não a constante do módulo (25). Medir com a
  constante inflaria o piso em 2,5× e ele nunca dispararia.
- **`read_note` e `neighbors` = 50 ms.** Estes são **guarda de classe**, não
  detector fino: a p95 dos dois é sub-milissegundo, e nessa escala o ruído do
  escalonador é maior que qualquer sinal. Um piso apertado piscaria vermelho por
  troca de contexto. O que 50 ms pega é o que importa — uma mudança que troque
  consulta indexada por varredura, que custa ordens de grandeza e não por cento.

## O que fica de fora, e por quê

- **`overview` não existe.** O dossiê lhe dá porta de 200 ms; ele é `R7.1`, onda
  7. Não entra no arquivo de portas: porta de ferramenta ausente mede zero e
  reporta aprovado, que é pior que não ter porta.
- **A serialização JSON-RPC do MCP não é medida.** O instrumento mede a
  recuperação — a camada que mudança de ranking move, e a que a porta existe
  para guardar. É uma exclusão declarada, não uma suposição de que seja pequena.
- **A porta não roda no CI.** O CI não tem o acervo, o índice nem o encoder
  (`colaboracao.md` §3). É uma porta **local e manual**, rodada antes de fundir
  mudança de ranking. Automatizá-la depende do índice sintético inflado, que é
  do desktop.
- **`neighbors` devolveu documento ligado em 45 de 186 chamadas.** O resto voltou
  vazio — o caso honesto e comum. O relatório conta, porque chamada que não
  devolve nada é rápida por não ter assunto, e inflaria a aprovação da porta.

## O que isso decide na fila

- **`R4.1` (ANN) ganhou medida e implementação.** Acima de 200 mil vetores o
  indexador cria IVF-PQ e retreina depois de 30% de crescimento; a busca exata
  continua disponível como fallback e referência. No milhão inflado, ANN levou
  o braço denso a 349–370 ms p95 no caminho entregue. É ganho de classe, mas
  ainda reprova a meta de 150 ms do pacote.
- **`R6.2` (rerank v2) tem uma meta impossível, e agora dá para dizer por quê.**
  O pacote pede "30 candidatos em menos de 500 ms em CPU de 4 núcleos". A 761 ms
  por par, 30 candidatos custam ~22,8 s — **46× a meta**. Não é ajuste: é a
  classe do cross-encoder neste hardware. `R6.2` tem de escolher entre GPU (a
  rota da F3.6) ou outra classe de reranqueador.
- **A decomposição mostrou dois gargalos, não um.** Depois do ANN, BM25 ficou em
  1 708 ms p95 contra 349 ms do denso, 381 ms do encoder, 5 ms do nome e 9 ms
  da fusão+hidratação. Portanto R4.2 é obrigatório; INT8 sozinho não fecha a
  porta de produto.

## Reproduzir

```bash
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 1 --rerank
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3 --decompor-search
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3 --porta
py -m eval.ann --base padrao --construir --out docs/metricas-f4-r41-ann.md
```

O comando com `--porta` sai com código 1 se um piso de regressão for rompido. `--porta` sem
`--maquina` é recusado: piso sem máquina não é porta, é número solto. Os
relatórios vão para `docs/metricas-f4-r93-latencia*.md`, gitignorados por padrão.

## Índice inflado — desktop (02/09/2026)

As portas estão definidas. Faltava o índice de 1M trechos. Embeddar 1M
documentos do zero nesta máquina é ~22 h; o método é **perturbar vetores que
já existem**, a receita do `R4.1`, sem carregar o encoder.

```bash
py -m segundocerebro.index.inflar --origem index-sintetico --destino index-r93-1m --n 1000000 --seed 42
py -m eval.latencia --base <id> --maquina desktop-980ti --rodadas 3 --porta
```

O destino é `/index-*/`, gitignorado. A guarda é `tests/test_inflar.py`: N
trechos, chunks = vetores, busca densa ainda devolve, e o módulo não importa
`fastembed`. Medir o 1M é a passada local; o pacote é o método.

### Piso `desktop-980ti` — 02/09/2026

Três passadas independentes, braço `search`, CPU, `e5-large`, índice inflado
de 1 000 000 trechos, dourado sintético n=30:

| Passada | p95 `search` | p50 por rodada |
|---|---:|---|
| 1 | 7 402 ms | 7 102 → 6 839 → 6 450 ms |
| 2 | **8 039 ms** | 6 440 → 6 358 → 6 537 ms |
| 3 | 7 632 ms | 6 573 → 6 416 → 6 452 ms |

Piso: 1,15 × 8 039 = 9 245, arredondado para baixo a **9 200 ms**. Porta de
produto (300 ms) reprova **24,7× a 26,8×** — é o alvo do `R4.1`. `read_note`
passa (p95 ≤ 1,2 ms). `neighbors` e `search+rerank` não foram medidos nesta
leva (sem grafo no inflado; um braço por passada). Relatórios gitignorados:
`docs/metricas-f4-r93-latencia-desktop*.md`.

## R4.1 e R4.2 no milhão — desktop (03/09/2026)

A decomposição foi executada dentro da mesma chamada entregue por `search`.
Ela mostrou que nome e fusão eram irrelevantes para a cauda; varredura densa e
FTS respondiam pelo custo. O índice IVF-PQ foi então criado automaticamente com
4 000 partições e 128 subvetores. A configuração de consulta usa 256 partições
e reordena exatamente um orçamento constante de 10 mil candidatos — não um
fator constante que cresceria de 10 mil para 100 mil quando o produto pede 200
candidatos para a fusão.

| Passada (n=10, 1 rodada) | p95 `search` | encoder | denso | bm25 | nome | fusão+hidratação |
|---|---:|---:|---:|---:|---:|---:|
| flat, antes do ANN | 54 319 ms | 446 ms | 34 915 ms | 18 899 ms | 5 ms | 59 ms |
| ANN, refino proporcional incorreto | 3 738 ms | 295 ms | 1 484 ms | 1 967 ms | 5 ms | 53 ms |
| ANN, orçamento absoluto de 10 mil | 2 592 ms | 484 ms | **370 ms** | 2 011 ms | 5 ms | 13 ms |
| após `FTS5 optimize` | **2 379 ms** | 381 ms | **349 ms** | **1 708 ms** | 5 ms | 9 ms |

As passadas sofrem estado térmico e cache, portanto percentis entre linhas não
são uma ablação pareada. A conclusão robusta é a ordem de grandeza: ANN retirou
a varredura de dezenas de segundos; BM25 passou a dominar o caminho.

### Guarda de qualidade do ANN

`eval.ann` calcula uma referência flat com `bypass_vector_index` e mede recall@20
por ID para as mesmas consultas. O dourado de escala disponível tem 10 perguntas,
não as 100 pedidas pelo dossiê; por isso este resultado permite o padrão local,
mas **não encerra o pacote**.

- `nprobes=256`, sem refino: recall médio 0,060;
- `nprobes=256`, refino 100×: recall médio 0,900;
- `nprobes=256`, refino 500× (10 mil candidatos em k=20): recall médio **0,980**,
  pior consulta 0,900, p95 denso isolado 288 ms.

O corpus é deliberadamente adversarial para recall por ID: o milhão nasceu de
apenas **18 vetores-semente**, cada qual replicado ~55 mil vezes com ruído e ID
novo. Mesmo assim a porta é estrita; réplica semanticamente equivalente não foi
contada como acerto. A meta de qualidade (≥0,95) passa, a de latência densa
(<150 ms) ainda não.

### Higiene FTS5

`Store` agora dimensiona `cache_size` e `mmap_size` pela RAM livre; registros
novos nascem com vacuum incremental. Ao fim de uma passada global consistente,
o indexador consolida os segmentos FTS e recupera páginas incrementalmente
quando o banco permite. No registro antigo do milhão, `optimize` levou 3,7 s e
o p95 do BM25 foi de 2 011 para 1 708 ms nesta sequência. A meta de 100 ms
reprova. A alternativa `ORDER BY rank` também foi medida de forma pareada e
refutada: média de 1 592 ms contra 1 279 ms do `bm25()` explícito; não entrou.

O tamanho de transação também foi auditado: o inflador escreve **8 192 chunks
por commit**, dentro do alvo de 5–10 mil. O indexador real continua confirmando
por documento, contrato de retomada que limita a perda após queda a um arquivo;
agrupar documentos só para perseguir o número do checklist pioraria esse limite.

### Poda pelo piso de IDF — primeiro ataque ao BM25

Depois do merge do ANN, a forma da consulta explicou a cauda lexical. O OR das
perguntas fazia termos presentes em quase todo o índice levarem centenas de
milhares de linhas até o `bm25()`. O próprio FTS5 dá IDF `1e-6` a uma frase que
aparece em pelo menos metade das linhas: ela custa a varredura e quase não vota.

A busca agora consulta o `fts5vocab` — uma visão virtual dos postings, sem cópia
nem reconstrução — e tira do MATCH somente os termos que já caíram nesse piso.
Identificadores com hífen, ponto, barra ou sublinhado nunca são podados; consulta
formada só por termos ubíquos conserva o OR original. A hidratação do `id` também
foi movida da junção de todos os matches para a projeção do top-200. O braço de
ablação continua reproduzível por `eval.rodar --sem-poda-ubiquos`.

Medição pareada do componente, 10 perguntas no índice R9.3 de 1 milhão, alternando
a ordem dos braços para repartir cache e estado térmico:

| Consulta lexical | média | p50 | p95 |
|---|---:|---:|---:|
| OR integral | 1 049 ms | 1 098 ms | 1 438 ms |
| poda pelo piso de IDF | **734 ms** | **675 ms** | **1 101 ms** |

Na passada entregue (`eval.latencia`, n=10, uma rodada), o BM25 ficou em
**1 327 ms p95** e `search` em **1 805 ms p95**. A referência imediatamente
anterior, após `FTS5 optimize`, era 1 708 ms e 2 379 ms respectivamente. Não é
ablação pareada entre datas, mas concorda com a redução de 23,5% do microbenchmark.

A guarda de ranking foi medida antes da adoção. BM25 puro ficou idêntico nos dois
dourados: sintético (n=10, MRR 1,000, nDCG@5 1,000, 4/4 armadilhas) e empresas
(n=13 no escopo, MRR 0,231, nDCG@5 0,160). No índice inflado, os 200 IDs das dez
consultas também ficaram iguais. Uma stoplist PT/EN fixa foi tentada e **refutada**:
neutra no sintético, derrubou o MRR lexical de empresas de 0,231 para 0,179. Ela
não entrou; a poda adotada depende da estatística da base, não do idioma.

A antiga meta lexical de 100 ms ficaria 13,3× abaixo desta passada. A mudança
remove trabalho que o score já declarava irrelevante; chegar àquela ordem de
grandeza exigiria mudar a semântica da consulta ou a classe do motor, não mais
higiene de SQLite.

## Reavaliação arquitetural — 04/09/2026

**Decisão: retirar as metas isoladas de 100 ms do BM25 e 150 ms do ANN e fechar
R4.1/R4.2.** A porta que interessa passa a ser `search` completo, sem rerank:
**p95 <4 s** no cenário de referência de 4 núcleos, 8 GB e índice de estresse
com 1M+ trechos. O piso de regressão por máquina continua separado.

Não é afrouxar uma meta até ela passar. É corrigir três erros de arquitetura da
meta original:

1. **O requisito é da experiência, não do componente.** O consumidor é uma tool
   MCP chamada por um agente, não uma caixa de busca que precisa atualizar a
   cada tecla. Alguns segundos são perceptíveis, mas não impedem a tarefa; 100 ms
   no BM25 nunca foi pedido nem validado com usuário.
2. **A conta não fechava.** Em três rodadas no caminho entregue, `search` ficou
   em **3 404 ms p95**, com **1 301 ms** no BM25 e **2 181 ms** no denso. Mesmo
   um BM25 instantâneo não cumpriria os antigos 300 ms do total. Subportas
   independentes otimizavam peças sem garantir o sistema.
3. **O milhão inflado é canário, não retrato do produto.** Ele replica apenas 18
   vetores-semente cerca de 55 mil vezes cada. Isso é útil para expor caudas e
   validar escala mecânica, mas super-representa termos ubíquos e empates. Não
   deve sozinho justificar uma migração de armazenamento.

Os 4 s são um **orçamento operacional provisório**, não uma verdade universal
de UX: 3 404 ms medidos mais cerca de 15% de margem. Ele impede que a experiência
volte às dezenas de segundos sem transformar um benchmark adversarial em plano
de produto. Quando houver corpus de 1M representativo ou telemetria de uso, o
valor deve ser reavaliado com esse instrumento.

### Consequências para a arquitetura e a fila

- O FTS5 permanece como sinal lexical exato e local. A poda estatística e a
  hidratação tardia ficam: reduziram custo sem mudar a qualidade medida.
- Tantivy ou outro motor só volta à pauta se o BM25 for gargalo em **5M+ trechos
  representativos**, se `search` romper 4 s de forma repetível, ou se fluxos
  reais mostrarem várias buscas sequenciais tornando esse custo cumulativo.
- Paralelizar denso e lexical é uma opção futura, não uma correção óbvia: ambos
  disputam CPU, RAM e I/O. Só entra com medição fim a fim e guarda de qualidade.
- `R3.3` (INT8) continua por capacidade de RAM e escala de 5–20M vetores. Ele não
  é necessário para declarar R4.1/R4.2 prontos nem para “fechar” 100 ms.
- O próximo pacote segue a fila do produto. Não há outro PR de micro-otimização
  do BM25 enquanto nenhum dos gatilhos acima ocorrer.
