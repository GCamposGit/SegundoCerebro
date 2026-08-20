"""Smoke test da F3.6 — o Maxwell carrega onnxruntime-gpu?

    py -m segundocerebro.index.smoke_cuda

ROADMAP: descobrir que o runtime não roda nas 980 Ti *depois* de escrever o
pipeline é a ordem errada. Este módulo não desenha pipeline. Ele diz sim ou não.

`sm_52` saiu do CUDA 13. Neste desktop o pin que funciona é ORT 1.18.0 +
CUDA 11.8 + cuDNN 8 (`requirements-gpu.txt`). Driver 582.x: não subir para 590+.

Não grava nada no índice. Não altera `model_id`. Hardware não entra no vetor.
"""

from __future__ import annotations

import argparse
import os

from ..logger import get_logger

log = get_logger("index.smoke_cuda")

COMPUTE_MAXWELL = "5.2"
TEXTOS = (
    "passage: Política vigente da Várzea Clara Energia sobre inteligência artificial.",
    "query: Qual a versão vigente da política de IA?",
)

# Espelha retrieve.rerank.MODELO_PADRAO e CANDIDATOS_PARA_RERANK. Não importar
# retrieve daqui: o smoke é da camada index, e o wiring CUDA no query path é
# outro PR (arquivo do notebook).
MODELO_RERANK = "BAAI/bge-reranker-base"
CANDIDATOS_RERANK = 25
CANDIDATOS_CONFIG = 10
"""10 é o default de config.Busca.rerank_candidatos; 25 é o do módulo."""

CONSULTA_RERANK = "Qual é a versão vigente da política de IA da Várzea Clara Energia?"
PASSAGENS_RERANK = (
    "Politica de Inteligencia Artificial revisada GC > Vigência\n---\n"
    "A versão vigente é a revisada por GC em março de 2026, que substitui a v6.",
    "Politica de Inteligencia Artificial v6 > Histórico\n---\n"
    "A v6 foi a minuta interna; não é o texto que vale para o conselho.",
    "Proposta Aurora Tecnica implantacao IA > Escopo\n---\n"
    "A Aurora propõe implantar o copiloto de contratos em 90 dias.",
    "Proposta Boreal Servicos implantacao IA > Escopo\n---\n"
    "A Boreal descreve serviços de implantação de IA generativa no mesmo edital.",
    "Deck governanca IA v2 > Decisão\n---\n"
    "O conselho aprovou o comitê de IA e pediu a política vigente como anexo.",
    "Ata 2026-03-12 mudanca escopo > Deliberações\n---\n"
    "A ata registra a troca de escopo do projeto Lagoa Norte, sem falar de IA.",
    "Orcamento projeto Lagoa Norte > Planilha\n---\n"
    "Valores de sondagem e licença ambiental; não menciona política de IA.",
    "CT-VCE-2024-0142 Servicos consultoria > Cláusula 4\n---\n"
    "O contrato de consultoria cobre licenciamento, não software de IA.",
    "Nota licenciamento faixa norte > Resumo\n---\n"
    "Pendência de licença prévia na faixa norte do reservatório.",
    "Ata 2026-04-02 riscos ambientais > Riscos\n---\n"
    "Risco de embargo na faixa norte; ação: protocolar a licença até maio.",
)


def _gpus() -> list[dict[str, str]]:
    try:
        import subprocess

        bruto = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,compute_cap,memory.total",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if bruto.returncode != 0:
        return []
    saida = []
    for linha in bruto.stdout.splitlines():
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) >= 3:
            saida.append(
                {
                    "name": partes[0],
                    "driver": partes[1],
                    "compute": partes[2],
                    "memoria": partes[3] if len(partes) > 3 else "",
                }
            )
    return saida


