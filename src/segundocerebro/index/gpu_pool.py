"""One ONNX session per GPU — the Runtime will not split a session.

GPUs are discovered at runtime (`nvidia-smi`). Nothing here assumes how many
cards the machine has, or which one drives the monitor — that is only known
at install. `model_id` is unchanged. Hardware does not enter the vector.

Used when SEGUNDOCEREBRO_PROVIDER=cuda and at least two cards were *selected*
for embed. The main process then never loads the encoder.
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
        bruto = subprocess.run(  # noqa: S603 — argv fixo, `query` é literal do módulo
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


def _parse_smi_display(linhas: list[str]) -> tuple[list[str], list[str]]:
    """Returns (all indices, indices without an active display)."""
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
    return todos, livres


def dispositivos_embed(*, reservar_display: bool = False) -> list[str]:
    """Physical GPU indices for the encoder, discovered now.

    The installer does not know how many cards there will be. Rules, in order:

    1. No NVIDIA / nvidia-smi → empty (caller stays on CPU).
    2. One GPU → that GPU, even if it drives the monitor. Skipping it would
       leave a one-GPU machine with no accelerator — the common case.
    3. Two or more, and `reservar_display` (perfil `leve`) → drop cards with
       `display_active`, but only if at least one remains. TDR on the desktop
       GPU is a `leve` concern; it is not a reason to idle a spare card in
       `completo`/`maximo`.
    4. Two or more, not `leve` → every card.

    `reservar_display` is the effort profile, not a hardware constant.
    """
    linhas = _linhas_smi("index,display_active")
    if not linhas:
        return [str(i) for i, _ in enumerate(_linhas_smi("name"))]

    todos, livres = _parse_smi_display(linhas)
    if not todos:
        return []
    if len(todos) == 1:
        return todos
    if reservar_display and livres:
        if len(livres) < len(todos):
            log.info(
                "perfil leve: GPU do display %s fica para o desktop; embed em %s",
                [i for i in todos if i not in livres],
                livres,
            )
        return livres
    return todos


def contar_gpus() -> int:
    """How many NVIDIA GPUs nvidia-smi sees. Display does not subtract."""
    return len(dispositivos_embed(reservar_display=False))


def _desempacotar(job) -> tuple:  # noqa: ANN001
    """(jid, textos, lote, ritmo). Ritmo 1.0 se o produtor velho mandou 3 campos."""
    if len(job) == 4:
        return job
    jid, textos, lote = job
    return jid, textos, lote, 1.0


def _worker(device: str, modelo: str, cache: str, pedidos, respostas) -> None:  # noqa: ANN001 — tipo fica no chamador para não importar o módulo pesado
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
        jid, textos, lote, ritmo = _desempacotar(job)
        try:
            vetores = embedder.embed_passagens(textos, batch_size=lote, ritmo=ritmo)
            respostas.put((jid, [v.tolist() for v in vetores], None))
        except Exception as erro:  # noqa: BLE001 — worker da GPU devolve o erro na fila; o processo não morre
            respostas.put((jid, None, str(erro)))


def _worker_eco(device: str, modelo: str, cache: str, pedidos, respostas) -> None:  # noqa: ANN001, ARG001 — tipo fica no chamador para não importar o módulo pesado; argumento faz parte da assinatura compartilhada
    """No encoder — CPU test of the queue protocol. Do not use in production."""
    while True:
        job = pedidos.get()
        if job is None:
            return
        jid, textos, _lote, _ritmo = _desempacotar(job)
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
        if len(devices) < 1:
            raise ValueError("EmbedFila precisa de ao menos 1 GPU")
        ctx = get_context("spawn")
        self._devices = devices
        self._pedidos = [ctx.Queue() for _ in devices]
        self._respostas = ctx.Queue()
        self._procs = []
        self._inflight = [0] * len(devices)
        self._pesos = [1.0] * len(devices)
        self._ritmos = [1.0] * len(devices)
        self._onde: dict[int, int] = {}
        self._jid = 0
        self._modelo = modelo
        self._cache = str(cache)
        self._alvo = alvo or _worker
        self._ctx = ctx
        for device in devices:
            self._spawn(device)
        log.info("pipeline: %d processos de embed (GPUs %s)", len(devices), ",".join(devices))

    def _spawn(self, device: str) -> None:
        p = self._ctx.Process(
            target=self._alvo,
            args=(device, self._modelo, self._cache, self._pedidos[len(self._procs)], self._respostas),
            daemon=True,
        )
        p.start()
        self._procs.append(p)

    @property
    def pids(self) -> list[int]:
        return [p.pid for p in self._procs if p.pid]

    def ajustar(self, pesos: dict[str, float], ritmos: dict[str, float] | None = None) -> None:
        """Repondera GPUs já ligadas. Peso 0 = não recebe trabalho novo."""
        ritmos = ritmos or {}
        for i, d in enumerate(self._devices):
            self._pesos[i] = max(0.0, float(pesos.get(d, 0.0)))
            if d in ritmos:
                self._ritmos[i] = max(0.05, min(1.0, float(ritmos[d])))

    def _escolher(self) -> int:
        melhor, nota = 0, 1e18
        algum = False
        for i, peso in enumerate(self._pesos):
            if peso <= 0:
                continue
            algum = True
            carga = self._inflight[i] / peso
            if carga < nota:
                melhor, nota = i, carga
        if not algum:
            return min(range(len(self._devices)), key=lambda i: self._inflight[i])
        return melhor

    def submit(self, textos: list[str], batch_size: int = 32, ritmo: float | None = None) -> int:
        """Non-blocking. Pair with `receber` — up to one job in flight per GPU."""
        jid = self._jid
        self._jid += 1
        alvo = self._escolher()
        self._inflight[alvo] += 1
        self._onde[jid] = alvo
        duty = self._ritmos[alvo] if ritmo is None else ritmo
        self._pedidos[alvo].put((jid, list(textos), batch_size, duty))
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
        slot = self._onde.pop(rid, None)
        if slot is not None:
            self._inflight[slot] = max(0, self._inflight[slot] - 1)
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
