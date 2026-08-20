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

4. Medir. O `config.sintetico.toml` ainda aponta MiniLM (barato na CPU); o
   índice GPU é e5-large — o modelo tem que ir na linha de comando:

```bash
py -m eval.rodar --config config.sintetico.toml --base sintetico ^
  --indice index-sintetico-gpu --modelo e5-large --retriever hibrido
```

Referência medida **neste desktop** em 19/08/2026, `corpus=sintetico`, n=10:
recall@1 **0,850** / recall@10 **1,000**. Não é a condição C.

Se o notebook reindexar com MiniLM, os vetores deixam de ser comparáveis e o
experimento se perde.

## O que isto prova

Consultas no notebook sobre um índice que **não** foi embeddado lá. Se as
métricas caírem fora do ruído, o `model_id` ou a versão do fastembed divergiram
— não o hardware.