def _providers() -> list[str]:
    from .cuda_runtime import preparar

    preparar()
    import onnxruntime as ort

    debug = getattr(ort, "print_debug_info", None)
    if callable(debug):
        try:
            debug()
        except Exception:  # noqa: BLE001
            pass
    return list(ort.get_available_providers())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.index.smoke_cuda")
    parser.add_argument("--embed", action="store_true", help="tenta embeddar dois textos no GPU")
    parser.add_argument(
        "--pool",
        action="store_true",
        help="sobe um processo por GPU e embedda em paralelo — prova as duas placas, "
        "sem gravar índice",
    )
    parser.add_argument(
        "--modelo",
        default="intfloat/multilingual-e5-large",
        help="nome no catálogo fastembed. MiniLM quantizado (onnx-Q) devolve NaN no Maxwell; "
        "e5-large (model.onnx) é o que vale neste desktop",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="carrega o cross-encoder da F2 (BAAI/bge-reranker-base) no GPU e mede "
        "latência CUDA vs CPU para 10 e 25 pares. Não altera retrieve/rerank.py, "
        "não grava índice, não muda peso. model.onnx cheio (não onnx-Q)",
    )
    parser.add_argument(
        "--modelo-rerank",
        default=MODELO_RERANK,
        dest="modelo_rerank",
        help="nome no catálogo TextCrossEncoder. Padrão: o mesmo da F2",
    )
    args = parser.parse_args(argv)

    gpus = _gpus()
    if not gpus:
        log.error("nvidia-smi não listou GPU — sem placa visível não há F3.6")
        return 2
    for g in gpus:
        log.info("gpu %s | driver %s | compute %s | %s", g["name"], g["driver"], g["compute"], g["memoria"])
        if g["compute"] == COMPUTE_MAXWELL and g["driver"].split(".", 1)[0] >= "590":
            log.warning("driver %s pode ter largado Maxwell — o ramo 580 é o último anunciado", g["driver"])

    try:
        providers = _providers()
    except ImportError:
        log.error(
            "onnxruntime não importou. Instale um build CUDA 11.8/12.x "
            "(não CUDA 13) — ver ARCHITECTURE.md §4"
        )
        return 2

    log.info("providers: %s", providers)
    if "CUDAExecutionProvider" not in providers:
        log.error("CUDAExecutionProvider ausente — este pacote é CPU. F3.6 para aqui.")
        return 2

    if args.pool:
        return _smoke_pool()

    if args.rerank:
        return _smoke_rerank(args.modelo_rerank)

    if not args.embed:
        log.info("runtime CUDA visível. Rode de novo com --embed, --pool ou --rerank")
        return 0

    try:
        from fastembed import TextEmbedding

        # Sem CPU na lista: fallback silencioso para CPU era um falso "ok".
        modelo = TextEmbedding(
            args.modelo,
            cache_dir="models",
            providers=["CUDAExecutionProvider"],
        )
        vetores = list(modelo.embed(list(TEXTOS)))
    except Exception as erro:  # noqa: BLE001 — o ponto do smoke é o erro cru
        log.error("forward pass no GPU falhou: %s", erro)
        return 3

    import numpy as np

    arr = [np.asarray(v, dtype=np.float32) for v in vetores]
    if any(not np.isfinite(v).all() for v in arr):
        log.error(
            "forward pass devolveu NaN/Inf — o EP carregou, mas o Maxwell não "
            "calcula este ONNX. MiniLM quantizado (onnx-Q) faz isso no Maxwell; "
            "use --modelo intfloat/multilingual-e5-large."
        )
        return 3
    log.info("forward pass ok: %d vetores, dim %d, finitos", len(arr), len(arr[0]))
    return 0


def passagens_rerank(n: int) -> list[str]:
    """n trechos sintéticos (VCE). Cíclicos se n > o estoque."""
    if n < 1:
        raise ValueError("n tem que ser ≥ 1")
    estoque = list(PASSAGENS_RERANK)
    return [estoque[i % len(estoque)] for i in range(n)]


def _cronometrar_rerank(encoder, consulta: str, docs: list[str], repeticoes: int = 5) -> float:
    """Mediana de parede, depois de o caller ter feito o warmup."""
    import statistics
    import time

    amostras: list[float] = []
    for _ in range(repeticoes):
        t0 = time.perf_counter()
        list(encoder.rerank(consulta, docs))
        amostras.append(time.perf_counter() - t0)
    return statistics.median(amostras)


def _carregar_rerank(modelo: str, providers: list[str]):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from .cuda_runtime import preparar

    preparar()
    return TextCrossEncoder(modelo, cache_dir="models", providers=providers, threads=10)


def _scores_finitos(scores: list[float]) -> bool:
    import math

    return bool(scores) and all(math.isfinite(s) for s in scores)


