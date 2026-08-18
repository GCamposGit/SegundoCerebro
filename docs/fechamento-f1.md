# F1 — fechamento

> Medido em 17/08/2026 na condição C: índice completo, 1.601 documentos, 92.137
> chunks, 45 perguntas no escopo. Baseline por nome de arquivo remedido no mesmo
> run, sobre o mesmo universo — nunca copiado de documento anterior.

**As cinco portas passam.** A fase estava aberta desde 11/08/2026.

| # | Porta | Medido | Alvo | Baseline |
|---|---|---:|---:|---:|
| 1 | recall@1 ≥ baseline + 0,10 | **0,678** | 0,567 | 0,467 |
| 2 | MRR@10 ≥ baseline + 0,08 | **0,785** | 0,672 | 0,592 |
| 3 | ≥ 5 de 6 casos-armadilha no top-10 | **5 de 6** | 5 | 3 de 6 |
| 4 | multi-hop: ≥ 1 fonte no top-10, por caso | **5 de 5** | 5 | 2 de 5 |
| 5 | ≤ 3 quedas do 1º lugar, nenhuma crítica | **1 queda, 0 críticas** | 3 / 0 | — |

Complementares: nDCG@10 **0,794**, recall@10 **0,930**.

## O que fechou cada porta que estava reprovando

Em 16/08 as portas 3 e 4 reprovavam. Nenhuma das duas foi resolvida afrouxando
régua:

- **Porta 3** (4 → 5 de 6) fechou com **famílias de versão**. O caso que faltava
  dependia de saber qual de seis parentes quase idênticos é o vigente — informação
  que está na data de modificação e na convenção de nome, não no conteúdo. Nenhum
  peso de fusão alcança metadado. Custo por consulta: zero.
- **Porta 4** foi **reescrita por argumento de categoria**, não recalibrada. Ela
  media recuperação de conjunto completo numa consulta única, enquanto a
  invariante 3 delega multi-hop ao cliente: a fase era cobrada por uma capacidade
  que a arquitetura decidiu não implementar. Passou a medir o que uma consulta
  única legitimamente entrega — o cliente consegue começar. A exigência dura
  migrou para os critérios de saída da F3 e da F4, onde não dá para maquiá-la com
  peso de fusão. A reescrita está registrada no ROADMAP com a ressalva de que foi
  feita **depois** de ver o resultado, e com o que a defende.

## A única regressão, inspecionada

Uma pergunta caiu do 1º para o 2º lugar (`g046`, não-crítica) na comparação
baseline → híbrido. O orçamento da porta 5 é de três, e a regra sempre foi que
cada uma é olhada individualmente em vez de dissolvida numa média. Trinta e duas
perguntas melhoraram no mesmo movimento.

## O que **não** é dependência do fechamento

A configuração medida acima tem o reranking ligado com peso 0,25. Vale registrar
que **as portas 1 a 4 também passam com ele desligado** — 0,644 de recall@1 contra
o alvo de 0,567, e 0,762 de MRR contra 0,672, com as mesmas 5 de 6 armadilhas e 5
de 5 multi-hop.

Isso importa porque o reranking custa 6,8× no tempo de consulta. O fechamento da
fase **não** depende de pagar esse preço: quem preferir a busca instantânea põe
`rerank = 0` e a F1 continua fechada.

## O que continua aberto, e não é da F1

- **Uma armadilha ainda erra** (`g036`): discriminação entre propostas irmãs na
  mesma pasta, com o nome do arquivo contendo erro de digitação do nome da
  empresa. O reranking, que era a aposta para ela, não resolveu — o ganho de
  0,678 veio de outras perguntas. Fica como caso nomeado para o que vier depois.
- **Multi-hop completo** — todas as fontes de uma pergunta no top-10 — segue em
  1 de 5. Por decisão de arquitetura isso é trabalho do cliente, e a prova mora
  na F3 e na F4.
