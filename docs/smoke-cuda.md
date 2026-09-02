# Smoke CUDA — 19/08/2026

## F6-C — CPU é o padrão

Máquina sem NVIDIA **indexa**. CUDA é extra `[gpu]` e só entra com
`SEGUNDOCEREBRO_PROVIDER=cuda`. Vazio não deixa o runtime escolher a placa:
isso fazia um `pip install` com o wheel errado cair no CUDA em silêncio.

O smoke recusa, em português, o que esta placa não calcula:

- CUDA 13 nesta geração de placa (o `onnxruntime-gpu` ≥ 1.27)
- MiniLM quantizado (devolve NaN)
- driver 590+ nesta placa

Não menciona `sm_52`. Não põe `cuda` em `model_id`. `pip install -e .` sem o
extra é o caminho do leigo.

Comando, neste desktop, **pelo venv**:

```bash
.\.venv\Scripts\python.exe -m segundocerebro.index.smoke_cuda --embed
# padrão: e5-large. MiniLM quantizado devolve NaN neste hardware.
```

## O que não se mexeu

| | |
|---|---|
| Driver | **582.28** (antes e depois) |
| `python` no PATH | 3.11.9 |
| Toolkit NVIDIA de sistema | não instalado |
| `winget Nvidia.CUDA` | **não** — hoje é 13.3 |

Python 3.12.10 entrou ao lado, sem prepend no PATH. O `py` launcher passou a
apontar 3.12 por ser o mais novo; outros projetos que usam `python` continuam
no 3.11. Este repo usa `.venv`.

Disco C: 16,7 GB livres → 9,4 GB. Os pacotes nvidia-* ficam no `.venv`.

## Resultado que vale

`onnxruntime-gpu==1.18.0` + CUDA 11.8 + cuDNN 8.9.5, vendidos por pip.

```
session providers ['CUDAExecutionProvider', 'CPUExecutionProvider']
e5-large: 2 vetores, dim 1024, finitos
```

O MiniLM multilíngue do `fastembed` é **quantizado** (`onnx-Q`). No Maxwell o
forward passa sem exceção e devolve **NaN** — o smoke antigo olhava só a
dimensão e dava ok. `embed_passagens` agora recusa NaN.

`e5-large` usa `model.onnx` cheio: 11 documentos sintéticos, 18 chunks,
`model_id = e5-large:1024:fastembed0.8.0` (sem `cuda`). Hybrid no conjunto
sintético: recall@1 **0,850** / recall@10 **1,000** (n=10, `corpus=sintetico`
— não é a condição C).

Pipeline (19/08): parse em N threads. Com uma placa, embed+commit na
principal. Com duas, `EmbedFila` sobe um processo por GPU
(`CUDA_VISIBLE_DEVICES`) e a principal **não** carrega o encoder — e5-large
já enche uma 980 Ti de 6 GB.

```
.\.venv\Scripts\python.exe -m segundocerebro.index.smoke_cuda --pool
# pool ok: 2 GPUs, 2 vetores, dim 1024, finitos
# model_id = e5-large:1024:fastembed0.8.0  (sem cuda)
```

Indexador no sintético, duas placas, `--modelo e5-large` (o MiniLM da
`config.sintetico.toml` continua NaN no Maxwell — recusado, não gravado):
11 documentos, 18 chunks, **7 s**. O mesmo corpus na CPU (`PROVIDER=cpu`):
**23 s**. `eval.sintetico.comparar`: 18 chunks, cosseno mínimo **1,000000**,
`model_id` idêntico. Hardware não mudou o vetor.

Notebook, 20/08/2026: o mesmo índice consultado **sem reembeddar**; híbrido
recall@1 0,850 / recall@10 1,000 — idêntico ao desktop. F3.6 fechada no
sintético. Não é a condição C.

`Embedder` e o indexador recusam MiniLM com `PROVIDER=cuda` **antes** de
abrir a sessão: o forward pass sem exceção era o modo de falha pior.

ORT coloca ops de *shape* na CPU de propósito. A lista do `TextEmbedding` no
smoke é **só** `CUDAExecutionProvider`.

## O que falhou, e por quê

| Tentativa | O que aconteceu |
|-----------|-----------------|
| MiniLM quantizado (`onnx-Q`) no CUDA | Forward sem exceção, **todos** os vetores NaN. LanceDB recusa gravar. |
| ORT 1.26.0 + CUDA 12.8 + cuDNN 9 | EP aparece. `ReduceSum` morre: `CUDNN_STATUS_EXECUTION_FAILED_CUDART`. cuDNN 9 largou Maxwell. |
| ORT 1.18.0 + CUDA 12.9/cuDNN 8 pip | `LoadLibrary` 126 em `onnxruntime_providers_cuda.dll`. O 1.18.0 do PyPI é **CUDA 11**, não 12. |
| ORT ≥ 1.27 | CUDA 13. `sm_52` saiu. Nem tentar. |
| `nvidia-smi` “CUDA Version: 13.0” | Teto do **driver**, não toolkit instalado. Não autoriza instalar CUDA 13. |

## Pin

O extra `[gpu]` em `pyproject.toml` é a fonte: `onnxruntime-gpu==1.18.0` +
CUDA 11.8 / cuDNN 8, vendidos por pip. **Não** é o CUDA 13 (ORT ≥ 1.27) que
derrubou o indexador neste desktop. `tests/test_gpu_extra.py` recusa extra ou
overlay que aceite 1.19+ ou `cu12`/`cu13`.

`requirements-gpu.txt` é o overlay: os mesmos pins **e** `numpy<2`, porque o
extra do pip é união e o pin de CPU é `numpy>=2`. Depois de `pip install -e .`:

```
pip uninstall -y onnxruntime
pip install -r requirements-gpu.txt
```

`fastembed` puxa o `onnxruntime` CPU (1.29 em 19/08) e tapa o GPU.

Para indexar neste desktop:

```
set SEGUNDOCEREBRO_PROVIDER=cuda
```

`model_id` não muda.

## Display GPU e TDR (21/08/2026)

GPU 0 tem o monitor (`display_active=Enabled`); GPU 1 não. Embed nas duas
encheu ~4 GB em cada 980 Ti de 6 GB. O driver `nvlddmkm` entrou em TDR
(Event 4101, 37 vezes entre 04:54 e 06:01) e o Windows reiniciou à força
(Kernel-Power 41, desligamento inesperado às 06:00:51).

O pool agora **pula a placa com display** quando existe outra. Neste desktop
isso deixa o embed só na GPU 1, na thread principal. `model_id` não muda.

A retomada no logon é um `.cmd` na pasta de inicialização do usuário
(`SegundoCerebro-retomar-indexacao.cmd`). Sem esse arquivo, o reboot não
religa o indexador.

## Cross-encoder (20/08/2026)

`.\.venv\Scripts\python.exe -m segundocerebro.index.smoke_cuda --rerank`

`BAAI/bge-reranker-base` (`model.onnx`, não onnx-Q): 25 scores finitos no
Maxwell. CUDA 0,028 s / 10 pares e 0,062 s / 25 pares, contra 1,084 s e
2,280 s na CPU deste desktop (~37×). O query path ainda não usa isso —
ver [`docs/rerank-gpu.md`](rerank-gpu.md). Não liga o padrão.
