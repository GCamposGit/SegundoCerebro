"""Adaptive startup probe shared by indexing, MCP, OCR and embeddings."""

from __future__ import annotations

import json
import os
import platform
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from ..logger import get_logger

log = get_logger("index.cuda_runtime")

KERNEL_FALHOU = "kernel_falhou"
MSG_KERNEL_FALHOU = (
    "O ONNX Runtime anuncia CUDA, mas o kernel mínimo não executou na GPU. "
    "A etapa continua na CPU. Consulte o log para ver o motivo."
)
MEMORIA_OCR_MINIMA_MB = 768


@dataclass(frozen=True)
class DispositivoCuda:
    indice: int
    nome: str
    compute: str
    memoria_total_mb: int | None
    memoria_livre_mb: int | None
    kernel_ok: bool
    motivo: str = ""
    id_fisico: str = ""


@dataclass(frozen=True)
class DiagnosticoCuda:
    ok: bool
    codigo: str
    mensagem: str
    cpu: str = ""
    versao_ort: str | None = None
    build_ort: str | None = None
    providers_anunciados: tuple[str, ...] = ()
    providers_com_kernel: tuple[str, ...] = ()
    dispositivos: tuple[DispositivoCuda, ...] = ()


_diagnostico_cache: DiagnosticoCuda | None = None


def _varint(valor: int) -> bytes:
    bruto = bytearray()
    while valor > 0x7F:
        bruto.append((valor & 0x7F) | 0x80)
        valor >>= 7
    bruto.append(valor)
    return bytes(bruto)


def _campo_bytes(numero: int, valor: bytes) -> bytes:
    return _varint((numero << 3) | 2) + _varint(len(valor)) + valor


def _campo_int(numero: int, valor: int) -> bytes:
    return _varint(numero << 3) + _varint(valor)


def _valor_info(nome: bytes) -> bytes:
    dimensao = _campo_int(1, 1)
    forma = _campo_bytes(1, dimensao)
    tensor = _campo_int(1, 1) + _campo_bytes(2, forma)
    tipo = _campo_bytes(1, tensor)
    return _campo_bytes(1, nome) + _campo_bytes(2, tipo)


def _modelo_kernel_minimo() -> bytes:
    no = (
        _campo_bytes(1, b"entrada") + _campo_bytes(1, b"entrada")
        + _campo_bytes(2, b"saida") + _campo_bytes(3, b"sonda_cuda")
        + _campo_bytes(4, b"Add")
    )
    grafo = (
        _campo_bytes(1, no) + _campo_bytes(2, b"sonda_hardware")
        + _campo_bytes(11, _valor_info(b"entrada"))
        + _campo_bytes(12, _valor_info(b"saida"))
    )
    opset = _campo_bytes(1, b"") + _campo_int(2, 13)
    return _campo_int(1, 8) + _campo_bytes(7, grafo) + _campo_bytes(8, opset)