def _smoke_rerank(modelo: str) -> int:
    """Cross-encoder no Maxwell. Latência, não qualidade. Não toca retrieve/."""
    import gc
    import time

    docs10 = passagens_rerank(CANDIDATOS_CONFIG)
    docs25 = passagens_rerank(CANDIDATOS_RERANK)

    log.info("carregando reranker %s no CUDA (model.onnx, não onnx-Q)", modelo)
    t0 = time.perf_counter()
    try:
        enc_cuda = _carregar_rerank(modelo, ["CUDAExecutionProvider"])
    except Exception as erro:  # noqa: BLE001
        log.error("carregar reranker no GPU falhou: %s", erro)
        return 3
    log.info("reranker CUDA pronto em %.1fs", time.perf_counter() - t0)

    try:
        scores = list(enc_cuda.rerank(CONSULTA_RERANK, docs25))
    except Exception as erro:  # noqa: BLE001
        log.error("forward pass do reranker no GPU falhou: %s", erro)
        return 3
    if not _scores_finitos(scores):
        log.error(
            "reranker no GPU devolveu NaN/Inf — o EP carregou, mas o Maxwell "
            "não calcula este ONNX. Não ligar CUDA no query path."
        )
        return 3
    log.info("forward CUDA ok: %d scores finitos, min=%.3f max=%.3f", len(scores), min(scores), max(scores))

    med10_cuda = _cronometrar_rerank(enc_cuda, CONSULTA_RERANK, docs10)
    med25_cuda = _cronometrar_rerank(enc_cuda, CONSULTA_RERANK, docs25)
    log.info("CUDA mediana: %d pares %.3fs | %d pares %.3fs", CANDIDATOS_CONFIG, med10_cuda, CANDIDATOS_RERANK, med25_cuda)

    del enc_cuda
    gc.collect()

    log.info("carregando o mesmo reranker na CPU (CPUExecutionProvider)")
    t0 = time.perf_counter()
    try:
        enc_cpu = _carregar_rerank(modelo, ["CPUExecutionProvider"])
    except Exception as erro:  # noqa: BLE001
        log.error("carregar reranker na CPU falhou: %s", erro)
        return 3
    log.info("reranker CPU pronto em %.1fs", time.perf_counter() - t0)
    try:
        scores_cpu = list(enc_cpu.rerank(CONSULTA_RERANK, docs25))
    except Exception as erro:  # noqa: BLE001
        log.error("forward pass do reranker na CPU falhou: %s", erro)
        return 3
    if not _scores_finitos(scores_cpu):
        log.error("reranker na CPU devolveu NaN/Inf")
        return 3

    med10_cpu = _cronometrar_rerank(enc_cpu, CONSULTA_RERANK, docs10)
    med25_cpu = _cronometrar_rerank(enc_cpu, CONSULTA_RERANK, docs25)
    log.info("CPU mediana: %d pares %.3fs | %d pares %.3fs", CANDIDATOS_CONFIG, med10_cpu, CANDIDATOS_RERANK, med25_cpu)

    if med10_cuda > 0:
        log.info("razão CPU/CUDA @%d: %.1f×", CANDIDATOS_CONFIG, med10_cpu / med10_cuda)
    if med25_cuda > 0:
        log.info("razão CPU/CUDA @%d: %.1f×", CANDIDATOS_RERANK, med25_cpu / med25_cuda)
    log.info(
        "query path ainda é CPU: retrieve/rerank.py não passa providers. "
        "Isto mede o teto do hardware, não o tempo da consulta hoje."
    )
    return 0


def _smoke_pool() -> int:
    """Load one encoder per card. Main process must stay empty of ONNX."""
    from pathlib import Path

    import numpy as np

    from .gpu_pool import EmbedFila, contar_gpus

    n = contar_gpus()
    if n < 2:
        log.error("pool precisa de ≥2 GPUs visíveis (nvidia-smi viu %d)", n)
        return 2
    os.environ["SEGUNDOCEREBRO_PROVIDER"] = "cuda"
    fila = EmbedFila(n, modelo="e5-large", cache=Path("models"))
    try:
        jobs = [fila.submit([TEXTOS[i % len(TEXTOS)]]) for i in range(n)]
        vistos: dict[int, np.ndarray] = {}
        for _ in jobs:
            got = fila.receber()
            if got is None:
                log.error("pool: worker não respondeu")
                return 3
            jid, vetores = got
            if any(not np.isfinite(v).all() for v in vetores):
                log.error("pool: vetor NaN/Inf no job %s", jid)
                return 3
            vistos[jid] = vetores[0]
        if set(vistos) != set(jobs):
            log.error("pool: jobs %s, respostas %s", jobs, list(vistos))
            return 3
        log.info(
            "pool ok: %d GPUs, %d vetores, dim %d, finitos",
            n,
            len(vistos),
            len(next(iter(vistos.values()))),
        )
    except Exception as erro:  # noqa: BLE001
        log.error("pool falhou: %s", erro)
        return 3
    finally:
        fila.fechar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
