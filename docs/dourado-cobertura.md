# O conjunto dourado cobria 18% do índice

24/08/2026. Setup notebook, acervo corporativo, **condição C**. Este documento é
sobre o *conjunto dourado*, não sobre um recuperador: o que ele alcança, o que
não alcança, e o que apareceu quando passou a alcançar.

Nenhum texto de pergunta e nenhum nome de arquivo do acervo entram aqui — isso
mora nos `docs/metricas-*.md`, que não vão para o Git.

## O número que mandou parar

Depois de `Meetings/` fechar, o índice tem **1.900 documentos alcançáveis pela
busca, em 30 pastas de topo**. As 51 perguntas do dourado apontavam para **63
fontes, todas na mesma pasta** — a subárvore de desenvolvimento da F0.

| | |
|---|---|
| Documentos alcançáveis | 1.900, em 30 pastas de topo |
| Fontes das 51 perguntas | 63, em **1** pasta |
| Cobertura | **18,2%** |

As duas maiores pastas do acervo — 25,8% e 20,4% dos documentos — não podiam
ganhar nenhuma pergunta. Só podiam competir como distrator.

Isso não é defeito de quem escreveu o dourado: na F0 o índice **era** a subárvore
de dev, e `docs/escala-f0.md` já media que escala sozinha move recall@1 em 16
pontos. O que aconteceu é que o índice cresceu seis vezes e o dourado ficou
parado. A consequência é assimétrica e silenciosa: **crescer o corpus só podia
piorar a métrica**, porque documento novo entra como distrator e nunca como
resposta. Foi exatamente o que se mediu quando `Meetings/` entrou — recall@5 caiu
0,039 sem que nada tivesse ficado pior.

Por isso a porta 3 (`F4-P`, "onde o bm25 se paga") **não** foi aberta: decidir
peso de ranqueador com quatro quintos do corpus só atrapalhando escolheria o
peso errado com número a favor.

## Método, para o número não medir o autor

Perguntas escritas a partir do que a busca devolve medem a busca contra si mesma.
O procedimento fecha essa porta, e vale para quem escrever as próximas:

1. **Escolher o documento antes da pergunta**, por enumeração — nunca por
   consulta. Aqui: as reuniões com mais conteúdo, espalhadas no calendário.
2. **Ler o texto já indexado**, não o arquivo em disco. É o que a busca vê, e
   dispensa abrir placeholder de nuvem.
3. **Escrever a pergunta a partir de um fato do texto**, na forma em que alguém
   perguntaria — sem reusar as palavras raras do documento.
4. **Conferir a fonte trecho por trecho**: para cada renderização candidata,
   procurar o fato. Só entra em `fontes` a que **contém** a resposta.
5. **Só então** rodar o eval.

O passo 4 é o que produziu o achado da seção seguinte, e ele não teria aparecido
de outra forma.

## As renderizações não são cópias do mesmo áudio

O levantamento de `Meetings/` dizia "três renderizações do mesmo áudio" e
`docs/ablacao-f4-meetings.md` propunha escolher uma por ordem de preferência
(`reconciled` > `enhanced` > `diarized` > `transcript`). **As duas coisas estão
erradas, e a medição diz por quê.**

Volume de texto por renderização, com carimbo de tempo e rótulo de falante
descontados, nas 144 reuniões:

| | |
|---|---|
| A que a ordem por nome escolheria | `reconciled` em 106 de 144 |
| A que de fato tem mais texto | `transcript` em **128** de 144; `reconciled` em 14 |
| Reuniões em que a preferida tem < 60% do texto da mais completa | **56 de 144** |

A conciliada costuma ter um terço do texto da verbatim. Mas **não é um resumo
dela**: é outra passada de transcrição, mais fiel. Das 11 perguntas novas,
**4 só são respondíveis pela conciliada** — o fato existe lá e não existe em
nenhuma das outras duas, porque o reconhecimento de fala verbatim o embaralhou.
As outras 7 são respondíveis pelas três.

Conclusão que fecha a questão: **nenhuma renderização pode ser descartada por
regra.** Descartar as verbatim perde cobertura; descartar a conciliada perde fato
que só existe nela. A regra de família continua valendo, mas o mecanismo é
**colapsar irmãs no ranking** — uma ocupa a vaga do top-k, as outras continuam no
índice — e não escolher uma por nome nem cortar na indexação. É o que
`retrieve/familias.py` já faz para versão.

Achado de brinde: em 4 reuniões a **mesma** renderização existe em duas cópias
com volumes diferentes, uma delas 70 vezes menor. Não é o caso que o `sha256`
pega, porque os bytes diferem.

## O que as 11 perguntas de reunião mediram

