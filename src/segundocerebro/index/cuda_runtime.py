"""Put pip-vendored CUDA/cuDNN DLLs on this process PATH, and say why not.

Does not change the machine PATH or the driver. Called from the smoke test
and from the embedder when the provider is cuda.

F6-C: CPU is the default. CUDA is opt-in (`SEGUNDOCEREBRO_PROVIDER=cuda` +
extra `[gpu]`). Incompatible GPU (CUDA 13 on Maxwell, MiniLM-Q) is refused
in Portuguese — the layperson does not have to know what `sm_52` is.
Hardware never enters `model_id`.
"""

from __future__ import annotations

import os
import site
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..logger import get_logger

log = get_logger("index.cuda_runtime")

_preparado = False

COMPUTE_MAXWELL = "5.2"
ORT_CUDA13 = (1, 27, 0)
DRIVER_MAXWELL_LIMITE = 590

OK = "ok"
SEM_GPU = "sem_gpu"
CUDA13 = "cuda13"
MINILM = "minilm_q"
EP_AUSENTE = "ep_ausente"
DRIVER = "driver_maxwell"
SEM_ORT = "sem_ort"

MSG_SEM_GPU = (
    "Não achei placa NVIDIA. A indexação neste computador é na CPU — é o padrão. "
    "CUDA é extra opcional (`pip install -e .[gpu]`) e só entra se você pedir "
    "com SEGUNDOCEREBRO_PROVIDER=cuda."
)
MSG_CUDA13 = (
    "Este pacote de GPU usa CUDA 13, que não roda nesta placa de vídeo. "
    "Desinstale o extra [gpu] (`pip uninstall onnxruntime-gpu`) e a indexação "
    "continua na CPU. O extra que funciona nesta placa é CUDA 11.8, pinado em "
    "requirements-gpu.txt — não instale o CUDA 13 do winget."
)
MSG_MINILM = (
    "O modelo pequeno (MiniLM) devolve NaN nesta GPU — números inválidos, o "
    "índice ficaria podre. Use o modelo padrão (e5-large) ou tire "
    "SEGUNDOCEREBRO_PROVIDER=cuda para indexar na CPU. O tipo de hardware não "
    "entra no identificador do índice."
)
MSG_EP = (
    "O CUDA não carregou neste Python. O `onnxruntime` CPU (o que o fastembed "
    "puxa sozinho) tampa o extra [gpu]. Neste desktop: "
    "`pip uninstall -y onnxruntime` e `pip install -r requirements-gpu.txt`. "
    "Ou tire SEGUNDOCEREBRO_PROVIDER=cuda para indexar na CPU — é o padrão."
)
MSG_DRIVER = (
    "O driver NVIDIA 590 ou mais novo largou esta placa de vídeo. Fique no "
    "ramo 580. Enquanto isso, tire SEGUNDOCEREBRO_PROVIDER=cuda para indexar "
    "na CPU."
)
MSG_SEM_ORT = (
    "onnxruntime não importou. Sem o extra [gpu] a indexação é na CPU. "
    "Não instale um pacote de GPU com CUDA 13."
)
MSG_OK = "CUDA visível."


@dataclass(frozen=True)
class DiagnosticoCuda:
    ok: bool
    codigo: str
    mensagem: str


def pastas_nvidia() -> list[str]:
    saida: list[str] = []
    for raiz in site.getsitepackages():
        nvidia = Path(raiz) / "nvidia"
        if not nvidia.is_dir():
            continue
        for binario in nvidia.glob("*/bin"):
            if binario.is_dir():
                saida.append(str(binario))
    return saida


def preparar() -> None:
    """Idempotent. Safe to call on a machine with no GPU packages."""
    global _preparado
    if _preparado:
        return
    extras = pastas_nvidia()
    if extras:
        os.environ["PATH"] = os.pathsep.join(extras + [os.environ.get("PATH", "")])
        log.info("PATH deste processo += %d pastas nvidia/*/bin", len(extras))
    try:
        import onnxruntime as ort
    except ImportError:
        _preparado = True
        return
    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload()
        except Exception as erro:  # noqa: BLE001 — probe de hardware: preload de DLL CUDA é best-effort
            log.warning("preload_dlls() falhou: %s", erro)
    _preparado = True


def provider_pedido() -> str:
    """`cuda` only when asked. Anything else is CPU — F6-C default."""
    return "cuda" if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda" else "cpu"


def resolver_provider(provider: str | None) -> str:
    """Which provider wins between the env and `[maquina] provider` — no side effect.

    F6-C made empty env mean CPU. The desktop's `config.toml` says `cuda`;
    without this the indexer never starts the GPU pool and the cards sit at
    1% while the pass runs on the CPU. Env still wins when set.

    Pure on purpose. `aplicar_provider` is what writes, and only a process
    entry point may call it — see the docstring there.
    """
    pedido = (os.environ.get("SEGUNDOCEREBRO_PROVIDER") or "").strip()
    if pedido:
        return pedido.lower()
    return (provider or "").strip().lower() or "cpu"


