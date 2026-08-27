# A fatia que decidiria a `F4-P.1` tem n=0, e o relatório diria n=100

**Data:** 27/08/2026 · **Achado antes de medir**, não durante · **Base:** `e1`
(camada 2, corpus sintético, semente 42, `--n-por-fatia 100`) · **Índice:**
`index-e1`, 3.530 documentos registrados

A `F4-P.1` está declarada com hipótese, efeito mínimo e regra de encerramento:
Δ pareado de MRR@10 **≥ +0,05** com IC95 que não cruza zero na fatia `reunião` do
corpus sintético, **n≈100**, e *empate encerra o pacote com "hipótese refutada"*.

A fatia tem **n=0**. Auditando o índice antes de gastar a medição:

| grupo | docs candidatos (`n_chunks > 0`) | registrados | perguntas | **com fonte indexada** |
|---|---:|---:|---:|---:|
| escritório | 3.116 | 3.228 | 1.819 | 1.540 |
| email | 102 | 102 | 102 | 102 |
| **reunião** | **3** | 200 | **100** | **0** |

As 100 perguntas de reunião apontam para 100 arquivos `.vtt` em
`corpus/09. meetings/`, e **nenhum deles está no índice**:
`supported_extensions()` tem 17 extensões e `.vtt`, `.srt` e `.sbv` não estão
entre elas. Não existe parser de transcrição neste projeto.

Os 200 documentos "registrados" do grupo `reunião` são registro com `n_chunks = 0`
— e a lição já está no `CLAUDE.md`: *documento sem chunk é invisível até para o
ranqueador de nome*. Os 3 candidatos que sobram são arquivos de formato suportado
que caem no grupo pela **pasta**, não pela extensão.

## Por que isto seria um falso "hipótese refutada"

Se a medição declarada rodasse:

1. as 100 perguntas de `reunião` pontuam **zero nos dois braços** — a fonte
   esperada não está no índice, então nem `nome = 0,5` nem `nome = 0,0` a alcança;
2. o Δ pareado da fatia sai **0,000**, com IC que cruza zero;
3. o critério de encerramento declarado dispara: *"empate no Δ pareado encerra o
   pacote com 'hipótese refutada' no doc"*;
4. e o pacote fecharia **com aparência de rigor perfeito** — efeito mínimo
   declarado antes, uma medição, empate, encerra. Todas as regras cumpridas.

O que teria sido registrado como "o peso de nome por tipo de fonte não se paga" é
"o indexador não lê transcrição". São afirmações diferentes sobre coisas
diferentes, e a segunda não tem nada a ver com ranking.

**Não é a primeira vez, é a terceira.** A classe está no `CLAUDE.md`: *regra que
não casa com nada falha em silêncio, e o silêncio parece sucesso.* As duas
instâncias anteriores foram quatro `metricas-f2-*` commitados (20/08) e 3 h 22 min
de máquina com medição contaminada (26/08). Esta é a mais cara das três se
passasse, porque não produziria erro nenhum — produziria uma **conclusão**.

## O defeito de contrato por baixo

`retrieve/fonte.py` declara, em docstring: *"Legenda com marca de tempo é
transcrição por construção, sem olhar a pasta"* — e classifica `.vtt`/`.srt`/`.sbv`
como grupo `reunião`. `retrieve/hybrid.py` usa esse grupo para escolher o peso do
ranqueador de nome (`PESO_NOME_POR_GRUPO = {REUNIAO: 0.0}`).

Ou seja: **a régua nomeia um formato que o produto não ingere.** A regra de peso
existe para uma classe de documento que nunca pode ser candidata. É a mesma classe
do `F4-P.0` — "o eval mede um caminho e o cliente executa outro" — um nível acima,
e com o mesmo modo de falha: cada metade está certa sozinha, e nada falha.

Vale notar o contraste que fecha o argumento: `.msg`/`.eml` **estão** em
`supported_extensions()`, e por isso a fatia `email` mede 102 de 102. O mecanismo
não é errado; ele está adiantado em relação ao parser.

