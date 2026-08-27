"""LibreOffice is optional. Missing binary is None; a hung convert must not orphan."""

from __future__ import annotations

import subprocess
from pathlib import Path

from segundocerebro.ingest.converters.libreoffice import (
    _matar,
    encontrar_soffice,
    recalcular_xlsx,
)


def test_soffice_ausente_devolve_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.shutil.which", lambda nome: None
    )
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice._CANDIDATOS", ()
    )

    assert encontrar_soffice() is None
    assert recalcular_xlsx(b"nao-e-xlsx") is None


def test_timeout_mata_a_arvore_do_processo(monkeypatch) -> None:
    class Proc:
        def __init__(self) -> None:
            self.pid = 4242
            self.returncode = None

        def communicate(self, timeout=None):  # noqa: ANN001
            raise subprocess.TimeoutExpired(cmd="soffice", timeout=timeout)

        def poll(self):
            return None

        def wait(self, timeout=None):  # noqa: ANN001
            return None

        def kill(self) -> None:
            return None

    proc = Proc()
    matou: list[object] = []
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.encontrar_soffice",
        lambda: "soffice",
    )
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.subprocess.Popen",
        lambda *a, **k: proc,
    )
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice._matar",
        lambda p: matou.append(p),
    )

    assert recalcular_xlsx(b"x") is None
    assert matou == [proc]


def test_matar_nao_explode_se_ja_terminou() -> None:
    class Morto:
        pid = 1

        def poll(self):
            return 0

    _matar(Morto())  # type: ignore[arg-type]


def test_encontrar_soffice_aceita_caminho_padrao(monkeypatch, tmp_path: Path) -> None:
    falso = tmp_path / "soffice.exe"
    falso.write_bytes(b"x")
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.shutil.which", lambda nome: None
    )
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice._CANDIDATOS", (falso,)
    )

    assert encontrar_soffice() == str(falso)
