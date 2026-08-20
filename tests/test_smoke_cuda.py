"""O smoke da F3.6 não pode levantar só porque a máquina não tem GPU hoje."""

from __future__ import annotations

from segundocerebro.index.smoke_cuda import _gpus


def test_gpus_devolve_lista() -> None:
    assert isinstance(_gpus(), list)