def _executar_kernel_minimo(provider: str, indice: int | None) -> tuple[bool, str]:
    """Execute Add and confirm its provider from ONNX Runtime profiling."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as erro:
        return False, f"dependência ausente: {erro}"
    opcoes = ort.SessionOptions()
    opcoes.enable_profiling = True
    opcoes.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    try:
        with tempfile.TemporaryDirectory(prefix="sc-hardware-probe-") as pasta:
            opcoes.profile_file_prefix = str(Path(pasta) / "kernel")
            pedido: list[object] = (
                [(provider, {"device_id": str(indice or 0)})]
                if provider == "CUDAExecutionProvider"
                else [provider]
            )
            sessao = ort.InferenceSession(
                _modelo_kernel_minimo(), sess_options=opcoes, providers=pedido
            )
            esperado = np.asarray([2.0], dtype=np.float32)
            saida = sessao.run(
                ["saida"], {"entrada": np.asarray([1.0], dtype=np.float32)}
            )
            if not np.array_equal(saida[0], esperado):
                return False, "kernel mínimo devolveu um resultado inválido"
            eventos = json.loads(Path(sessao.end_profiling()).read_text(encoding="utf-8"))
            executores = {
                evento.get("args", {}).get("provider")
                for evento in eventos
                if evento.get("cat") == "Node"
            }
            if provider not in executores:
                executado = ", ".join(sorted(p for p in executores if p)) or "nenhum"
                return False, f"o kernel mínimo executou em {executado}, não em {provider}"
            return True, "kernel mínimo executado"
    except Exception as erro:  # noqa: BLE001 — a sonda deve falhar fechada
        return False, f"{type(erro).__name__}: {erro}"


def _cpu_atual() -> str:
    return platform.processor() or platform.machine() or "desconhecida"


def _mb(valor: str) -> int | None:
    partes = valor.strip().lower().split()
    digitos = "".join(caractere for caractere in partes[0] if caractere.isdigit()) if partes else ""
    if not digitos:
        return None
    numero = int(digitos)
    unidade = partes[1] if len(partes) > 1 else "mib"
    if unidade.startswith(("gib", "gb")):
        return numero * 1024
    if unidade.startswith(("tib", "tb")):
        return numero * 1024 * 1024
    if unidade.startswith(("kib", "kb")):
        return max(1, numero // 1024)
    return numero


def _sondar_dispositivos(base, gpus, executar, providers) -> tuple[list[DispositivoCuda], list[str]]:  # noqa: ANN001
    dispositivos: list[DispositivoCuda] = []
    providers_ok: list[str] = []
    if providers and "CPUExecutionProvider" in providers:
        cpu_ok, _ = executar("CPUExecutionProvider", None)
        if cpu_ok:
            providers_ok.append("CPUExecutionProvider")
    for posicao, gpu in enumerate(gpus):
        try:
            indice = int(gpu.get("indice", posicao))
        except ValueError:
            indice = posicao
        kernel_ok, motivo = (
            executar("CUDAExecutionProvider", indice) if base.ok else (False, base.mensagem)
        )
        dispositivos.append(
            DispositivoCuda(
                indice=indice,
                nome=gpu.get("name", "NVIDIA"),
                compute=gpu.get("compute", ""),
                memoria_total_mb=_mb(gpu.get("memoria", "")),
                memoria_livre_mb=_mb(gpu.get("memoria_livre", "")),
                kernel_ok=kernel_ok,
                motivo=motivo,
                id_fisico=gpu.get("id_fisico", gpu.get("indice", str(indice))),
            )
        )
        if kernel_ok:
            providers_ok.append("CUDAExecutionProvider")
    return dispositivos, providers_ok


def sondar_hardware(
    *,
    modelo: str | None = None,
    gpus: list[dict[str, str]] | None = None,
    versao_ort: str | None = None,
    providers: list[str] | None = None,
    executar_kernel: Callable[[str, int | None], tuple[bool, str]] | None = None,
    cpu: str | None = None,
    build_ort: str | None = None,
) -> DiagnosticoCuda:
    """Full injectable startup probe; advertised providers alone never pass."""
    from .cuda_runtime import _build_ort, _listar_providers, _versao_ort, diagnosticar

    gpus = gpus if gpus is not None else _listar_gpus()
    versao_ort = versao_ort if versao_ort is not None else _versao_ort()
    providers = providers if providers is not None else _listar_providers()
    base = diagnosticar(modelo=modelo, gpus=gpus, versao_ort=versao_ort, providers=providers)
    dispositivos, providers_ok = _sondar_dispositivos(
        base, gpus, executar_kernel or _executar_kernel_minimo, providers
    )
    funcionando = any(dispositivo.kernel_ok for dispositivo in dispositivos)
    resultado = base
    if base.ok and not funcionando:
        motivos = "; ".join(
            f"GPU {d.indice} ({d.nome}): {d.motivo}" for d in dispositivos
        ) or "nenhuma GPU pôde ser testada"
        resultado = DiagnosticoCuda(False, KERNEL_FALHOU, f"{MSG_KERNEL_FALHOU} {motivos}")
    return DiagnosticoCuda(
        ok=resultado.ok,
        codigo=resultado.codigo,
        mensagem=resultado.mensagem,
        cpu=cpu or _cpu_atual(),
        versao_ort=versao_ort,
        build_ort=build_ort if build_ort is not None else _build_ort(),
        providers_anunciados=tuple(providers or ()),
        providers_com_kernel=tuple(dict.fromkeys(providers_ok)),
        dispositivos=tuple(dispositivos),
    )


def _listar_gpus():  # noqa: ANN202 — tipo concreto pertence ao runtime
    from .cuda_runtime import listar_gpus

    return listar_gpus()


def diagnosticar_inicializacao() -> DiagnosticoCuda:
    """Shared, once-per-process hardware report; tests inject instead of probing cards."""
    global _diagnostico_cache
    if _diagnostico_cache is None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            _diagnostico_cache = DiagnosticoCuda(
                False,
                "sem_gpu",
                "Sonda física desativada durante pytest; hardware deve ser injetado.",
                cpu=_cpu_atual(),
            )
        else:
            _diagnostico_cache = sondar_hardware()
        diag = _diagnostico_cache
        log.info(
            "hardware | CPU %s | ONNX %s (%s) | providers anunciados %s | kernels executados %s | CUDA: %s",
            diag.cpu,
            diag.versao_ort or "indisponível",
            diag.build_ort or "build desconhecida",
            ",".join(diag.providers_anunciados) or "nenhum",
            ",".join(diag.providers_com_kernel) or "nenhum",
            diag.mensagem,
        )
        for dispositivo in diag.dispositivos:
            log.info(
                "GPU %d | %s | compute %s | VRAM livre %s MB | kernel CUDA %s%s",
                dispositivo.indice,
                dispositivo.nome,
                dispositivo.compute or "desconhecido",
                dispositivo.memoria_livre_mb if dispositivo.memoria_livre_mb is not None else "desconhecida",
                "ok" if dispositivo.kernel_ok else "falhou",
                f" ({dispositivo.motivo})" if dispositivo.motivo else "",
            )
    return _diagnostico_cache


def limpar_cache_sonda() -> None:
    global _diagnostico_cache
    _diagnostico_cache = None


def selecionar_dispositivo(
    diagnostico: DiagnosticoCuda,
    *,
    memoria_minima_mb: int = 0,
    indices_permitidos: set[int] | None = None,
) -> DispositivoCuda | None:
    candidatos = [
        d for d in diagnostico.dispositivos
        if d.kernel_ok
        and (indices_permitidos is None or d.indice in indices_permitidos)
        and d.memoria_livre_mb is not None
        and d.memoria_livre_mb >= memoria_minima_mb
    ]
    return max(candidatos, key=lambda d: d.memoria_livre_mb or 0, default=None)


def _dispositivo_visivel(dispositivo: DispositivoCuda) -> DispositivoCuda | None:
    texto = os.environ.get("CUDA_VISIBLE_DEVICES")
    if texto is None:
        return dispositivo
    ids = [parte.strip() for parte in texto.split(",") if parte.strip()]
    fisico = dispositivo.id_fisico or str(dispositivo.indice)
    if fisico not in ids:
        return None
    return replace(dispositivo, indice=ids.index(fisico))


def provider_da_etapa(
    etapa: str,
    *,
    memoria_minima_mb: int = 0,
    indice_fixo: int | None = None,
    modelo: str | None = None,
    diagnostico: DiagnosticoCuda | None = None,
) -> tuple[str, int | None, str]:
    from .cuda_runtime import MINILM, diagnosticar, provider_pedido

    if provider_pedido() != "cuda":
        return "cpu", None, "CPU solicitado ou padrão"
    diag = diagnostico or diagnosticar_inicializacao()
    if modelo:
        compatibilidade = diagnosticar(modelo=modelo)
    else:
        compatibilidade = None
    if compatibilidade and compatibilidade.codigo == MINILM:
        motivo = compatibilidade.mensagem
        log.warning("etapa %s em CPU: %s", etapa, motivo)
        return "cpu", None, motivo
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if indice_fixo is not None and visible is not None:
        ids = [parte.strip() for parte in visible.split(",") if parte.strip()]
        fisico = ids[indice_fixo] if indice_fixo < len(ids) else ""
        indices = {d.indice for d in diag.dispositivos if d.id_fisico == fisico}
    else:
        indices = {indice_fixo} if indice_fixo is not None else None
    dispositivo = selecionar_dispositivo(
        diag, memoria_minima_mb=memoria_minima_mb, indices_permitidos=indices
    )
    dispositivo = _dispositivo_visivel(dispositivo) if dispositivo else None
    if dispositivo is None:
        motivo = diag.mensagem
        if diag.ok:
            motivo = f"nenhuma GPU testada tem {memoria_minima_mb} MB livres"
            if indice_fixo is not None:
                motivo += f" no dispositivo {indice_fixo}"
        log.warning("etapa %s em CPU: %s", etapa, motivo)
        return "cpu", None, motivo
    log.info(
        "etapa %s em CUDA | GPU %d %s | %d MB livres",
        etapa, dispositivo.indice, dispositivo.nome, dispositivo.memoria_livre_mb or 0,
    )
    return "cuda", dispositivo.indice, "kernel mínimo executado e VRAM suficiente"


def filtrar_gpus_embed(
    modelo: str,
    memoria_minima_mb: int,
    solicitadas: list[str],
    diagnostico: DiagnosticoCuda,
) -> tuple[list[str], str, list[str]]:
    from .cuda_runtime import MINILM, diagnosticar

    compatibilidade = diagnosticar(modelo=modelo)
    if not compatibilidade.ok and compatibilidade.codigo == MINILM:
        raise RuntimeError(compatibilidade.mensagem)
    aprovadas = {
        d.id_fisico or str(d.indice)
        for d in diagnostico.dispositivos
        if d.kernel_ok and d.memoria_livre_mb is not None and d.memoria_livre_mb >= memoria_minima_mb
    }
    if not compatibilidade.ok or not aprovadas:
        motivo = compatibilidade.mensagem if not compatibilidade.ok else diagnostico.mensagem
        if compatibilidade.ok and diagnostico.ok:
            motivo = f"nenhuma GPU aprovada tem {memoria_minima_mb} MB livres"
        return [], motivo, list(solicitadas)
    aceitas = [str(gpu) for gpu in solicitadas if str(gpu) in aprovadas]
    recusadas = [str(gpu) for gpu in solicitadas if str(gpu) not in aprovadas]
    if recusadas:
        return aceitas, "uma ou mais GPUs não passaram kernel/VRAM", recusadas
    return aceitas, "", []


def preparar_gpus_embed(
    modelo: str,
    memoria_minima_mb: int,
    solicitadas: list[str],
    diagnostico: DiagnosticoCuda,
) -> list[str]:
    aceitas, motivo, recusadas = filtrar_gpus_embed(
        modelo, memoria_minima_mb, solicitadas, diagnostico
    )
    if motivo:
        log.warning("embedding em CPU/GPU reduzida: %s", motivo)
    if recusadas:
        log.warning("GPU(s) %s ficaram fora do pool por kernel/VRAM", ",".join(recusadas))
    return aceitas
