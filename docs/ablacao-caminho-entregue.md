# O caminho que o cliente recebe, medido — 24/08/2026

O harness sempre mediu `BuscaHibrida.search`. A ferramenta `search` do servidor
MCP chama `BuscaHibrida.buscar_chunks` (`mcp/server.py:191`). **São dois
recuperadores diferentes**, e a diferença não é de embalagem: o `RanqueadorDeNome`
participa só do primeiro.

Este documento mede os dois lado a lado pela primeira vez. Instrumento em
`eval/entregue.py`, ligado por `--entregue`. **Aditivo, nunca substituto** — toda a
série F0 → F4 foi medida em `search`, e trocar o recuperador canônico apagaria a
comparabilidade entre fases, que é a razão de o harness existir.

```bash
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank --entregue \
    --glossario eval/glossario-teste.toml --out docs/metricas-caminho-entregue.md
```

Condição C, 59 perguntas no escopo, 2.156 documentos, 98.326 chunks, sem
reranking, glossário ligado.

## Como isto foi encontrado

Não por leitura de código, e sim por uma verificação de três consultas no índice
real, feita antes de começar o `F4-P`: **mudar `peso_nome` de 0,5 para 0 não altera
nada em `buscar_chunks`, e altera a ordem em `search` em todas.**

O peso do nome é **inerte em produção**, diga o que disser a configuração. Logo
todo número que o projeto tem sobre ele — a varredura de 13/08 que escolheu 0,5,
[`dourado-cobertura.md`](dourado-cobertura.md), a varredura do
[`C3.a`](ablacao-c3a-pesos-fts.md) — descreve um caminho que o cliente não executa.

E o painel herda a mesma cegueira: `painel/medir.py:79` também usa
`buscar_chunks`, então o controle de peso de nome não move o número que o próprio
painel exige antes de salvar (invariante 4).

O projeto já tinha declarado o princípio contrário, para famílias de versão, em
`docs/ablacao-familias.md`: *"ligado em `search` **e** em
`buscar_chunks`, para o que se mede ser o que se entrega — ligar só no primeiro
seria medir uma coisa e entregar outra."* Para o ranqueador de nome isso não foi
feito, e ninguém reparou **porque no agregado os dois caminhos medem parecido**.

## O agregado esconde a diferença, como sempre

| caminho | recall@1 | recall@3 | recall@5 | recall@10 | recall@20 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `search` — a série histórica | 0,551 | 0,729 | 0,797 | **0,907** | **0,955** | **0,680** | 0,682 |
| `buscar_chunks` — **o entregue** | 0,551 | **0,737** | **0,805** | 0,881 | 0,921 | 0,671 | **0,693** |

Empate em recall@1, o entregue ganha no topo (recall@3, recall@5, nDCG@5) e perde
na cauda (recall@10, recall@20) e 0,009 de MRR. Olhando só isto, a conclusão seria
"tanto faz, é dívida de instrumento" — e ela estaria errada em dois lugares.

## Onde estão as diferenças de verdade

| grupo / fatia | n | métrica | `search` | **entregue** | Δ |
|---|---:|---|---:|---:|---:|
| **reunião** | 11 | recall@1 | 0,091 | **0,273** | **+0,182** |
| | | MRR@10 | 0,287 | **0,452** | **+0,165** |
| | | nDCG@5 | 0,325 | **0,499** | **+0,174** |
| escritório | 46 | recall@1 | **0,641** | 0,620 | −0,021 |
| | | MRR@10 | **0,761** | 0,720 | −0,041 |
| mesma-língua | 44 | recall@5 | 0,852 | **0,898** | +0,046 |
| **cross-lingual** | 12 | MRR@10 | **0,496** | 0,447 | −0,049 |
| | | recall@10 | **0,875** | 0,750 | −0,125 |
| | | **recall@20** | **1,000** | **0,750** | **−0,250** |

**O caminho entregue é três vezes melhor nas perguntas de reunião** — porque ele é,
na prática, a configuração "sem ranqueador de nome" que `dourado-cobertura.md`
mediu. Aproximadamente, não identicamente: aquela medição deu recall@1 0,273 e MRR
0,459 no `search` com `nome = 0`, contra 0,273 e 0,452 aqui. A fusão no nível de
trecho não é a mesma coisa que zerar o peso, mas chega perto.

