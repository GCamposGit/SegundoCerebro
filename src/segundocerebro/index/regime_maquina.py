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

import os
from typing import Any

ProcessPowerThrottling = 4
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
RelationProcessorCore = 0


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
