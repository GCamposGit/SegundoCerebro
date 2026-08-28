"""Reconciliação: remover do índice o que sumiu do disco, sem remover demais.

A parte que importa não é apagar — é **recusar apagar** na hora errada. Uma
passada interrompida enumera metade do corpus, e uma raiz mal configurada
enumera zero. Purgar sobre qualquer uma das duas destrói o índice em silêncio, e
com aparência de sucesso.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from segundocerebro.index.reconciliar import LIMITE_SEGURANCA, reconciliar
from segundocerebro.index.store import Store
from segundocerebro.ingest.chunking import Chunk
from segundocerebro.ingest.document import BlockKind


def montar(tmp_path: Path, documentos: dict[str, str]):  # noqa: ANN201
    """Índice com um chunk por documento; o valor do dict é o sha256 simulado."""
    store = Store(tmp_path / "indice", dim=4)
    for i, (path, sha) in enumerate(documentos.items()):
        chunk = Chunk(
            id=f"{path}#0",
            doc_path=path,
            ordinal=0,
            heading_path=(),
            locator="",
            kind=BlockKind.TEXT,
            text=f"conteudo de {path}",
        )
        store.gravar_chunks([chunk], [np.ones(4, dtype=np.float32)], 0.0, "m:4")
        store.registrar_documento(
            path=path, raiz="r", tamanho=1, mtime=0.0, status="ok", sha256=sha, n_chunks=1, model_id="m:4"
        )
    store.commit()
    return store


def test_remove_documento_que_sumiu_do_disco(tmp_path: Path) -> None:
    store = montar(tmp_path, {"a.pdf": "sha-a", "b.pdf": "sha-b", "c.pdf": "sha-c"})
    try:
        r = reconciliar(store, vistos={"a.pdf", "b.pdf"})

        assert r.removidos == ["c.pdf"]
        assert r.chunks_removidos == 1
        assert {x[0] for x in store.con.execute("select path from documentos")} == {"a.pdf", "b.pdf"}
        assert not store.con.execute("select 1 from chunks where path='c.pdf'").fetchall()
    finally:
        store.fechar()


def test_passada_incompleta_nunca_purga(tmp_path: Path) -> None:
    """O caso que destruiria o índice: hibernou no meio, metade não foi enumerada.

    Ausência de um caminho em `vistos` significa "não cheguei lá", e não "não
    existe mais".
    """
    store = montar(tmp_path, {"a.pdf": "sha-a", "b.pdf": "sha-b"})
    try:
        r = reconciliar(store, vistos={"a.pdf"}, completa=False)

        assert r.removidos == []
        assert "incompleta" in r.recusada
        assert store.con.execute("select count(*) from documentos").fetchone()[0] == 2
    finally:
        store.fechar()


def test_poucas_remocoes_nao_disparam_a_trava(tmp_path: Path) -> None:
    """Sem o piso absoluto, remover 1 de 3 seria 33% e travaria — mas 1 documento
    não pode ser sintoma de raiz errada."""
    store = montar(tmp_path, {"a.pdf": "sha-a", "b.pdf": "sha-b", "c.pdf": "sha-c"})
    try:
        r = reconciliar(store, vistos={"a.pdf", "b.pdf"})
        assert r.removidos == ["c.pdf"] and not r.recusada
    finally:
        store.fechar()


def test_recusa_quando_sumiu_gente_demais(tmp_path: Path) -> None:
    """Raiz errada ou unidade desconectada enumera pouco ou nada.

    Sem a trava, o resultado seria um índice zerado, sem erro, com log de
    sucesso — o pior modo de falha possível.
    """
    store = montar(tmp_path, {f"{i:02d}.pdf": f"sha-{i}" for i in range(40)})
    try:
        r = reconciliar(store, vistos={"00.pdf"})

        assert r.removidos == []
        assert "acima do limite" in r.recusada
        assert store.con.execute("select count(*) from documentos").fetchone()[0] == 40
    finally:
        store.fechar()


def test_forcar_vence_a_trava(tmp_path: Path) -> None:
    """A trava pede um humano; `--forcar-reconciliacao` é esse humano dizendo sim."""
    store = montar(tmp_path, {f"{i:02d}.pdf": f"sha-{i}" for i in range(40)})
    try:
        r = reconciliar(store, vistos={"00.pdf"}, forcar=True)

        assert len(r.removidos) == 39
        assert store.con.execute("select count(*) from documentos").fetchone()[0] == 1
    finally:
        store.fechar()


def test_faxina_dentro_do_limite_passa(tmp_path: Path) -> None:
    """A limpeza real de 14/08 removeu 8% — abaixo da trava, tem que passar sozinha."""
    documentos = {f"{i}.pdf": f"sha-{i}" for i in range(100)}
    store = montar(tmp_path, documentos)
    try:
        vistos = set(list(documentos)[:92])
        r = reconciliar(store, vistos=vistos)

        assert len(r.removidos) == 8
        assert not r.recusada
    finally:
        store.fechar()


def test_movido_e_reconhecido_por_conteudo_nao_por_nome(tmp_path: Path) -> None:
    """Nome igual em pasta diferente é coincidência; conteúdo igual não é.

    O acervo tem `Assignment.docx` em oito semanas do curso do MIT — casar por
    nome apontaria movimentação onde há só homônimo.
    """
    store = montar(tmp_path, {"velho/x.docx": "mesmo-sha", "novo/x.docx": "mesmo-sha"})
    try:
        r = reconciliar(store, vistos={"novo/x.docx"})

        assert r.removidos == ["velho/x.docx"]
        assert r.movidos == [("velho/x.docx", "novo/x.docx")]
        assert "movimentação" in r.resumo()
    finally:
        store.fechar()


def test_homonimo_com_conteudo_diferente_nao_e_movimentacao(tmp_path: Path) -> None:
    store = montar(tmp_path, {"semana8/Assignment.docx": "sha-8", "semana9/Assignment.docx": "sha-9"})
    try:
        r = reconciliar(store, vistos={"semana9/Assignment.docx"})

        assert r.removidos == ["semana8/Assignment.docx"]
        assert r.movidos == []
    finally:
        store.fechar()


def test_prefixo_limita_o_escopo(tmp_path: Path) -> None:
    """Passada com `--prefixo` não pode purgar o que ela nem tentou enumerar."""
    store = montar(tmp_path, {"A/1.pdf": "s1", "A/2.pdf": "s2", "B/1.pdf": "s3"})
    try:
        r = reconciliar(store, vistos={"A/1.pdf"}, prefixo="A/", forcar=True)

        assert r.removidos == ["A/2.pdf"]
        assert {x[0] for x in store.con.execute("select path from documentos")} == {"A/1.pdf", "B/1.pdf"}
    finally:
        store.fechar()


def test_indice_em_dia_nao_faz_nada(tmp_path: Path) -> None:
    store = montar(tmp_path, {"a.pdf": "sha-a"})
    try:
        r = reconciliar(store, vistos={"a.pdf"})

        assert not r.houve_mudanca and not r.recusada
        assert r.resumo() == "índice em dia com o disco"
    finally:
        store.fechar()


def test_limite_de_seguranca_e_declarado() -> None:
    assert 0 < LIMITE_SEGURANCA < 1
