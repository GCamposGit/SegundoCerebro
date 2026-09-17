"""CPU continua o padrão; CUDA só quando a placa e o runtime realmente servem."""

from __future__ import annotations

import pytest

from segundocerebro.index.cuda_runtime import DiagnosticoCuda, EP_AUSENTE, OK, resolver_provider


def test_sem_runtime_cuda_continua_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(False, EP_AUSENTE, "sem ep"),
    )
    assert resolver_provider(None) == "cpu"


def test_cuda_entra_quando_a_placa_responde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(True, OK, "ok"),
    )
    assert resolver_provider(None) == "cuda"


def test_env_cpu_vence_mesmo_com_placa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cpu")
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.diagnosticar",
        lambda **_k: DiagnosticoCuda(True, OK, "ok"),
    )
    assert resolver_provider(None) == "cpu"