## A correção que isto obriga em `fatia-cross-lingual.md`

O achado de manchete daquele documento é:

> **recall@20 é 1.000 na fatia cross-lingual.** O documento certo é alcançado e
> **mal ordenado** — sintoma de ranqueador cego dentro da fusão, não de busca que
> não encontra.

**Isso vale em `search`, e não vale no caminho que o cliente recebe.** Ali o
recall@20 cross-lingual é **0,750**: três das doze perguntas cross-lingual não são
alcançadas de jeito nenhum no top-20. Para um quarto da fatia, no produto, é sim
busca que não encontra.

E a explicação é a mesma que o `C3.a` já tinha isolado por outro caminho: **o
ranqueador de nome é a ponte agnóstica a idioma.** Identificador, código, data e
nome próprio casam igual em PT e EN; o bm25 não casa `contrato` com `agreement`.
Tirar o nome da fusão — que é o que o caminho entregue faz por construção — tira a
ponte, e três perguntas somem do alcance.

Duas conclusões do projeto se encaixam aqui e uma se corrige:

- `C3.a` mediu que baixar `nome` derruba o MRR cross-lingual (0,496 → 0,475 →
  0,461). **Confirmado por outro caminho**, e mais forte do que parecia: no
  extremo, não é só ordem, é alcance.
- `C4.5` está certo sobre o recorte e **errado sobre o diagnóstico**, para o
  caminho entregue. "Alcançado e mal ordenado" é metade do problema, não o
  problema.

## O que isto faz com o `F4-P`

O pacote foi escrito como "peso de nome por tipo de fonte", com o teto de oráculo
de +0,032 calculado sobre `search`. **Aquele teto não descreve o produto.** Com as
duas colunas na mesa, a pergunta do `F4-P` fica bem posta pela primeira vez:

> O caminho entregue já tem o melhor número de reunião **de graça** (0,452 de MRR
> contra 0,287) e paga por isso com a ponte cross-lingual (recall@20 1,000 →
> 0,750) e com 0,041 de MRR em escritório. O peso de nome por tipo de fonte é
> exatamente o mecanismo que pega os dois: trazer o sinal de nome para o caminho
> de trecho **sem** deixá-lo votar em documento de reunião.

Ou seja, `F4-P` deixa de ser uma afinação e passa a ser a reconciliação dos dois
caminhos, com alvo declarado: **reunião ≥ 0,452 de MRR e cross-lingual voltando
para recall@20 = 1,000**, sem perder o recall@1 de 0,551.

Isso também explica por que o `0,3` do `fts_caminho` não foi aplicado: ele foi
medido em `search`, e precisa ser remedido no caminho entregue antes de virar
configuração. Configurar a partir de um número que descreve outro caminho de
código é o defeito que este documento existe para registrar.

## Detalhes do instrumento que valem guardar

- **O colapso trecho → documento é o mesmo que `search` faz por dentro**: o
  documento fica com a posição do seu melhor trecho. Qualquer outra regra mediria
  a regra, não o recuperador.
- **O fator de trechos é medido, não escolhido.** Pedir `k` trechos rende menos de
  `k` documentos, porque vários trechos são do mesmo arquivo. Com `k × 6`,
  **14 de 59** perguntas rendiam menos de 20 documentos (mínimo 1); com `k × 20`,
  1 de 59 (mínimo 16). As duas medições deram as mesmas cinco métricas até a
  terceira casa — porque o que a fome cortava entrava depois da 10ª posição —, mas
  isso é sorte deste acervo e não desenho. O fator fica em 20.
- **Um teste do próprio pacote passava por empate.** A primeira versão de
  `test_search_de_documento_sente_o_peso_do_nome` ligava o bm25, e num acervo de
  três arquivos a coluna `caminho` do FTS5 já promove o documento pelo nome — a
  dupla contagem do `C3.a` escondendo o efeito que o teste queria mostrar. Ele
  roda com o lexical desligado, e há um teste irmão provando que a inércia no
  caminho entregue **não** é empate produzido pela coluna: é ausência do
  ranqueador ali.

## O que este documento não decide

Não propõe mudar o que o servidor devolve. Ele torna mensurável o que já é
entregue, e é `F4-P` quem decide o que fazer com a diferença — com número dos dois
lados, que agora existem.
