"""Crash between SQLite and LanceDB recovers or aborts, never silent success (FND-02b)."""

from __future__ import annotations

import numpy as np
import pytest

from segundocerebro.index.operacoes import (
    FalhaInjetada,
    abandonar_escrita,
    apagar_vetores_do_path,
    ha_pendentes,
    injetar_falha_apos,
    publicar_completo,
    recuperar_pendentes,
)
from segundocerebro.index.store import Store
from segundocerebro.index.trava import TravaDeIndice
from tests.falsos import DIM, chunk

TEXTO = "O contrato CT-VCE-2024-0142 define o reajuste anual."
PATH = "contrato.md"


def _vetor() -> np.ndarray:
    return np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)


def _doc() -> dict:
    return {
        "path": PATH,
        "raiz": "principal",
        "tamanho": len(TEXTO),
        "mtime": 1.0,
        "sha256": "a" * 64,
        "status": "ok",
        "n_chunks": 1,
        "model_id": "falso:8",
        "chunker": "2",
        "parser": "md:1",
    }


def _publicar(store: Store) -> None:
    c = chunk("c-vce-1", PATH, 0, TEXTO)
    publicar_completo(store, [c], [_vetor()], 1.0, "falso:8", documento=_doc())


def _reabrir(diretorio) -> Store:
    return Store(diretorio, DIM)


def test_publicar_completo_reproduz_ids_e_consulta(store: Store) -> None:
    _publicar(store)
    assert not ha_pendentes(store)
    hits = store.buscar_lexical("CT-VCE-2024-0142", 5)
    assert [h.id for h in hits] == ["c-vce-1"]
    assert store.diagnosticar_integridade().integro


@pytest.mark.parametrize(
    "etapa",
    ["preparar", "deletar", "textos", "vetores", "carimbo", "verificar", "publicar"],
)
def test_crash_apos_etapa_recupera_ou_aborta_consistente(tmp_path, etapa: str) -> None:
    diretorio = tmp_path / "indice"
    store = Store(diretorio, DIM)
    injetar_falha_apos(etapa)
    with pytest.raises(FalhaInjetada) as exc:
        _publicar(store)
    assert exc.value.etapa == etapa
    abandonar_escrita(store)
    injetar_falha_apos(None)

    de_novo = _reabrir(diretorio)
    assert not ha_pendentes(de_novo)
    if (diretorio / "vetores.lance").is_dir():
        _ = de_novo.tabela
    cons = de_novo.diagnosticar_integridade()
    assert cons.integro or cons.status in {"vazio", "rascunho_pendente"}
    # Second recovery is a no-op.
    assert recuperar_pendentes(de_novo) == 0
    de_novo.fechar()


def test_duas_retomadas_sao_idempotentes(tmp_path) -> None:
    diretorio = tmp_path / "indice"
    store = Store(diretorio, DIM)
    injetar_falha_apos("vetores")
    with pytest.raises(FalhaInjetada):
        _publicar(store)
    abandonar_escrita(store)
    injetar_falha_apos(None)
    um = _reabrir(diretorio)
    ids_um = [h.id for h in um.buscar_lexical("CT-VCE-2024-0142", 5)]
    recuperar_pendentes(um)
    dois = _reabrir(diretorio)
    ids_dois = [h.id for h in dois.buscar_lexical("CT-VCE-2024-0142", 5)]
    assert ids_um == ids_dois
    assert not ha_pendentes(dois)
    um.fechar()
    dois.fechar()


def test_delete_que_nao_e_tabela_ausente_sobe(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """OSError on Lance delete is not 'table missing' — the journal must stay honest."""

    class _Boom:
        def delete(self, _pred: str) -> None:
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(
        "segundocerebro.index.operacoes._tabela_existente",
        lambda _s: _Boom(),
    )
    with pytest.raises(OSError, match="No space"):
        apagar_vetores_do_path(store, PATH)


def test_leitor_nao_recupera_com_indexador_vivo(tmp_path) -> None:
    diretorio = tmp_path / "indice"
    store = Store(diretorio, DIM)
    injetar_falha_apos("textos")
    with pytest.raises(FalhaInjetada):
        _publicar(store)
    abandonar_escrita(store)
    injetar_falha_apos(None)
    with TravaDeIndice(diretorio):
        leitor = Store(diretorio, DIM)
        assert ha_pendentes(leitor)
        leitor.fechar()
    recuperado = Store(diretorio, DIM)
    assert not ha_pendentes(recuperado)
    recuperado.fechar()


def test_indexar_recupera_journal_e_reprocessa(tmp_path) -> None:
    from segundocerebro.index.indexer import indexar
    from tests.falsos import EmbedderFalso, config_de_raiz

    raiz = tmp_path / "acervo"
    raiz.mkdir()
    (raiz / PATH).write_text(TEXTO, encoding="utf-8")
    diretorio = tmp_path / "indice"
    store = Store(diretorio, DIM)
    injetar_falha_apos("deletar")
    with pytest.raises(FalhaInjetada):
        _publicar(store)
    abandonar_escrita(store)
    injetar_falha_apos(None)
    store = Store(diretorio, DIM)
    cfg = config_de_raiz(raiz)
    indexar(cfg, store, EmbedderFalso(), publicar=False, reconciliar_ao_fim=False)
    assert not ha_pendentes(store)
    assert store.estatisticas()["documentos"] == 1
    assert store.diagnosticar_integridade().integro
    store.fechar()