## A classe, e o que passa a pegá-la (regra 12)

O caso é `.vtt`. A classe:

> **Extensão citada por uma regra de ranking, ou de recorte de relatório, que o
> despachante de parsers não sabe ler, é regra sobre documento que nunca existe —
> e a fatia correspondente sai vazia sem erro.**

Entregue em `tests/test_fonte_contrato.py`, na suíte padrão: toda extensão citada
em `retrieve/fonte.py` tem de estar em `supported_extensions()` **ou** numa tabela
`LACUNAS_DECLARADAS` que nomeia o pacote que a fecha. E há um teste no sentido
inverso — quando o parser entrar, a entrada na tabela passa a **falhar**, para a
dívida não sobreviver ao próprio conserto e a fatia não continuar sendo tratada
como vazia depois de passar a medir.

Enquanto a extensão estiver na tabela, **nenhuma decisão de ranking pode ser
tomada sobre o grupo dela**: a fatia é vazia por construção e qualquer Δ sai zero.

## O que isto muda para quem instala amanhã

É produto, não laboratório. **`.vtt` e `.srt` são a saída nativa de todo gravador
de reunião** — Teams, Zoom, Meet. Um leigo que aponte a pasta onde as reuniões
dele são salvas tem hoje esses arquivos **silenciosamente ausentes** do índice: o
registro guarda o documento com zero chunk, a barra de progresso conta o arquivo,
e a busca nunca o devolve. Pela régua de prontidão, item 2, *falhar é aceitável;
travar ou mentir em silêncio, não* — e este é mentir em silêncio.

No nosso acervo corporativo o grupo `reunião` funciona porque as transcrições
estão em formato de escritório e caem no grupo pela **pasta** (`PASTAS_DE_REUNIAO`).
Foi isso que escondeu a lacuna: a camada 1 mede 11 perguntas de reunião com
recall@20 = 1,000, então nada indicava que o formato canônico não é lido.

## O pacote que desbloqueia — `F4-T`

Não é parte da `F4-P.1`: é pré-requisito dela, e é um pacote de formato, com dono
por arquivo.

| Campo | Valor |
|---|---|
| Serve base desconhecida | **sim, e diretamente.** Transcrição de reunião entra no índice no formato em que o gravador a salva, em vez de ser contada e não indexada |
| Hipótese | `.vtt`/`.srt` parseados como texto com marca de tempo removida entram no índice, e a fatia `reunião` da camada 2 passa de n=0 para n≈100 |
| Efeito mínimo | **binário, e não é MRR:** as 100 perguntas de `reunião` passam a ter fonte indexada, e `supported_extensions()` cresce de 17 para 19. Sem isso a `F4-P.1` não tem fatia |
| Orçamento | um parser, um teste de formato, sem grade. Não mexe em chunking nem em `[padrao]` |
| Encerramento | se `.vtt` entrar e a fatia continuar vazia, o defeito é outro e o pacote reabre com o número novo na mão |
| Classe | `tests/test_fonte_contrato.py` já está no lugar: quando o parser entrar, a `LACUNAS_DECLARADAS` falha e obriga a medir a fatia |

- **Toca:** `ingest/parsers/vtt.py` (novo), teste do formato, `LACUNAS_DECLARADAS`
- **Precisa combinar:** `ingest/parsers/__init__.py` (o despachante) é "um de cada
  vez", e o desktop pode tocá-lo no `F4-O.2` — parser não registrado é código
  morto, então o registro **não** entra sem acordo
- **Não toca:** `retrieve/*` (a classificação está certa), chunking, `[padrao]`

## A ordem que isto impõe

```
F4-T  parser de transcrição  ──►  F4-P.1  medição da camada 2  ──►  decisão de peso
```

A `F4-P.1` **não fecha antes do `F4-T`**, e o que estava pronto nela — o mecanismo,
a definição única de grupo, a base da camada 2 — continua válido e medido. O que
não existe é a fatia.
