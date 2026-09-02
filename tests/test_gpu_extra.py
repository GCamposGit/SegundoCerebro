"""Q2 — extra [gpu] is the pin. CUDA 13 is a failed install, not a dirty venv.

The canary on this desktop: the full suite with a CUDA 13 GPU extra failed in
the indexer (45 tests). Cleaning the venv is not the package. The extra in
pyproject.toml must not be able to resolve to CUDA 13 or cuDNN 9, and if
onnxruntime-gpu is installed it must be the pinned 1.18.0 stack.

The guard is derived: pyproject extra, requirements-gpu.txt overlay, and
cuda_runtime.ORT_GPU_PINADO have to agree. An isolated case proves the
predicate without the real files, because a copy of the guard always agrees
with itself.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

from segundocerebro.index.cuda_runtime import (
    ORT_CUDA13,
    ORT_CUDNN9,
    ORT_GPU_PINADO,
)

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
OVERLAY = REPO / "requirements-gpu.txt"

_ORT_GPU = "onnxruntime-gpu"
_CUDA13 = Version(f"{ORT_CUDA13[0]}.{ORT_CUDA13[1]}.{ORT_CUDA13[2]}")
_CUDNN9 = Version(f"{ORT_CUDNN9[0]}.{ORT_CUDNN9[1]}.{ORT_CUDNN9[2]}")
_PINADO = Version(f"{ORT_GPU_PINADO[0]}.{ORT_GPU_PINADO[1]}.{ORT_GPU_PINADO[2]}")


def specs_que_puxam_runtime_proibido(specs: list[str]) -> list[str]:
    """Which requirement strings would install CUDA 13, cuDNN 9, or cu12/cu13.

    Pure. The test against pyproject and the isolated-case proof both call this.
    A copy of the predicate would pass today and miss the next extra.
    """
    ruins: list[str] = []
    for bruto in specs:
        texto = bruto.split("#", 1)[0].strip()
        if not texto:
            continue
        req = Requirement(texto)
        nome = req.name.lower().replace("_", "-")
        if any(marca in nome for marca in ("cu12", "cu13", "cuda12", "cuda13")):
            ruins.append(texto)
            continue
        if nome != _ORT_GPU:
            continue
        if req.specifier.contains(_CUDNN9, prereleases=True) or req.specifier.contains(
            _CUDA13, prereleases=True
        ):
            ruins.append(texto)
        elif not req.specifier.contains(_PINADO, prereleases=True):
            ruins.append(texto)
    return ruins


def _specs_do_extra_gpu() -> list[str]:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extra = pyproject["project"]["optional-dependencies"]["gpu"]
    assert extra, "extra [gpu] vazio — o pin saiu"
    return list(extra)


def _specs_do_overlay() -> list[str]:
    saida: list[str] = []
    for linha in OVERLAY.read_text(encoding="utf-8").splitlines():
        texto = linha.split("#", 1)[0].strip()
        if texto:
            saida.append(texto)
    assert saida, "requirements-gpu.txt sem pacotes — overlay GPU sumiu"
    return saida


def test_extra_gpu_nao_permite_cuda13_nem_cudnn9() -> None:
    """The extra the layperson types must not resolve to the stack that died here."""
    ruins = specs_que_puxam_runtime_proibido(_specs_do_extra_gpu())
    assert not ruins, (
        f"extra [gpu] aceitaria CUDA 13 / cuDNN 9 / cu12: {ruins}. "
        "O pin é onnxruntime-gpu==1.18.0 + nvidia-*-cu11. "
        "Instalar sem pin é o defeito; não se mede mais extras."
    )


def test_overlay_gpu_nao_permite_cuda13_nem_cudnn9() -> None:
    ruins = specs_que_puxam_runtime_proibido(_specs_do_overlay())
    assert not ruins, (
        f"requirements-gpu.txt aceitaria CUDA 13 / cuDNN 9 / cu12: {ruins}. "
        "O overlay tem de repetir o extra [gpu] e só acrescentar numpy<2."
    )


def test_overlay_repete_o_extra_e_so_acrescenta_numpy() -> None:
    """pyproject extra [gpu] is the source; the overlay must not drift.

    numpy<2 stays in the overlay because pip extras are a union and the CPU
    pin is numpy>=2 — the extra cannot express the contradiction.
    """
    extra = {Requirement(s).name.lower(): str(Requirement(s).specifier) for s in _specs_do_extra_gpu()}
    overlay = {Requirement(s).name.lower(): str(Requirement(s).specifier) for s in _specs_do_overlay()}
    faltando = sorted(nome for nome in extra if overlay.get(nome) != extra[nome])
    assert not faltando, (
        f"overlay GPU divergiu do extra [gpu] em {faltando}. "
        "Fonte única é pyproject.toml; requirements-gpu.txt só replica e soma numpy."
    )
    extras_a_mais = sorted(nome for nome in overlay if nome not in extra)
    assert extras_a_mais == ["numpy"], extras_a_mais
    numpy_spec = Requirement(f"numpy{overlay['numpy']}").specifier
    assert numpy_spec.contains(Version("1.26.4"), prereleases=True)
    assert not numpy_spec.contains(Version("2.0.0"), prereleases=True)


def test_pin_do_codigo_e_o_do_extra() -> None:
    """ORT_GPU_PINADO in cuda_runtime.py and the extra have to name the same wheel."""
    extra = [Requirement(s) for s in _specs_do_extra_gpu()]
    ort = next(r for r in extra if r.name.lower().replace("_", "-") == _ORT_GPU)
    assert ort.specifier.contains(_PINADO, prereleases=True)
    assert _PINADO < _CUDNN9 < _CUDA13


def test_a_guarda_reprova_cuda13_em_caso_isolado() -> None:
    """The predicate fails on CUDA 13 even when pyproject is still pinned.

    Proof against the real extra would pass by accident the day the extra is
    still 1.18.0. The isolated strings are the class.
    """
    assert specs_que_puxam_runtime_proibido(["onnxruntime-gpu==1.18.0"]) == []
    assert specs_que_puxam_runtime_proibido(["nvidia-cuda-runtime-cu11==11.8.89"]) == []
    assert specs_que_puxam_runtime_proibido(["onnxruntime-gpu>=1.27"]) == [
        "onnxruntime-gpu>=1.27"
    ]
    assert specs_que_puxam_runtime_proibido(["onnxruntime-gpu>=1.19,<1.27"]) == [
        "onnxruntime-gpu>=1.19,<1.27"
    ]
    assert specs_que_puxam_runtime_proibido(["nvidia-cuda-runtime-cu13==13.0.0"]) == [
        "nvidia-cuda-runtime-cu13==13.0.0"
    ]
    assert specs_que_puxam_runtime_proibido(["onnxruntime-gpu>=1.18"]) == [
        "onnxruntime-gpu>=1.18"
    ]


def test_se_gpu_instalado_nao_e_cuda13() -> None:
    """Canary: CUDA 13 on this desktop dropped 45 indexer tests.

    Skip-by-absence on CPU CI. Fail while a CUDA 13 (or cu12) wheel is present
    — cleaning the venv without the pin would go green and the next install
    would bring CUDA 13 back.
    """
    try:
        instalado = version(_ORT_GPU)
    except PackageNotFoundError:
        return
    assert Version(instalado) == _PINADO, (
        f"onnxruntime-gpu=={instalado} está instalado; o extra [gpu] pinado é "
        f"{_PINADO} (CUDA 11.8). ORT >= {_CUDA13} é CUDA 13 e derrubou o "
        "indexador neste desktop. O pacote é o pin, não limpar o venv: "
        "`pip uninstall onnxruntime onnxruntime-gpu` e "
        "`pip install -r requirements-gpu.txt`."
    )
    ruins = [
        d.metadata["Name"]
        for d in distributions()
        if any(marca in d.metadata["Name"].lower() for marca in ("cu12", "cu13"))
    ]
    assert not ruins, (
        f"pacotes CUDA 12/13 instalados: {ruins}. O extra [gpu] é cu11. "
        "Desinstale e reinstale o overlay pinado."
    )
