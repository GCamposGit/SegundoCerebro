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

    if not args.embed:
        log.info("runtime CUDA visível. Rode de novo com --embed ou --pool")
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
