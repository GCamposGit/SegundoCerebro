"""Machine scheduling regime — battery, EcoQoS, hybrid topology.

F4-R.1 (2026-09-02). Calibration that does not record this mixes two worlds
that differ by an order of magnitude. The 22× on the 1355U was EcoQoS plus a
mask that mixed P-cores and E-cores; this module records the state and can
turn EcoQoS on and off, without assuming that topology.

Windows `EfficiencyClass` is **not** the classifier: on the 14700HX, P-cores
report class 1 and E-cores class 0, the opposite of MSDN. P-cores are the
ones with SMT; E-cores are the single-thread cores on a hybrid package.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from pathlib import Path
from typing import Any

ProcessPowerThrottling = 4
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
RelationProcessorCore = 0


def aceita_regime(ecoqos: bool | None) -> bool:
    """Whether an observation may update the default coefficients.

    EcoQoS-on is the slow scheduling regime isolated in F4-R.1 (3.72× on the
    14700HX). Mixing it with EcoQoS-off is bias, not noise. `None` means the
    OS has no API — desktop, POSIX — and there is no second regime to mix.
    """
    return ecoqos is not True


def arquitetura_da_maquina() -> str:
    """Arquitetura sem consulta WMI no Windows hospedado."""
    if sys.platform == "win32":
        return (
            os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or "Windows"
        )
    return platform.machine()


def processador_da_maquina() -> str:
    """Nome do processador sem bloquear no provedor WMI do Windows."""
    if sys.platform == "win32":
        return os.environ.get("PROCESSOR_IDENTIFIER") or arquitetura_da_maquina()
    return platform.processor() or arquitetura_da_maquina()


def impressao_da_maquina(model_id: str, chunker: str, *, gpus: list[str] | None = None) -> str:
    """Hash of everything that invalidates the machine coefficients.

    Core count is the **total** logical count, not the profile's usable slice:
    the profile is already its own dimension (`g`). EcoQoS is **not** folded
    in: the slow regime is dropped at `Calibracao.observar`, so the remaining
    history is the benign world. Splitting the fingerprint would calibrate
    neither (the same reason profile is not in the key).
    """
    partes = [
        arquitetura_da_maquina(),
        processador_da_maquina()[:80],
        str(os.cpu_count() or 0),
        ",".join(sorted(gpus or [])),
        model_id,
        chunker,
    ]
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:16]


def diretorio_de_calibracao() -> Path:
    """Per-machine, outside every base — encoder cost learned once serves all."""
    forcado = os.environ.get("SEGUNDOCEREBRO_CALIBRACAO")
    if forcado:
        return Path(forcado)
    if os.name == "nt":
        raiz = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        raiz = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
    return Path(raiz) / "segundocerebro"


def ecoqos_ativo() -> bool | None:
    """Whether this process is in EcoQoS / execution-speed throttling.

    `None` on POSIX, on an OS without the API, or when the probe fails.
    """
    return _ecoqos_windows(None)


def aplicar_ecoqos(ligado: bool) -> bool | None:
    """Turn EcoQoS on or off. Returns the state after the call, or `None`."""
    return _ecoqos_windows(bool(ligado))


def topologia() -> dict[str, Any]:
    """Logical processors grouped as P-cores and E-cores.

    `regra` is `smt` on Intel hybrid (SMT cores vs single-thread cores),
    `homogeneo` when every core looks the same, `desconhecido` when the OS
    does not report topology. Never raises.
    """
    nucleos = _nucleos_windows()
    if not nucleos:
        n = os.cpu_count() or 1
        return {"p": list(range(n)), "e": [], "regra": "desconhecido", "logicos": n}
    com_smt = [c for c in nucleos if c["smt"]]
    sem_smt = [c for c in nucleos if not c["smt"]]
    if com_smt and sem_smt:
        p = sorted(lp for c in com_smt for lp in c["lps"])
        e = sorted(lp for c in sem_smt for lp in c["lps"])
        regra = "smt"
    else:
        p = sorted(lp for c in nucleos for lp in c["lps"])
        e = []
        regra = "homogeneo"
    return {"p": p, "e": e, "regra": regra, "logicos": len(p) + len(e)}


def mascara_mista(n_usados: int, topo: dict[str, Any] | None = None) -> list[int]:
    """R.3 candidate: one LP per P-core for ~n/3, rest E-cores.

    On the 1355U that is `[0,2,4,5,6,7]`. Measured 02/09/2026 on the 14700HX
    and refuted: 1.76× slower than P-only in the EcoQoS-on regime. Kept so
    the instrument can reproduce the contrast; the product uses
    `mascara_afinidade`.
    """
    p, e, n = _partes(n_usados, topo)
    if not p or not e:
        return list(range(n))
    p_um = p[::2] or p
    n_p = min(len(p_um), max(1, n // 3))
    n_e = min(len(e), n - n_p)
    n_p = min(len(p_um), n - n_e)
    mask = p_um[:n_p] + e[:n_e]
    if len(mask) < n:
        resto = [x for x in p + e if x not in mask]
        mask.extend(resto[: n - len(mask)])
    return mask


def mascara_afinidade(n_usados: int, topo: dict[str, Any] | None = None) -> list[int]:
    """Product mask: P-cores only. Never a thin tail of E-cores.

    F4-R.3. First-N on the 1355U was 4 P + 2 E; EcoQoS parked on the two
    and cost 8×. The mix that added E-cores was the declared candidate; on
    this 14700HX it lost to P-only (1.76× slower in EcoQoS-on) and so did
    removing the mask (`livre`, 1.90× slower). Homogeneous machines keep
    first-N. When there are fewer P-logicals than n, return the P-logicals
    rather than padding with E-cores.
    """
    p, e, n = _partes(n_usados, topo)
    if not p or not e:
        return list(range(n))
    if len(p) >= n:
        return p[:n]
    return list(p)


def _partes(
    n_usados: int, topo: dict[str, Any] | None
) -> tuple[list[int], list[int], int]:
    if topo is None:
        topo = topologia()
    p = [int(x) for x in (topo.get("p") or [])]
    e = [int(x) for x in (topo.get("e") or [])]
    n_logicos = int(topo.get("logicos") or (len(p) + len(e)) or 1)
    n = max(1, min(int(n_usados), n_logicos))
    return p, e, n


def observar() -> dict[str, Any]:
    """What every speed observation must record. Never raises."""
    dados: dict[str, Any] = {
        "tomada": None,
        "bateria_pct": None,
        "mhz": None,
        "fisicos": None,
        "ecoqos": ecoqos_ativo(),
        "topologia": topologia(),
    }
    try:
        import psutil

        bateria = psutil.sensors_battery()
        dados["tomada"] = None if bateria is None else bool(bateria.power_plugged)
        dados["bateria_pct"] = None if bateria is None else bateria.percent
        freq = psutil.cpu_freq()
        dados["mhz"] = None if freq is None else round(freq.current)
        dados["fisicos"] = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001 — probe de hardware
        pass
    return dados


def _ecoqos_windows(ligar: bool | None) -> bool | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Estado(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        # Without argtypes ctypes passes HANDLE as c_int and truncates it
        # on 64-bit — Set/Get then fail and EcoQoS looks unset.
        kernel32.SetProcessInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        kernel32.SetProcessInformation.restype = wintypes.BOOL
        kernel32.GetProcessInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        kernel32.GetProcessInformation.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if ligar is not None:
            pedido = Estado(
                PROCESS_POWER_THROTTLING_CURRENT_VERSION,
                PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
                PROCESS_POWER_THROTTLING_EXECUTION_SPEED if ligar else 0,
            )
            if not kernel32.SetProcessInformation(
                handle, ProcessPowerThrottling, ctypes.byref(pedido), ctypes.sizeof(pedido)
            ):
                return None
        lido = Estado(PROCESS_POWER_THROTTLING_CURRENT_VERSION, 0, 0)
        if not kernel32.GetProcessInformation(
            handle, ProcessPowerThrottling, ctypes.byref(lido), ctypes.sizeof(lido)
        ):
            return None
        return bool(lido.StateMask & PROCESS_POWER_THROTTLING_EXECUTION_SPEED)
    except Exception:  # noqa: BLE001 — probe de hardware
        return None


def _nucleos_windows() -> list[dict[str, Any]]:
    """One entry per physical core: SMT flag and logical-processor indexes."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = kernel32.GetLogicalProcessorInformationEx
        fn.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        fn.restype = wintypes.BOOL
        needed = wintypes.DWORD(0)
        fn(RelationProcessorCore, None, ctypes.byref(needed))
        if needed.value < 8:
            return []
        buf = (ctypes.c_byte * needed.value)()
        if not fn(RelationProcessorCore, buf, ctypes.byref(needed)):
            return []
        return _ler_nucleos(bytes(buf), needed.value)
    except Exception:  # noqa: BLE001 — probe de hardware
        return []


def _ler_nucleos(raw: bytes, n: int) -> list[dict[str, Any]]:
    """Parse SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX / RelationProcessorCore."""
    fora: list[dict[str, Any]] = []
    off = 0
    while off + 40 <= n:
        size = int.from_bytes(raw[off + 4 : off + 8], "little")
        if size < 40:
            break
        flags = raw[off + 8]
        mask = int.from_bytes(raw[off + 32 : off + 40], "little")
        lps = [b for b in range(64) if mask & (1 << b)]
        fora.append({"smt": bool(flags & 1), "lps": lps})
        off += size
    return fora
