"""One ONNX session per GPU — the Runtime will not split a session.

Used only when SEGUNDOCEREBRO_PROVIDER=cuda and nvidia-smi sees ≥2 cards.
The main process never loads the encoder in that case (VRAM: e5-large ≈ 5 GB
on a 6 GB 980 Ti). Token budget on the main thread is the spec window, not
the live tokenizer — same ChunkConfig.max_tokens, no silent CUDA load.

model_id is unchanged. Hardware does not enter the vector fingerprint.
"""

from __future__ import annotations

import os
import queue
import subprocess
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable

from ..logger import get_logger

log = get_logger("index.gpu_pool")

WorkerFn = Callable[[str, str, str, Any, Any], None]


def contar_gpus() -> int:
    try:
        bruto = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 0
    if bruto.returncode != 0:
        return 0
    return sum(1 for linha in bruto.stdout.splitlines() if linha.strip())


def _worker(device: str, modelo: str, cache: str, pedidos, respostas) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = device
    os.environ["SEGUNDOCEREBRO_PROVIDER"] = "cuda"
    from .cuda_runtime import preparar
    from .embeddings import Embedder

    preparar()
    embedder = Embedder(modelo, cache_dir=Path(cache), lazy=False)
    log.info("embed worker GPU visível %s | %s", device, embedder.model_id)
    while True:
        job = pedidos.get()
        if job is None:
            return
        jid, textos, lote = job
        try:
            vetores = embedder.embed_passagens(textos, batch_size=lote)
            respostas.put((jid, [v.tolist() for v in vetores], None))
        except Exception as erro:  # noqa: BLE001
            respostas.put((jid, None, str(erro)))


def _worker_eco(device: str, modelo: str, cache: str, pedidos, respostas) -> None:
    """No encoder — CPU test of the queue protocol. Do not use in production."""
    while True:
        job = pedidos.get()
        if job is None:
            return
        jid, textos, _lote = job
        respostas.put((jid, [[float(len(t))] for t in textos], None))


class EmbedFila:
    """Round-robin across N GPU processes. Call `fechar` when the run ends."""

    def __init__(
        self,
        n_gpus: int,
        *,
        modelo: str,
        cache: Path,
        alvo: WorkerFn | None = None,
    ) -> None:
        if n_gpus < 2:
            raise ValueError("EmbedFila precisa de ao menos 2 GPUs")
        ctx = get_context("spawn")
        self._pedidos = [ctx.Queue() for _ in range(n_gpus)]
        self._respostas = ctx.Queue()
        self._procs = []
        self._proximo = 0
        self._jid = 0
        cache_s = str(cache)
        fn = alvo or _worker
        for i in range(n_gpus):
            p = ctx.Process(
                target=fn,
                args=(str(i), modelo, cache_s, self._pedidos[i], self._respostas),
                daemon=True,
            )
            p.start()
            self._procs.append(p)
        log.info("pipeline: %d processos de embed (um por GPU)", n_gpus)

    def submit(self, textos: list[str], batch_size: int = 32) -> int:
        """Non-blocking. Pair with `receber` — up to one job in flight per GPU."""
        jid = self._jid
        self._jid += 1
        alvo = self._proximo % len(self._pedidos)
        self._proximo += 1
        self._pedidos[alvo].put((jid, list(textos), batch_size))
        return jid

    def receber(self, timeout: float | None = None) -> tuple[int, list[Any]] | None:
        import numpy as np

        if timeout is None:
            rid, bruto, erro = self._bloquear()
        else:
            try:
                rid, bruto, erro = self._respostas.get(timeout=timeout)
            except queue.Empty:
                return None
        if erro:
            raise RuntimeError(f"embed GPU falhou: {erro}")
        return rid, [np.asarray(v, dtype=np.float32) for v in bruto]

    def _bloquear(self) -> tuple[int, Any, str | None]:
        """Wait for a result; fail if a worker died instead of hanging forever."""
        while True:
            try:
                return self._respostas.get(timeout=1.0)
            except queue.Empty:
                mortos = [i for i, p in enumerate(self._procs) if not p.is_alive()]
                if mortos:
                    raise RuntimeError(f"worker GPU morreu: {mortos}") from None

    def embed_passagens(self, textos: list[str], batch_size: int = 32) -> list[Any]:
        jid = self.submit(textos, batch_size)
        got = self.receber()
        if got is None:
            raise RuntimeError("embed GPU sem resposta")
        rid, vetores = got
        if rid != jid:
            raise RuntimeError(f"resposta fora de ordem: pedi {jid}, veio {rid}")
        return vetores

    def fechar(self) -> None:
        for q in self._pedidos:
            q.put(None)
        for p in self._procs:
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()
