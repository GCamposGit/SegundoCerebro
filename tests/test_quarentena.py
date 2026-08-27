"""R1.4: a poisonous file is quarantined; the wave finishes; the parent lives."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from segundocerebro.census import Config, RootSpec
from segundocerebro.index.isolamento import parse_isolado, timeout_para
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import BACKOFF_QUARENTENA_S, MAX_TENTATIVAS_QUARENTENA, Store
from tests.test_index import DIM, EmbedderFalso


def _zip_que_nao_e_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nao_e_office.txt", "lixo da VCE")
    return buf.getvalue()


def test_timeout_cresce_com_o_tamanho() -> None:
    assert timeout_para(0) == 60.0
    assert timeout_para(2_000_000) == 80.0


def test_arquivo_vazio_binario_vira_erro_sem_subprocesso(tmp_path: Path) -> None:
    alvo = tmp_path / "vazio.pdf"
    alvo.write_bytes(b"")
    resultado = parse_isolado(str(alvo))
    assert resultado.status.value == "erro"
    assert "0 bytes" in resultado.detail


def test_subprocesso_abortado_nao_derruba_o_pai(tmp_path: Path) -> None:
    """Acceptance: the indexer survives kill -9 of the parse child.

    `os.abort()` is the same class as a native parser abort: the child dies
    without returning a ParseResult. The parent has to log one line and go on.
    """
    alvo = tmp_path / "x.pdf"
    alvo.write_bytes(b"%PDF-1.4\n")
    resultado = parse_isolado(str(alvo), worker="abort", indice=tmp_path)
    assert resultado.status.value == "erro"
    assert "subprocesso morreu" in resultado.detail
    log = tmp_path / "quarentena.log"
    assert log.is_file()
    assert "subprocesso morreu" in log.read_text(encoding="utf-8")


def test_subprocesso_pendurado_estoura_o_timeout(tmp_path: Path) -> None:
    alvo = tmp_path / "x.pdf"
    alvo.write_bytes(b"%PDF-1.4\n")
    inicio = datetime.now(timezone.utc)
    resultado = parse_isolado(str(alvo), worker="hang", timeout=1.0, indice=tmp_path)
    decorrido = (datetime.now(timezone.utc) - inicio).total_seconds()
    assert resultado.status.value == "erro"
    assert "timeout" in resultado.detail
    assert decorrido < 20, "the parent must kill the child, not wait for it"


def test_backoff_e_teto_de_tentativas(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", DIM)
    agora = datetime(2026, 8, 27, tzinfo=timezone.utc)
    store.registrar_quarentena("a.pdf", hash="aaa", motivo="timeout", agora=agora, backoff_s=60)
    assert store.deve_pular_quarentena("a.pdf", "aaa", agora=agora)
    assert store.deve_pular_quarentena("a.pdf", "aaa", agora=agora + timedelta(seconds=30))
    assert not store.deve_pular_quarentena("a.pdf", "aaa", agora=agora + timedelta(seconds=61))
    store.registrar_quarentena(
        "a.pdf", hash="aaa", motivo="timeout", agora=agora + timedelta(seconds=61), backoff_s=60
    )
    item = store.quarentena_de("a.pdf")
    assert item is not None
    assert item.tentativas == MAX_TENTATIVAS_QUARENTENA
    assert store.deve_pular_quarentena("a.pdf", "aaa", agora=agora + timedelta(days=30))
    # Replacing the file (new hash) clears the row.
    assert not store.deve_pular_quarentena("a.pdf", "bbb", agora=agora + timedelta(days=30))
    assert store.quarentena_de("a.pdf") is None
    store.fechar()
    assert BACKOFF_QUARENTENA_S == 3600.0


def test_onda_com_tres_venenosos_termina_e_quarentena(tmp_path: Path) -> None:
    """Acceptance: truncated PDF, ZIP-as-docx, 0-byte file — wave completes, 3 quarantined.

    Plus one honest Markdown so the run actually indexes something. Zero
    unhandled exceptions is the assertion that we got a Progresso back.
    """
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "ok.md").write_text("# VCE\nContrato NN-ACME-001 da Várzea Clara Energia.\n", encoding="utf-8")
    (raiz / "cortado.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")
    (raiz / "mentira.docx").write_bytes(_zip_que_nao_e_docx())
    (raiz / "vazio.pdf").write_bytes(b"")
    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(
        Config(roots=[RootSpec(name="teste", path=raiz)]),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
    )
    assert not progresso.interrompido
    nomes = {item.path for item in store.listar_quarentena()}
    assert nomes == {"cortado.pdf", "mentira.docx", "vazio.pdf"}
    assert progresso.quarentena == 3
    assert store.estado_documento("ok.md") is not None
    assert store.estado_documento("ok.md").status == "ok"
    store.fechar()
