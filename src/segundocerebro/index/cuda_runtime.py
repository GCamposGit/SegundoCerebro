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
import sysconfig
from pathlib import Path

from ..logger import get_logger
from .hardware_probe import (
    KERNEL_FALHOU,
    MEMORIA_OCR_MINIMA_MB,
    MSG_KERNEL_FALHOU,
    DiagnosticoCuda,
    DispositivoCuda,
    diagnosticar_inicializacao,
    limpar_cache_sonda,
    provider_da_etapa as _provider_da_etapa,
    selecionar_dispositivo,
    sondar_hardware,
    _executar_kernel_minimo,
    filtrar_gpus_embed as _filtrar_gpus_embed,
    preparar_gpus_embed as _preparar_gpus_embed,
)

__all__ = [
    "KERNEL_FALHOU",
    "MEMORIA_OCR_MINIMA_MB",
    "MSG_KERNEL_FALHOU",
    "DiagnosticoCuda",
    "DispositivoCuda",
    "diagnosticar_inicializacao",
    "limpar_cache_sonda",
    "selecionar_dispositivo",
    "sondar_hardware",
    "_executar_kernel_minimo",
]

log = get_logger("index.cuda_runtime")

_preparado = False

COMPUTE_MAXWELL = "5.2"
# Extra [gpu] pin in pyproject.toml. ORT >= 1.19 is cuDNN 9 (ReduceSum dies
# on Maxwell); ORT >= 1.27 is CUDA 13. tests/test_gpu_extra.py derives the
# extra against these numbers — bumping the extra without this constant, or
# the other way around, is the class Q2 exists to catch.
ORT_GPU_PINADO = (1, 18, 0)
ORT_CUDNN9 = (1, 19, 0)
ORT_CUDA13 = (1, 27, 0)
DRIVER_MAXWELL_LIMITE = 590
TIMEOUT_SONDA_GPU_S = 5

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
    "continua na CPU. O extra [gpu] pinado neste pacote é CUDA 11.8 "
    "(onnxruntime-gpu 1.18.0) — não instale o CUDA 13 do winget nem um "
    "onnxruntime-gpu sem pin."
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
    "`pip uninstall -y onnxruntime` e `pip install -r requirements-gpu.txt` "
    "(o extra [gpu] é CUDA 11.8; o overlay também baixa o numpy para 1.x). "
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
def _raizes_de_site() -> list[Path]:
    """Venv and base prefixes. `getsitepackages()` misses the venv on Windows."""
    achadas: list[Path] = []
    puro = sysconfig.get_paths().get("purelib")
    if puro:
        achadas.append(Path(puro))
    for bruto in site.getsitepackages():
        achadas.append(Path(bruto))
    vistas: list[Path] = []
    for caminho in achadas:
        if caminho not in vistas:
            vistas.append(caminho)
    return vistas


def pastas_nvidia(raizes: list[Path] | None = None) -> list[str]:
    saida: list[str] = []
    for raiz in raizes if raizes is not None else _raizes_de_site():
        nvidia = raiz / "nvidia"
        if not nvidia.is_dir():
            continue
        for binario in nvidia.glob("*/bin"):
            if binario.is_dir() and str(binario) not in saida:
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
        if hasattr(os, "add_dll_directory"):
            for pasta in extras:
                try:
                    os.add_dll_directory(pasta)
                except OSError as erro:
                    log.warning("DLL NVIDIA não entrou no processo (%s): %s", pasta, erro)
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
    if (provider or "").strip():
        return (provider or "").strip().lower()
    return "cuda" if diagnosticar().ok else "cpu"


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
    # DLLs da venv têm de entrar antes do primeiro import do onnxruntime.
    # Sem isso o provider CUDA já nasce sem cuDNN e o OCR cai na CPU.
    preparar()
    p = resolver_provider(provider)
    diagnostico = diagnosticar_inicializacao()
    if p == "cuda":
        if not diagnostico.ok:
            log.warning("CUDA recusado na inicialização; usando CPU: %s", diagnostico.mensagem)
            p = "cpu"
    # Publica o provedor efetivo para os filhos; falha do kernel pode rebaixar
    # até um pedido explícito de CUDA para CPU, sem interromper a indexação.
    atual = (os.environ.get("SEGUNDOCEREBRO_PROVIDER") or "").strip().lower()
    if p and (not atual or atual != p):
        os.environ["SEGUNDOCEREBRO_PROVIDER"] = p
    return p


