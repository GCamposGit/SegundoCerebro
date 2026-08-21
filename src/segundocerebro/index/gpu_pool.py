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
from collections.abc import Sequence
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable

from ..logger import get_logger

log = get_logger("index.gpu_pool")

WorkerFn = Callable[[str, str, str, Any, Any], None]


def _linhas_smi(query: str) -> list[str]:
    try:
        bruto = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if bruto.returncode != 0:
        return []
    return [ln.strip() for ln in bruto.stdout.splitlines() if ln.strip()]


def dispositivos_embed() -> list[str]:
    """Physical GPU indices for compute.

    If at least one card has no monitor, skip the ones driving the display.
    Loading e5-large (~4 GB) on a 6 GB 980 Ti that also paints the desktop
    trips Windows TDR (Event 4101, nvlddmkm) and can take the machine down.
    Measured 21/08/2026 on this desktop: GPU 0 `display_active=Enabled`,
    GPU 1 Disabled; a night of dual-GPU embed ended in Kernel-Power 41.

    If every card has a display, keep them all — there is nothing to spare.
    """
    linhas = _linhas_smi("index,display_active")
    if not linhas:
        # Older nvidia-smi without display_active: fall back to counting names.
        return [str(i) for i, _ in enumerate(_linhas_smi("name"))]

    todos: list[str] = []
    livres: list[str] = []
    for linha in linhas:
        partes = [p.strip() for p in linha.split(",")]
        if not partes:
            continue
        idx = partes[0]
        todos.append(idx)
        ativo = partes[1].lower() if len(partes) > 1 else ""
        if ativo not in {"enabled", "enable"}:
            livres.append(idx)
    if livres:
        if len(livres) < len(todos):
            log.info(
                "pulando GPU(s) com display %s; embed em %s",
                [i for i in todos if i not in livres],
                livres,
            )
        return livres
    return todos


def contar_gpus() -> int:
    return len(dispositivos_embed())


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
        gpus: int | Sequence[str],
        *,
        modelo: str,
        cache: Path,
        alvo: WorkerFn | None = None,
    ) -> None:
        if isinstance(gpus, int):
            devices = [str(i) for i in range(gpus)]
        else:
            devices = [str(g) for g in gpus]
        if len(devices) < 2:
            raise ValueError("EmbedFila precisa de ao menos 2 GPUs")
        ctx = get_context("spawn")
        self._pedidos = [ctx.Queue() for _ in devices]
        self._respostas = ctx.Queue()
        self._procs = []
        self._proximo = 0
        self._jid = 0
        cache_s = str(cache)
        fn = alvo or _worker
        for device in devices:
            p = ctx.Process(
                target=fn,
                args=(device, modelo, cache_s, self._pedidos[len(self._procs)], self._respostas),
                daemon=True,
            )
            p.start()
            self._procs.append(p)
        log.info("pipeline: %d processos de embed (GPUs %s)", len(devices), ",".join(devices))

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
