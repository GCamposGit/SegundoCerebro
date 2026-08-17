# Truncagem silenciosa — 80,7% do texto indexado nunca virou vetor

13/08/2026. Encontrado ao retomar a indexação com `e5-large` depois de o
computador hibernar: o mesmo XLSX que dá 23 chunks com o MiniLM estava dando
**3.277** com o e5. Diferença de tokenizador não explica duas ordens de
grandeza.

## Os dois defeitos, encadeados

**1. `contar_tokens()` saturava em vez de contar.** O tokenizador que o
`fastembed` expõe vem com truncagem ligada na janela do modelo, e
`encode()` devolve no máximo esse tanto de ids. Medido no mesmo texto de 4.380
caracteres:

| | janela do tokenizador | `contar_tokens()` | contagem real |
|---|---:|---:|---:|
| MiniLM | 128 | **128** | 840 |
| e5-large | 512 | **512** | 840 |

Dois modelos da mesma família XLM-R "contando" o mesmo texto e cada um devolvendo
exatamente a própria janela. A função existia para responder *"isto passa da
janela?"* — e era incapaz de dizer sim.

**2. `ModelSpec.max_tokens` assumia 512 para todo modelo.** O MiniLM declara 512
posições no `config.json` mas trunca em 128 no `tokenizer_config.json`, e é a
truncagem que vale. A janela real do
`paraphrase-multilingual-MiniLM-L12-v2` é **128 tokens**.

O encadeamento produz efeitos opostos nos dois modelos:

- **MiniLM**: `contar()` devolvia no máximo 128, o orçamento era 488, então
  `128 > 488` era sempre falso e `_respeitar_orcamento()` **nunca cortava**. O
  chunking passou a ser governado só por `max_chars`, e blocos marcados
  `never_split` (tabelas, planilhas) atravessaram inteiros — o maior chunk do
  índice tem **40.880 tokens**.
- **e5-large**: `contar()` devolvia 512, acima do orçamento de 488, então o corte
  disparava em *todo* bloco longo e a planilha virava uma linha por chunk. Daí os
  3.277.

## O tamanho do estrago no índice MiniLM

Amostra de 1.200 dos 7.214 chunks, contados com a truncagem desligada:

| Medida | Valor |
|---|---:|
| tokens por chunk, mediana | 196 |
| tokens por chunk, máximo | 40.880 |
| chunks acima da janela de 128 | **748 de 1.200 (62,3%)** |
| dos truncados, fração que chegou ao encoder (mediana) | **37%** |
| **tokens que viraram vetor, no agregado** | **19,3%** |

Mais de **quatro quintos** do texto indexado foi para o FTS e nunca chegou ao
vetor. O ranqueador denso vinha julgando cada documento pelo começo de cada
chunk — e como o chunk começa com o prefixo contextual (`nome do arquivo >
headings`), boa parte da janela de 128 é cabeçalho, não conteúdo.

## O que isso invalida, e o que não

**Não invalida** — o FTS5 indexa o texto completo do chunk, então nada que passe
por ele foi afetado:

- baseline por nome de arquivo, em todas as condições
- braço `bm25`, puro ou fundido
- o critério de escopo, a igualdade de universo e as portas reescritas do ROADMAP
- as leituras 1 a 3 de `ablacao-f1.md`: a média empata com o baseline, o bm25
  puro ganha nas armadilhas por 5 a 3, e a fusão com o nome desfaz esse ganho

**Invalida** — tudo que depende do vetor denso:

- `denso puro recall@1 = 0,333` e todos os números da coluna densa
- a leitura 4 de `ablacao-f1.md` ("denso e bm25 são complementares"), que pode
  estar certa ou errada: foi medida sobre vetores de um terço do texto
- a conclusão da varredura de que **o peso ótimo do denso é zero**. Um
  ranqueador que lê 19% do acervo perder de um que lê 100% não é evidência sobre
  embeddings; é evidência sobre o defeito
- a hipótese "MiniLM é modelo de paráfrase, não de recuperação" como explicação
  do desempenho denso. Continua verdadeira como fato sobre o treino do modelo, e
  deixa de ser necessária para explicar o número

O índice `index-e5` construído durante a madrugada (219 documentos, 9.098 chunks)
tem o chunking do defeito 1 na direção oposta e **não serve**.

## O terceiro defeito, que só apareceu depois

Com a contagem consertada, um teste de fumaça antes de gastar 4,5 h de máquina
mostrou a mesma planilha ainda dando 3.818 chunks — mais que os 3.277 de antes —
e **365 deles acima do orçamento**, o maior com 4.386 tokens para um limite de
488. Dois problemas independentes, escondidos atrás do primeiro:

