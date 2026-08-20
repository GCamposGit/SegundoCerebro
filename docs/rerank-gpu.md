# Cross-encoder nas 980 Ti — 20/08/2026

Latência, não qualidade. `corpus=sintetico` (trechos da VCE). **Não é a
condição C.** Não muda peso, não liga o rerank por padrão, não altera
`retrieve/rerank.py`.

```bash
.\.venv\Scripts\python.exe -m segundocerebro.index.smoke_cuda --rerank
```

## O que se mediu

O mesmo modelo da F2, `BAAI/bge-reranker-base`, `onnx/model.onnx` (cheio, não
quantizado). 10 pares = default de `rerank_candidatos` no `config`; 25 = o
default do módulo. Mediana de 5 passadas depois do warmup. Uma 980 Ti,
driver 582.28, ORT 1.18.0 + CUDA 11.8 + cuDNN 8.

| | 10 pares | 25 pares |
|---|---:|---:|
| CUDA | **0,028 s** | **0,062 s** |
| CPU neste desktop | 1,084 s | 2,280 s |
| CPU ÷ CUDA | 38,7× | 36,8× |

Scores finitos (min −10,2, max −2,9). Maxwell calcula este ONNX. MiniLM
quantizado do denso continua NaN; o reranker não é onnx-Q.

No notebook a consulta híbrida ia de 0,92 s para 6,28 s com rerank 0,25
(`docs/ablacao-rerank.md`, condição C, CPU 15 W). Aqui o trecho do
cross-encoder cabe em dezenas de milissegundos: a conta de 6,8× **inverte
neste hardware**, como o ROADMAP previa. Continua vetado ligar o padrão sem
o notebook medir no conjunto corporativo.

## O que isto não muda

O caminho de consulta ainda é CPU. `Reranker._carregar` não passa
`providers`. Este smoke prova o teto do hardware; o wiring é
`retrieve/rerank.py`, arquivo do notebook (tabela da seção 1 de
`docs/colaboracao.md`). Sem esse PR, `rerank = 0.25` numa base deste
desktop continua lento.

`model_id` do denso não muda. O reranker não entra no vetor.

## Download

A primeira carga puxa ~1 GB para `models/` (junction em `E:\SegundoCerebro\models`).
No Windows sem Developer Mode o HuggingFace tenta criar symlink, leva
`WinError 1314`, e o fastembed cai no fallback — a segunda tentativa
funcionou. Não é falha do Maxwell.
