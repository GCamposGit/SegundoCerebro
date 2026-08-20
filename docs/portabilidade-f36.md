# Portabilidade F3.6 — índice sintético do desktop para o notebook

Princípio: **hardware muda velocidade, nunca conteúdo.** Um índice feito nas
980 Ti com `e5-large` responde no notebook sem reembeddar.

O acervo é o sintético (Várzea Clara Energia). **Não** copiar `index-empresas`
nem o índice corporativo.

## O que viaja

Pasta `index-sintetico-gpu/` (SQLite + LanceDB). `model_id` gravado:

```
e5-large:1024:fastembed0.8.0
```

Sem `cuda` no id. O notebook precisa da **mesma** versão do `fastembed` (0.8.0).

Pacote gerado neste desktop: `E:\SegundoCerebro\portabilidade-f36\`.

## No notebook

1. Puxar a branch / o `main` com o corpus em `eval/sintetico/`.
2. Copiar `index-sintetico-gpu/` para a raiz do clone.
3. Conferir **sem** carregar o encoder:

```bash
py -m eval.sintetico.verificar --indice index-sintetico-gpu
```

4. Se o notebook também indexar o sintético em CPU (`--modelo e5-large`),
   conferir os vetores:

```bash
py -m eval.sintetico.comparar --a index-sintetico-gpu --b index-sintetico-cpu
```

5. Medir. O `config.sintetico.toml` ainda aponta MiniLM (barato na CPU); o
   índice GPU é e5-large — o modelo tem que ir na linha de comando:

```bash
py -m eval.rodar --config config.sintetico.toml --base sintetico ^
  --indice index-sintetico-gpu --modelo e5-large --retriever hibrido
```

Referência medida **neste desktop** em 19/08/2026, `corpus=sintetico`, n=10:
recall@1 **0,850** / recall@10 **1,000**. Não é a condição C.

Se o notebook reindexar com MiniLM, os vetores deixam de ser comparáveis e o
experimento se perde.

## Comparar dois índices (critério da F3.6)

Mesmo `model_id`, mesmos ids de chunk, cosseno **> 0,9999**. Não carrega o
encoder:

```bash
py -m eval.sintetico.comparar --a index-sintetico-gpu --b index-sintetico-cpu
```

Medido neste desktop em 20/08/2026, e5-large, 11 documentos / 18 chunks:

| | tempo ativo | model_id |
|---|---:|---|
| duas 980 Ti | **7 s** | `e5-large:1024:fastembed0.8.0` |
| CPU (`PROVIDER=cpu`) | **23 s** | o mesmo |

18 chunks em comum, zero só de um lado, **cosseno mínimo 1,000000**. Hardware
não mudou o vetor. O tempo inclui carregar o encoder — em corpus grande a
diferença de vazão é a que a semente GPU (fator 28, base empresas: 637 s
reais contra 5–11 h de semente CPU) descreve.

Se o notebook rebuildar o sintético em CPU com `--modelo e5-large`, o
`comparar` contra o índice copiado daqui tem que passar o mesmo limiar. Sem
`--modelo e5-large` o MiniLM do `config.sintetico.toml` gera outro espaço.

## O que isto prova

Consultas no notebook sobre um índice que **não** foi embeddado lá. Se as
métricas caírem fora do ruído, o `model_id` ou a versão do fastembed divergiram
— não o hardware.

## Fechamento — notebook, 20/08/2026

Os três itens da saída da F3.6 passaram no notebook, contra o índice copiado
daqui, **sem reembeddar**:

| Critério | Resultado |
|----------|-----------|
| Similaridade de vetor | 1,0000 (já medido no desktop, GPU vs. rebuild CPU) |
| Métricas do dourado | Idênticas: recall@1 0,850 / recall@10 1,000 nos dois lados |
| Consulta no notebook | `verificar.py` ok sem encoder; `eval.rodar --modelo e5-large` no índice das 980 Ti |

`corpus=sintetico`. Não é a condição C. O notebook limpou o índice pedido
emprestado depois da prova — a pasta continua gitignorada.
