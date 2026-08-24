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

| Operação | n por passada | p50 | p95 | porta de produto | distância (p95) |
|---|---:|---:|---:|---:|---:|
| `search` | 186 | 1 363 – 2 506 ms | **1 840 – 2 877 ms** | 300 ms | **6,1× a 9,6×** |
| `search+rerank` (10 cand.) | 62 | 10 119 ms | **11 331 ms** | 800 ms | **14,2×** |
| `read_note` | 186 | 0,3 – 0,4 ms | **0,9 – 2,8 ms** | 100 ms | passa por 36× ou mais |
| `neighbors` | 186 | 0,2 ms | **1,6 – 2,1 ms** | 100 ms | passa por 48× ou mais |

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

- **`R4.1` (ANN) e `R3.3` (INT8) ganham alvo e ordem de grandeza.** A busca densa
  é **exata e plana** — nenhum `create_index` no `store.py`, conferido no
  `ROADMAP.md`. A parte do orçamento que escala com o acervo é essa varredura, e
  o alvo do dossiê é 10× o índice de hoje. Sem mudar a classe do algoritmo, a
  porta de 300 ms não é alcançável por ajuste.
- **`R6.2` (rerank v2) tem uma meta impossível, e agora dá para dizer por quê.**
  O pacote pede "30 candidatos em menos de 500 ms em CPU de 4 núcleos". A 761 ms
  por par, 30 candidatos custam ~22,8 s — **46× a meta**. Não é ajuste: é a
  classe do cross-encoder neste hardware. `R6.2` tem de escolher entre GPU (a
  rota da F3.6) ou outra classe de reranqueador.
- **A próxima medição que falta é a decomposição de `search`.** Quanto dos 2,5 s
  é encoder, quanto é varredura densa, quanto é bm25 e nome. Sem ela, "ANN
  resolve" é hipótese. É a primeira coisa que `R4.1` deve medir.

## Reproduzir

```bash
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 1 --rerank
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3 --porta
```

O último sai com código 1 se um piso de regressão for rompido. `--porta` sem
`--maquina` é recusado: piso sem máquina não é porta, é número solto. Os
relatórios vão para `docs/metricas-f4-r93-latencia*.md`, gitignorados por padrão.
