"""Variable-length list<float64> is not a Lance vector; rewrite without reparse."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from segundocerebro.index.backup_manifesto import BackupRecusado
from segundocerebro.index.store import Store
from segundocerebro.index.trava import TravaDeIndice
from segundocerebro.index.vetores_tipo import (
    TipoVetorInvalido,
    e_vetor_fixo,
    main,
    reparar,
)
from tests.falsos import DIM, chunk

TEXTO = "O contrato CT-VCE-2024-0142 define o reajuste anual da Várzea Clara Energia."


def _indice_ok(tmp_path: Path) -> Path:
    indice = tmp_path / "ok"
    store = Store(indice, DIM)
    c = chunk("c-vce-1", "contrato.md", 0, TEXTO)
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    store.gravar_chunks([c], [vetor], mtime=1.0, model_id="falso:8")
    store.registrar_documento(
        path="contrato.md",
        raiz="pessoal",
        tamanho=len(TEXTO),
        mtime=1.0,
        sha256="a" * 64,
        status="ok",
        n_chunks=1,
        model_id="falso:8",
        chunker="2",
    )
    store.commit()
    store.fechar()
    return indice


def _quebrar_tipo(indice: Path) -> None:
    """Reproduce the FND-01b write: pylist infers list<float64>."""
    import lancedb

    from segundocerebro.index.lancedb_recursos import fechar_recursos

    lance = indice / "vetores.lance"
    db = lancedb.connect(str(lance))
    tabela = db.open_table("vetores")
    linhas = tabela.to_arrow().to_pylist()
    fechar_recursos(tabela, db)
    novo = indice / "vetores.lance.novo"
    if novo.exists():
        import shutil

        shutil.rmtree(novo)
    novo_db = lancedb.connect(str(novo))
    nova = novo_db.create_table("vetores", data=pa.Table.from_pylist(linhas))
    fechar_recursos(nova, novo_db)
    import gc
    import shutil

    gc.collect()
    shutil.rmtree(lance)
    novo.rename(lance)


def test_from_pylist_infere_lista_variavel_float64() -> None:
    tabela = pa.Table.from_pylist([{"id": "c1", "vetor": [0.1] * DIM}])
    tipo = tabela.schema.field("vetor").type
    assert not e_vetor_fixo(tipo, DIM)
    assert getattr(tipo, "list_size", None) in (None, -1)


def test_lista_variavel_recusa_busca_densa(tmp_path: Path) -> None:
    indice = _indice_ok(tmp_path)
    _quebrar_tipo(indice)
    store = Store(indice, DIM)
    try:
        tipo = store.tabela.schema.field("vetor").type
        assert not e_vetor_fixo(tipo, DIM)
        with pytest.raises(TipoVetorInvalido) as exc:
            store.buscar_denso(np.ones(DIM, dtype=np.float32), 1)
        assert exc.value.codigo == "tipo_vetor"
        assert "vetores_tipo" in exc.value.acao
    finally:
        store.fechar()


def test_reparar_converte_sem_tocar_registro(tmp_path: Path) -> None:
    indice = _indice_ok(tmp_path)
    _quebrar_tipo(indice)
    antes = (indice / "registro.db").read_bytes()
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)

    relato = reparar(indice)
    assert relato["alterado"] is True
    assert relato["linhas"] == 1
    assert relato["dim"] == DIM
    assert (indice / "registro.db").read_bytes() == antes

    store = Store(indice, DIM)
    try:
        tipo = store.tabela.schema.field("vetor").type
        assert e_vetor_fixo(tipo, DIM)
        hits = store.buscar_denso(vetor, 1)
        assert [h.id for h in hits] == ["c-vce-1"]
        lexical = store.buscar_lexical("CT-VCE-2024-0142", 5)
        assert [h.id for h in lexical] == ["c-vce-1"]
    finally:
        store.fechar()


def test_reparar_e_idempotente_quando_ja_e_vetor(tmp_path: Path) -> None:
    indice = _indice_ok(tmp_path)
    primeiro = reparar(indice)
    assert primeiro["alterado"] is False
    segundo = reparar(indice)
    assert segundo["alterado"] is False
    store = Store(indice, DIM)
    try:
        vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
        assert [h.id for h in store.buscar_denso(vetor, 1)] == ["c-vce-1"]
    finally:
        store.fechar()


def test_reparar_recusa_indice_em_uso(tmp_path: Path) -> None:
    indice = _indice_ok(tmp_path)
    _quebrar_tipo(indice)
    with TravaDeIndice(indice):
        with pytest.raises(BackupRecusado) as exc:
            reparar(indice)
    assert exc.value.codigo == "escritor_ativo"


def test_cli_recusa_indice_ausente(tmp_path: Path) -> None:
    codigo = main(["--indice", str(tmp_path / "nao-existe")])
    assert codigo == 2