def listar_gpus() -> list[dict[str, str]]:
    """Plates nvidia-smi can see. Empty is a valid machine, not an error."""
    try:
        bruto = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,driver_version,compute_cap,memory.total,memory.free",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SONDA_GPU_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if bruto.returncode != 0:
        return []
    visiveis = os.environ.get("CUDA_VISIBLE_DEVICES")
    ids_visiveis = [parte.strip() for parte in visiveis.split(",")] if visiveis else None
    saida: list[dict[str, str]] = []
    for linha in bruto.stdout.splitlines():
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) >= 5:
            indice_fisico = partes[0]
            if ids_visiveis is not None and indice_fisico not in ids_visiveis:
                continue
            indice_logico = (
                str(ids_visiveis.index(indice_fisico))
                if ids_visiveis is not None
                else indice_fisico
            )
            saida.append(
                {
                    "indice": indice_logico,
                    "id_fisico": indice_fisico,
                    "name": partes[1],
                    "driver": partes[2],
                    "compute": partes[3],
                    "memoria": partes[4],
                    "memoria_livre": partes[5] if len(partes) > 5 else "",
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


def _build_ort() -> str | None:
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    get = getattr(ort, "get_build_info", None)
    if not callable(get):
        return None
    try:
        return str(get()) or None
    except Exception:  # noqa: BLE001 — diagnóstico best-effort
        return None


def _listar_providers() -> list[str] | None:
    """Production discovers providers. Tests inject them.

    Without this, `import onnxruntime` of the CPU wheel (1.29, what fastembed
    pulls) looks like CUDA 13 on Maxwell: 1.29 >= 1.27, and the indexer
    refuses the extra that is actually 1.18.0 sitting unused. F6-C already
    named this EP_AUSENTE when the caller listed providers; the product path
    did not list them.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    get = getattr(ort, "get_available_providers", None)
    if not callable(get):
        return None
    try:
        return list(get())
    except Exception:  # noqa: BLE001 — probe de hardware: listar EP do ORT é best-effort
        return None


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

    # CPU wheel shadowing the extra [gpu] is not CUDA 13. Discover providers
    # when the caller did not list them — indexer and embeddings call
    # diagnosticar() with only the model. Tests inject the list.
    if providers is None:
        providers = _listar_providers()
    if providers is not None and "CUDAExecutionProvider" not in providers:
        return DiagnosticoCuda(False, EP_AUSENTE, MSG_EP)

    if versao_ort and _parse_versao(versao_ort) >= ORT_CUDA13 and _tem_maxwell(gpus):
        return DiagnosticoCuda(False, CUDA13, MSG_CUDA13)

    if _driver_largou_maxwell(gpus):
        return DiagnosticoCuda(False, DRIVER, MSG_DRIVER)

    return DiagnosticoCuda(True, OK, MSG_OK)


def provider_da_etapa(
    etapa: str,
    *,
    memoria_minima_mb: int = 0,
    indice_fixo: int | None = None,
    modelo: str | None = None,
) -> tuple[str, int | None, str]:
    return _provider_da_etapa(
        etapa,
        memoria_minima_mb=memoria_minima_mb,
        indice_fixo=indice_fixo,
        modelo=modelo,
        diagnostico=diagnosticar_inicializacao(),
    )


def filtrar_gpus_embed(
    modelo: str,
    memoria_minima_mb: int,
    solicitadas: list[str],
) -> tuple[list[str], str, list[str]]:
    return _filtrar_gpus_embed(
        modelo,
        memoria_minima_mb,
        solicitadas,
        diagnosticar_inicializacao(),
    )


def preparar_gpus_embed(
    modelo: str,
    memoria_minima_mb: int,
    solicitadas: list[str],
) -> list[str]:
    return _preparar_gpus_embed(
        modelo,
        memoria_minima_mb,
        solicitadas,
        diagnosticar_inicializacao(),
    )
