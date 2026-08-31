"""Watcher: disk events become `indexar --prefixo`, without a new IPC.

The guarantees that matter:

- creating a `.txt` under a root is indexed;
- deleting it drops it from the index;
- a cloud placeholder is never opened;
- two watchers on the same index refuse;
- cancel is `comando.txt`, the same IPC as the indexer.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from segundocerebro.census import Config, RootSpec
from segundocerebro.index.indexer import Progresso
from segundocerebro.index.store import Store
from segundocerebro.index.usn import Journal, Registro
from segundocerebro.index.watcher import (
    NOME_DA_TRAVA,
    Observador,
    ObservadorOcupado,
    TravaDeObservador,
)
from tests.falsos import DIM, EmbedderFalso, FonteFalsa, config_de_raiz


def _base(tmp_path: Path) -> tuple[Path, Config, Store, Observador]:
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    indice = tmp_path / "indice"
    cfg = config_de_raiz(raiz)
    store = Store(indice, DIM)
    obs = Observador(cfg, store, EmbedderFalso(), debounce_s=0)
    return raiz, cfg, store, obs


def test_criar_txt_dispara_indexacao(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("Contrato CT-VCE-2024-0142 com a Várzea Clara Energia.\n", encoding="utf-8")

    obs.enfileirar(alvo)
    feitos = obs.drenar()

    assert feitos == ["nota.txt"]
    estado = store.estado_documento("nota.txt")
    assert estado is not None
    assert estado.status == "ok"
    assert estado.n_chunks >= 1
    store.fechar()


def test_apagar_txt_sai_do_indice(tmp_path: Path) -> None:
    """O leigo apaga o Word e espera que a busca pare de devolver o trecho."""
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("Contrato CT-VCE-2024-0142.\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()
    assert store.estado_documento("nota.txt") is not None

    alvo.unlink()
    obs.enfileirar_apagado(alvo)
    feitos = obs.drenar()

    assert feitos == ["nota.txt"]
    assert store.estado_documento("nota.txt") is None
    store.fechar()


def test_salvar_por_cima_nao_esquece(tmp_path: Path) -> None:
    """Word grava com delete+create. O último evento vence: indexa, não apaga."""
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("primeira\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()

    alvo.unlink()
    obs.enfileirar_apagado(alvo)
    alvo.write_text("PO-VCE-007 vigente\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()

    estado = store.estado_documento("nota.txt")
    assert estado is not None
    assert estado.status == "ok"
    store.fechar()


def test_alterar_txt_reindexa(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("primeira versao\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()
    primeiro = store.estado_documento("nota.txt")
    assert primeiro is not None

    time.sleep(0.05)
    alvo.write_text("PO-VCE-007 vigente\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()
    segundo = store.estado_documento("nota.txt")
    assert segundo is not None
    assert segundo.sha256 != primeiro.sha256
    store.fechar()


def test_placeholder_de_nuvem_nao_e_aberto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "so_na_nuvem.txt"
    alvo.write_text("nao deveria ser lido\n", encoding="utf-8")

    monkeypatch.setattr("segundocerebro.index.watcher.is_cloud_only", lambda attrs: True)
    chamadas: list[str] = []

    def recusa(*args, **kwargs):  # noqa: ANN002, ANN003
        chamadas.append("indexar")
        return Progresso()

    obs._indexar = recusa
    obs.enfileirar(alvo)
    assert obs.drenar() == []
    assert chamadas == []
    assert store.estado_documento("so_na_nuvem.txt") is None
    store.fechar()


def test_dois_observadores_no_mesmo_indice_recusam(tmp_path: Path) -> None:
    _raiz, _cfg, store, obs = _base(tmp_path)
    outro = Observador(
        Config(roots=[RootSpec(name="x", path=tmp_path / "outra")]),
        store,
        EmbedderFalso(),
        debounce_s=0,
    )
    obs.ocupar()
    try:
        with pytest.raises(ObservadorOcupado, match="outro observador"):
            outro.ocupar()
        assert (store.diretorio / NOME_DA_TRAVA).exists()
    finally:
        obs.soltar()
        assert not (store.diretorio / NOME_DA_TRAVA).exists()
    store.fechar()


def test_trava_orfa_de_pid_morto_e_assumida(tmp_path: Path) -> None:
    marca = tmp_path / NOME_DA_TRAVA
    marca.write_text("999999,1.000", encoding="utf-8")
    with TravaDeObservador(tmp_path):
        assert marca.read_text(encoding="utf-8").startswith(str(os.getpid()))
    assert not marca.exists()


def test_extensao_sem_parser_e_ignorada(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "planta.dwg"
    alvo.write_bytes(b"binario")
    obs.enfileirar(alvo)
    assert obs.drenar() == []
    assert store.estado_documento("planta.dwg") is None
    store.fechar()


def test_arquivo_fora_da_raiz_e_ignorado(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    fora = tmp_path / "lado.txt"
    fora.write_text("CT-VCE-2024-0142\n", encoding="utf-8")
    obs.enfileirar(fora)
    assert obs.drenar() == []
    store.fechar()


def test_lock_do_office_e_ignorado(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "~$nota.txt"
    alvo.write_text("lixo\n", encoding="utf-8")
    obs.enfileirar(alvo)
    assert obs.drenar() == []
    store.fechar()


def test_watchdog_criar_arquivo_enfileira(tmp_path: Path) -> None:
    """O observer de verdade, não só o `enfileirar` chamado à mão."""
    raiz, _cfg, store, obs = _base(tmp_path)
    obs.debounce_s = 0.05
    observer = obs.iniciar_watchdog()
    try:
        (raiz / "viva.txt").write_text("PO-VCE-007\n", encoding="utf-8")
        deadline = time.monotonic() + 4
        feitos: list[str] = []
        while time.monotonic() < deadline:
            feitos = obs.drenar()
            if store.estado_documento("viva.txt") is not None:
                break
            time.sleep(0.1)
        assert store.estado_documento("viva.txt") is not None
        assert "viva.txt" in feitos or store.estado_documento("viva.txt").n_chunks >= 1
    finally:
        observer.stop()
        observer.join(timeout=3)
        store.fechar()


def test_watchdog_apagar_arquivo_sai_do_indice(tmp_path: Path) -> None:
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "viva.txt"
    alvo.write_text("CT-VCE-2024-0142\n", encoding="utf-8")
    obs.enfileirar(alvo)
    obs.drenar()
    assert store.estado_documento("viva.txt") is not None

    obs.debounce_s = 0.05
    observer = obs.iniciar_watchdog()
    try:
        alvo.unlink()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            obs.drenar()
            if store.estado_documento("viva.txt") is None:
                break
            time.sleep(0.1)
        assert store.estado_documento("viva.txt") is None
    finally:
        observer.stop()
        observer.join(timeout=3)
        store.fechar()


def test_ao_religar_usn_enfileira_o_que_mudou_desligado(tmp_path: Path) -> None:
    """Watcher off → file saved → catch-up indexes it. The USN extra."""
    raiz, _cfg, store, obs = _base(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("PO-VCE-007 vigente\n", encoding="utf-8")
    fonte = FonteFalsa(journal=Journal(journal_id=1, first_usn=0, next_usn=10))
    obs._fonte_usn = fonte
    assert obs.recuperar_ausencia() == []

    fonte.registros = [Registro(frn=1, reason=0x100, attrs=0x20)]
    fonte.caminhos = {1: alvo}
    fonte.journal = Journal(journal_id=1, first_usn=0, next_usn=20)
    assert obs.recuperar_ausencia() == ["nota.txt"]
    assert obs.drenar() == ["nota.txt"]
    estado = store.estado_documento("nota.txt")
    assert estado is not None
    assert estado.status == "ok"
    store.fechar()


def test_catch_up_roda_antes_do_watchdog() -> None:
    """If catch-up starts after the observer, the window between the two is lost."""
    import inspect

    from segundocerebro.index.watcher import Observador

    fonte = inspect.getsource(Observador.correr)
    assert fonte.index("recuperar_ausencia") < fonte.index("iniciar_watchdog")


def test_cancelar_por_comando_txt_encerra(tmp_path: Path) -> None:
    """O contrato de IPC é o mesmo da indexação: comando.txt, sem socket."""
    from segundocerebro.index.comando import pedir

    _raiz, _cfg, store, obs = _base(tmp_path)

    class Dummy:
        def stop(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
            return None

    obs.iniciar_watchdog = lambda: Dummy()  # type: ignore[method-assign]
    pedir(store.diretorio, "cancelar")
    obs.correr(intervalo=0.01, intervalo_usn=0)
    store.fechar()