**3a. `_cortar_por_linha` não garantia o que prometia.** Ele agrupa linhas de
tabela repetindo o cabeçalho, e emite o grupo quando a próxima linha não cabe.
Mas quando **uma linha sozinha, com o cabeçalho, já passa** do orçamento, não há
agrupamento possível — e o pedaço era emitido assim mesmo. A garantia declarada
no docstring de `_respeitar_orcamento` ("nenhum pedaço excede a janela") era
falsa nesse caminho. Agora cai para corte por caractere, que sempre cabe.

**3b. O limiar de "despejo de dados" só olhava altura.** O parser de XLSX já
tinha a lógica certa e documentada — aba de despejo se **acha**, não se lê linha
por linha, então vira digesto de valores distintos — mas o gatilho era
`max_row > 5000`. A aba do arquivo real tem 4.279 linhas e **22 colunas**: 94 mil
células, abaixo do limiar de altura, acima de qualquer noção razoável de área. Foi
para o caminho de janelas e explodiu.

Pior: `max_row` e `max_column` em `read_only=True` vêm do elemento `<dimension>`
do XML e podem faltar. A área tem que ser conferida **depois** da leitura, com as
linhas na mão. Com o gatilho por área (20 mil células, ~4× a aba mediana do
acervo), a planilha caiu de **3.277 para 176 chunks**, com o digesto cobrindo
todas as linhas em vez de janelar as primeiras.

Vale notar o que 3a e 3b faziam juntos: o cabeçalho longo repetido ocupava ~40%
de cada vetor, então 3.277 chunks quase idênticos — uma hora e meia de e5-large
gasta num arquivo, para produzir vetores que competem entre si no ranqueamento.

## A correção

- `contar_tokens()` conta numa **cópia** do tokenizador com truncagem desligada.
  Desligar no objeto compartilhado consertaria a contagem e quebraria a
  inferência, porque o encoder passaria a receber sequências acima da janela.
- `max_tokens` passa a ser conferido no pacote de cada modelo, com o valor real:
  MiniLM 128, mpnet 512, e5-large 512.
- A estimativa de emergência (sem tokenizador acessível) usa 4 caracteres por
  token, abaixo dos 4,49 medidos em português, para errar cortando cedo em vez de
  estourar a janela em silêncio.
- `tests/test_embeddings.py`, marca `modelo`: carrega o encoder de verdade e
  afirma que a contagem **não satura**, que dois modelos irmãos contam o mesmo
  texto dentro de 20%, e que o que o chunker aprova o encoder lê inteiro.
- `_cortar_por_linha` cai para corte por caractere quando uma linha não cabe nem
  com o cabeçalho, e `tests/test_chunking.py` afirma o orçamento com prefixo
  contextual longo incluído — o acervo tem caminho de 293 caracteres, e o prefixo
  entra na conta.
- O digesto de XLSX passa a ser acionado por **altura ou área**, com a área
  medida nas linhas lidas em vez de no metadado. `tests/test_ingest.py` cobre os
  dois lados: aba larga vai para digesto, aba de conteúdo continua janelada.

## O modelo de referência mudou junto

`MODELO_PADRAO` era `minilm` e passou a `e5-large`, por critério de resultado de
longo prazo com o acervo crescendo. É o único treinado para **recuperação** no
catálogo do `fastembed` — prefixos assimétricos `query:` e `passage:`. MiniLM e
mpnet são modelos de paráfrase, treinados em similaridade simétrica entre frases;
escolher o mpnet por ser rápido repetiria o erro recém-diagnosticado com
contabilidade melhor.

O MiniLM fica registrado e inadequado a este acervo: janela de 128 dá orçamento
de 104 tokens, uns 470 caracteres. Chunk desse tamanho mudaria também o índice
lexical e levaria embora as medições de `bm25` que sobreviveram. O mpnet fica como
dublê rápido — mesma janela de 512, logo mesmo chunking, útil para validar
pipeline sem esperar horas, e sem servir de proxy de qualidade.

## A lição de método

O projeto tinha a regra certa — "nenhuma otimização de precisão sem número antes
e depois" — e ela não pegou isto, porque o número estava sendo produzido por um
caminho quebrado. Duas coisas faltavam:

1. **Nenhum teste carregava o modelo real.** Todos usavam `EmbedderFalso`, cujo
   `contar_tokens` funciona. O defeito vivia exatamente na fronteira que os
   dublês escondem. Daí a marca `modelo`.
2. **Um invariante nunca foi verificado de ponta a ponta**: o que o chunker
   aprova, o encoder lê inteiro. É uma propriedade de duas peças, e cada peça
   estava correta em relação à sua própria suposição.

Também vale registrar o sinal que apareceu antes e foi lido errado. O
`ARCHITECTURE.md` diz que "com limite de 2.500 caracteres o p90 batia exatamente
em 512 tokens". *Exatamente* 512 num p90 não é distribuição de texto — é
saturação. O dado estava na mesa em 11/08 e foi interpretado como coincidência
confirmatória.
