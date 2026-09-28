"""BUSCA-BURACO: o hit declara o buraco e o panorama conta ok sem canônico.

O teste tem de falhar com o código antigo: sem `limitacoes` no trecho e sem
`ok_sem_canonico` no panorama. A ordem dos ids é a do ranqueador, no mesmo índice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, ParsedDoc
from segundocerebro.ingest.ocr import VERSAO as OCR_VERSAO
from segundocerebro.ingest.parse_store import ROTA_OCR, Chave, ParseStore, assinatura_do_motor
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.mcp.busca import LIMITE_DIGESTO, LIMITE_PLACEHOLDER, LIMITE_VAZIO
from segundocerebro.mcp.server import Recursos, construir
from tests.falsos import EmbedderFalso

SHA_DIGESTO = "a" * 64
SHA_PRESENTE = "b" * 64
SHA_AUSENTE = "c" * 64
SHA_VELHO = "d" * 64
SHA_OCR = "e" * 64


def _chamar(servidor, nome: str, **kwargs) -> dict:
    resultado = asyncio.run(servidor.call_tool(nome, kwargs))
    assert not resultado.is_error, resultado
    return resultado.structured_content


def _gravar_canonico(indice: Path, sha: str, parser: str, meta: dict[str, str], *, rota: str = "") -> None:
    canonico = renderizar(
        ParsedDoc("vce.txt", (Block(("VCE",), "texto de fixture"),), meta)
    )
    if rota == ROTA_OCR:
        chave = Chave(sha, parser, rota=ROTA_OCR, motor=assinatura_do_motor(ROTA_OCR))
    else:
        chave = Chave(sha, parser)
    ParseStore(indice).gravar(chave, canonico)


def _servidor_de_busca(tmp_path: Path):
    from segundocerebro.index.store import Store
    from segundocerebro.ingest.chunking import Chunk
    from segundocerebro.ingest.document import BlockKind
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    emb = EmbedderFalso()
    store = Store(tmp_path / "indice", dim=emb.dim)
    specs = [
        ("id-digesto", "VCE/digesto-alfa.txt", "Digesto da medicao VCE alfa.", "ok", SHA_DIGESTO),
        ("id-vazio", "VCE/scan-beta.txt", "Scan sem texto VCE beta.", "vazio", ""),
        ("id-nuvem", "VCE/nuvem-gama.txt", "Placeholder de nuvem VCE gama.", "placeholder", ""),
        ("id-limpo", "VCE/limpo-delta.txt", "Texto integral VCE delta.", "ok", ""),
    ]
    chunks = [
        Chunk(
            id=chunk_id,
            doc_path=caminho,
            ordinal=1,
            heading_path=("VCE",),
            locator="p. 1",
            kind=BlockKind.TEXT,
            text=texto,
        )
        for chunk_id, caminho, texto, _status, _sha in specs
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)
    for i, (_chunk_id, caminho, _texto, status, sha) in enumerate(specs):
        store.registrar_documento(
            path=caminho,
            raiz="r",
            tamanho=10 + i,
            mtime=float(i + 1),
            status=status,
            sha256=sha,
            n_chunks=1,
            model_id=emb.model_id,
            parser=parser_version_for(".txt"),
        )
    store.commit()
    _gravar_canonico(
        store.diretorio,
        SHA_DIGESTO,
        parser_version_for(".txt"),
        {"abas_em_digesto": "C:/segredo/planilha"},
    )
    recursos = Recursos(indice=store.diretorio, modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    return construir(recursos), recursos, store


def test_hit_declara_digesto_vazio_e_placeholder(tmp_path: Path) -> None:
    servidor, _recursos, store = _servidor_de_busca(tmp_path)
    consultas = {
        "digesto da medicao": ("VCE/digesto-alfa.txt", LIMITE_DIGESTO),
        "scan sem texto": ("VCE/scan-beta.txt", LIMITE_VAZIO),
        "placeholder de nuvem": ("VCE/nuvem-gama.txt", LIMITE_PLACEHOLDER),
    }
    for consulta, (arquivo, limite) in consultas.items():
        trechos = _chamar(servidor, "search", consulta=consulta, k=4, contexto=0)["trechos"]
        alvo = next(t for t in trechos if t["arquivo"] == arquivo)
        assert limite in alvo["limitacoes"]
        assert "segredo" not in str(alvo)
    limpo = _chamar(servidor, "search", consulta="texto integral", k=4, contexto=0)["trechos"]
    alvo_limpo = next(t for t in limpo if t["arquivo"] == "VCE/limpo-delta.txt")
    assert "limitacoes" not in alvo_limpo
    store.fechar()


def test_ordem_dos_ids_segue_o_ranqueador(tmp_path: Path) -> None:
    servidor, recursos, store = _servidor_de_busca(tmp_path)
    acertos = recursos.busca.buscar_chunks(
        "VCE",
        k=8,
        contexto=0,
        pasta="",
        incluir_versoes_antigas=False,
        depois_de="",
        antes_de="",
        root_id="",
    )
    saida = _chamar(servidor, "search", consulta="VCE", k=8, contexto=0)
    assert [t["id"] for t in saida["trechos"]] == [a.chunk_id for a in acertos]
    assert len(saida["trechos"]) >= 2
    store.fechar()


def test_limitacao_consulta_o_registro_uma_vez(tmp_path: Path) -> None:
    servidor, recursos, store = _servidor_de_busca(tmp_path)
    vistas: list[str] = []

    def rastrear(sql: str) -> None:
        if "sha256, parser FROM documentos" in sql:
            vistas.append(sql)

    store.con.set_trace_callback(rastrear)
    _chamar(servidor, "search", consulta="VCE", k=8, contexto=0)
    store.con.set_trace_callback(None)
    assert len(vistas) == 1
    assert recursos.store is store
    store.fechar()


def test_descricao_do_search_nao_manda_abrir_o_original(tmp_path: Path) -> None:
    servidor = construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1))
    desc = next(t.description or "" for t in asyncio.run(servidor.list_tools()) if t.name == "search")
    assert "incluir_versoes_antigas" in desc
    assert "minuta antiga" in desc
    assert "por fora" in desc


def test_overview_conta_ok_sem_canonico_sem_abrir_original(tmp_path: Path, monkeypatch) -> None:
    from segundocerebro.index.store import Store
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    assert parser_version_for(".txt") != "0"
    emb = EmbedderFalso()
    store = Store(tmp_path / "indice", dim=emb.dim)
    docs = [
        ("VCE/presente.txt", SHA_PRESENTE, parser_version_for(".txt")),
        ("VCE/ausente.txt", SHA_AUSENTE, parser_version_for(".txt")),
        ("VCE/velho.txt", SHA_VELHO, "0"),
        ("VCE/scan.pdf", SHA_OCR, OCR_VERSAO),
    ]
    for i, (caminho, sha, parser) in enumerate(docs):
        store.registrar_documento(
            path=caminho,
            raiz="r",
            tamanho=20 + i,
            mtime=float(i + 1),
            status="ok",
            sha256=sha,
            n_chunks=1,
            model_id=emb.model_id,
            parser=parser,
        )
    store.commit()
    _gravar_canonico(store.diretorio, SHA_PRESENTE, parser_version_for(".txt"), {})
    _gravar_canonico(store.diretorio, SHA_VELHO, "0", {})
    _gravar_canonico(store.diretorio, SHA_OCR, OCR_VERSAO, {}, rota=ROTA_OCR)

    real_read = Path.read_bytes

    def vigia(self: Path, *args, **kwargs):
        nome = self.as_posix()
        if nome.endswith(("presente.txt", "ausente.txt", "velho.txt", "scan.pdf")):
            raise AssertionError(f"abriu o original: {self}")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", vigia)
    recursos = Recursos(indice=store.diretorio, modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    dados = _chamar(construir(recursos), "overview")
    assert dados["status"]["ok_sem_canonico"] == 2
    assert not (tmp_path / "VCE").exists()
    store.fechar()