Índice com 2.156 documentos e 98.326 trechos. `hibrido`, sem reranking, com
glossário de teste.

| Grupo | n | recall@1 | recall@5 | recall@10 | recall@20 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| as 48 perguntas anteriores | 48 | 0,656 | 0,833 | 0,927 | — | 0,771 | 0,764 |
| **as 11 de reunião** | 11 | **0,091** | 0,636 | 0,818 | **1,000** | 0,287 | 0,325 |
| o conjunto no escopo | 59 | 0,551 | 0,797 | 0,907 | 0,955 | 0,680 | 0,682 |

**Transcrição de reunião é recuperável e mal ranqueada.** Zero perguntas sem
acerto no top 20 — a resposta está *sempre* lá — mas só 1 de 11 no primeiro
lugar. É problema de precisão, não de cobertura, e é a assinatura de irmãs
disputando as primeiras vagas.

E dentro do grupo, uma linha decide a fase seguinte:

| Tipo | n | recall@1 | MRR@10 |
|---|---:|---:|---:|
| `exato` (a resposta é um número dito na conversa) | 6 | **0,000** | 0,252 |
| `semantica` | 5 | 0,200 | 0,329 |

## O ranqueador de nome é uma troca por tipo de fonte, não um peso global

Hipótese imediata para o `0,000`: o nome do arquivo de transcrição carrega
assunto e data, e nada do que se disse dentro. Uma pergunta sobre um número dito
na conversa não tem sobreposição com o nome — mas um documento qualquer que tenha
a palavra no nome tem. Medido, desligando o ranqueador de nome:

| | recall@1 | recall@5 | recall@20 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| 11 de reunião, com nome | 0,091 | 0,636 | 1,000 | 0,287 | 0,325 |
| 11 de reunião, **sem** nome | **0,273** | **0,818** | 0,909 | **0,459** | **0,504** |
| as 59 no escopo, com nome | 0,551 | 0,797 | 0,955 | 0,680 | 0,682 |
| as 59 no escopo, **sem** nome | 0,534 | 0,831 | 0,938 | 0,668 | **0,693** |

Na reunião o nome **atrapalha** — MRR sobe 60% sem ele. No conjunto todo ele
continua se pagando em recall@1 e MRR, e é para isso que tem peso 0,5: no
documento de escritório o identificador **está** no nome.

Logo o peso certo do ranqueador de nome provavelmente **não é um número só**. É
peso por tipo de fonte, e essa opção não estava na mesa antes destas perguntas
existirem. Vai para a `F4-P` como braço a medir, com a ressalva honesta de que
`n = 11` é sinal, não decisão — o lote de perguntas do usuário na maior pasta é o
que confirma ou derruba.

## Office legado: não dá para medir neste acervo, e é a resposta

A `F4` registrava que faltava "número no dourado" para o Office legado. Faltava, e
medir **não é possível aqui** — o que também é um resultado:

- Dos 7 arquivos `.doc`/`.xls` repescados, 3 produziram texto.
- **Todos os 3 têm gêmeo moderno já indexado com o mesmo conteúdo**: dois `.xlsx`
  com a mesma fórmula e a mesma série numérica, e um `.pdf` da revisão seguinte
  do mesmo contrato, este com 28 trechos contra 3.
- Nenhum fato dos legados é **exclusivo** deles. Pergunta honesta não isola o
  parser: acertar o gêmeo é acertar.
- Pior: os 3 trechos do `.doc` **não são texto**. São bytes decodificados como
  caracteres largos — mojibake CJK, agora dentro do índice e do FTS. Não é
  extração fraca; é ruído indexado, a mesma classe do `.msg` de 343 trechos
  de 21/08.

> Achado para o dono de `ingest/parsers/ole_texto.py` (`docs/colaboracao.md` §1) —
> reportado, não corrigido. Dois pedidos: recusar a extração quando o texto não
> passar num teste de sanidade (proporção de caracteres fora do esperado), e
> subir a versão do parser quando isso entrar, para os 3 trechos saírem do índice
> na passada seguinte.

O valor do Office legado **em acervo de consultoria** segue de pé como
prioridade de produto. O que caiu foi a expectativa de medi-lo *neste* acervo:
aqui ele é redundante.

## O que fica aberto

- **O lote do usuário** na maior pasta (25,8% do índice, nenhuma pergunta hoje).
  É o que transforma o sinal de `n = 11` em decisão.
- **Multi-hop entre reunião e documento.** Segue em 1 de 5 e agora existe o
  material: a reunião cita o documento que a decisão registra.
- **A regra de família por renderização**, com o mecanismo corrigido — colapsar
  no ranking, não escolher por nome.
- **Peso do ranqueador de nome por tipo de fonte**, na `F4-P`.