def aplicar_provider(provider: str | None) -> str:
    """Resolve, and publish the answer to the whole process — `main()` only.

    A escrita em `os.environ` não é descuido: os processos de embed nascem por
    `multiprocessing` e leem a variável do ambiente que herdaram. Publicar é o
    mecanismo, e é por isso que ele continua aqui.

    O que mudou em 29/08/2026 é **quem** pode chamar. Esta função era a única
    porta, e um teste unitário a chamava direto: `monkeypatch.delenv` sobre uma
    variável ausente não registra nada para desfazer, então a escrita feita pelo
    produto dentro do teste sobrevivia à sessão inteira do pytest e envenenava
    todo teste posterior que rodasse `indexar()` — seis falhas de
    `tests/test_watcher.py` com `RuntimeError: Não achei placa NVIDIA`, verdes
    quando o arquivo roda sozinho. No desktop `diagnosticar()` diz `ok` e a suíte
    fica verde, então quem só roda lá nunca via.

    Quem só precisa saber a resposta chama `resolver_provider`, que não escreve.
    """
    p = resolver_provider(provider)
    # Publica só o que o ambiente ainda não disse e o arquivo declarou — a mesma
    # condição de antes, escrita agora sobre a função pura.
    if not (os.environ.get("SEGUNDOCEREBRO_PROVIDER") or "").strip() and (provider or "").strip():
        os.environ["SEGUNDOCEREBRO_PROVIDER"] = p
    return p


def listar_gpus() -> list[dict[str, str]]:
    """Plates nvidia-smi can see. Empty is a valid machine, not an error."""
    try:
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
    saida: list[dict[str, str]] = []
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


def _parse_versao(texto: str) -> tuple[int, int, int]:
    partes: list[int] = []
    for pedaco in texto.split("."):
        digitos = "".join(c for c in pedaco if c.isdigit())
        if digitos:
            partes.append(int(digitos))
        if len(partes) == 3:
            break
    while len(partes) < 3:
        partes.append(0)
    return partes[0], partes[1], partes[2]


def _versao_ort() -> str | None:
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    return getattr(ort, "__version__", "") or None


def _eh_minilm(modelo: str) -> bool:
    baixo = modelo.lower()
    return baixo == "minilm" or "minilm" in baixo or "onnx-q" in baixo


def _tem_maxwell(gpus: list[dict[str, str]]) -> bool:
    return any(g.get("compute", "") == COMPUTE_MAXWELL for g in gpus)


def _driver_largou_maxwell(gpus: list[dict[str, str]]) -> bool:
    for g in gpus:
        if g.get("compute", "") != COMPUTE_MAXWELL:
            continue
        major = g.get("driver", "").split(".", 1)[0]
        if major.isdigit() and int(major) >= DRIVER_MAXWELL_LIMITE:
            return True
    return False


def diagnosticar(
    *,
    modelo: str | None = None,
    gpus: list[dict[str, str]] | None = None,
    versao_ort: str | None = None,
    providers: list[str] | None = None,
) -> DiagnosticoCuda:
    """Why CUDA cannot run here, in Portuguese. Cheap: no forward pass.

    Callers inject `gpus` / `versao_ort` / `providers` in tests. Production
    discovers them. MiniLM-Q is refused before a GPU is even listed — writing
    NaN is worse than not using the card.
    """
    if modelo and _eh_minilm(modelo):
        return DiagnosticoCuda(False, MINILM, MSG_MINILM)

    if gpus is None:
        gpus = listar_gpus()
    if not gpus:
        return DiagnosticoCuda(False, SEM_GPU, MSG_SEM_GPU)

    if versao_ort is None:
        versao_ort = _versao_ort()
    if versao_ort is None and providers is None:
        return DiagnosticoCuda(False, SEM_ORT, MSG_SEM_ORT)

    # CPU wheel shadowing the extra [gpu] is not CUDA 13. Check the EP first
    # when the caller already listed providers (smoke / indexer).
    if providers is not None and "CUDAExecutionProvider" not in providers:
        return DiagnosticoCuda(False, EP_AUSENTE, MSG_EP)

    if versao_ort and _parse_versao(versao_ort) >= ORT_CUDA13 and _tem_maxwell(gpus):
        return DiagnosticoCuda(False, CUDA13, MSG_CUDA13)

    if _driver_largou_maxwell(gpus):
        return DiagnosticoCuda(False, DRIVER, MSG_DRIVER)

    return DiagnosticoCuda(True, OK, MSG_OK)
