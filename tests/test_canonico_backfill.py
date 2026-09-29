from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from segundocerebro.index.canonico_backfill import (
    _coluna_raiz,
    _processar_linha,
    main,
    reconstruir_parse_store,
)
from segundocerebro.index.store import Store
from segundocerebro.ingest.parse_cache import canonicos_disponiveis
from segundocerebro.ingest.parsers import parser_version_for


def test_registro_legacy_usa_a_coluna_raiz() -> None:
    conexao = sqlite3.connect(":memory:")
    conexao.row_factory = sqlite3.Row
    conexao.execute("CREATE TABLE documentos (path TEXT PRIMARY KEY, root_id TEXT, raiz TEXT)")

    assert _coluna_raiz(conexao) == "raiz"
    conexao.close()


def test_usa_versao_efetiva_com_raster_no_docx(tmp_path: Path, monkeypatch) -> None:
    conexao = sqlite3.connect(":memory:")
    conexao.row_factory = sqlite3.Row
    linha = conexao.execute(
        "SELECT 'doc.docx' AS path, 'VCE' AS root_id, 'sha' AS sha256, "
        "'3+raster' AS parser, 'ok' AS status, 1 AS n_chunks, 1 AS tamanho, 1.0 AS mtime"
    ).fetchone()
    monkeypatch.setattr(
        "segundocerebro.index.canonico_backfill.versao_efetiva",
        lambda _extensao: "3+raster",
    )
    monkeypatch.setattr(
        "segundocerebro.index.canonico_backfill.canonicos_disponiveis",
        lambda *_args, **_kwargs: iter([(None, None)]),
    )

    estado = _processar_linha(linha, tmp_path / "indice", {})

    assert estado == "existente"
    conexao.close()


def _registrar_documento(
    indice: Path,
    raiz: Path,
    relativo: str,
    *,
    parser: str | None = None,
    conteudo: bytes = b"Registro sintetico para o backfill.\n",
) -> str:
    arquivo = raiz / relativo
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(conteudo)
    stat = arquivo.stat()
    sha256 = hashlib.sha256(conteudo).hexdigest()
    store = Store(indice, dim=8)
    try:
        store.registrar_documento(
            path=relativo,
            raiz="VCE",
            tamanho=stat.st_size,
            mtime=stat.st_mtime,
            status="ok",
            sha256=sha256,
            n_chunks=1,
            model_id="fixture:8",
            chunker="texto:1",
            parser=parser or parser_version_for(Path(relativo).suffix),
        )
        store.con.commit()
        store.tabela.add(
            [
                {
                    "id": f"fixture-{relativo}",
                    "ocorrencia_id": f"VCE\0{relativo}",
                    "path": relativo,
                    "ordinal": 0,
                    "kind": "paragrafo",
                    "ext": Path(relativo).suffix.lower(),
                    "mtime": stat.st_mtime,
                    "model_id": "fixture:8",
                    "vetor": [0.0] * 8,
                }
            ]
        )
    finally:
        store.fechar()
    return sha256


def test_recupera_txt_sem_alterar_vetores_e_reconhece_cache_atual(tmp_path: Path) -> None:
    indice = tmp_path / "indice"
    raiz = tmp_path / "corpus"
    sha256 = _registrar_documento(indice, raiz, "Notas/fixture.txt")
    store = Store(indice, dim=8)
    try:
        vetores_antes = store.tabela.count_rows()
    finally:
        store.fechar()

    resultado = reconstruir_parse_store(indice, {"VCE": raiz})

    assert resultado.recuperados == 1
    assert resultado.existentes == 0
    recuperado = next(canonicos_disponiveis(indice, sha256, ".txt"), None)
    assert recuperado is not None
    assert "Registro sintetico para o backfill" in recuperado[1].markdown

    store = Store(indice, dim=8)
    try:
        assert store.tabela.count_rows() == vetores_antes == 1
    finally:
        store.fechar()

    segunda = reconstruir_parse_store(indice, {"VCE": raiz})
    assert segunda.recuperados == 0
    assert segunda.existentes == 1


def test_ignora_parser_antigo_e_pptx(tmp_path: Path) -> None:
    indice = tmp_path / "indice"
    raiz = tmp_path / "corpus"
    _registrar_documento(indice, raiz, "antigo.txt", parser="versao-antiga")
    _registrar_documento(
        indice,
        raiz,
        "grafico.pptx",
        conteudo=b"fixture que nunca deve ser interpretada pelo backfill",
    )

    resultado = reconstruir_parse_store(indice, {"VCE": raiz})

    assert resultado.recuperados == 0
    assert resultado.ignorados == 2


def test_nao_abre_arquivo_que_mudou_desde_o_registro(tmp_path: Path) -> None:
    indice = tmp_path / "indice"
    raiz = tmp_path / "corpus"
    _registrar_documento(indice, raiz, "mudou.txt")
    (raiz / "mudou.txt").write_text("conteúdo novo", encoding="utf-8")

    resultado = reconstruir_parse_store(indice, {"VCE": raiz})

    assert resultado.recuperados == 0
    assert resultado.ignorados == 1


def test_comando_cli_usa_base_e_indice_configurados(tmp_path: Path, monkeypatch) -> None:
    indice = tmp_path / "indice"
    raiz = tmp_path / "corpus"
    _registrar_documento(indice, raiz, "Notas/fixture.txt")
    base = SimpleNamespace(id="fixture", raizes=(SimpleNamespace(name="VCE", path=raiz),))
    config = SimpleNamespace(base=lambda identificador: base)
    monkeypatch.setattr("segundocerebro.index.canonico_backfill.carregar", lambda _path: config)

    codigo = main(["--base", "fixture", "--indice", str(indice)])

    assert codigo == 0
