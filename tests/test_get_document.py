"""J.c-conteúdo: integridade, procedência, invalidação e isolamento sem modelo."""

from __future__ import annotations

import base64
import os
import random
from dataclasses import replace
from hashlib import sha256

import pytest

from segundocerebro.acesso.documento import LeitorDocumento
from segundocerebro.acesso.original import ErroLeitura
from segundocerebro.acesso.pagina_documento import MAX_BLOCOS, MAX_CHARS, paginar
from segundocerebro.census import RootSpec
from segundocerebro.config import Base, LimitesDeIndexacao
from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, ParsedDoc, ParseResult, ParseStatus
from segundocerebro.ingest.parse_store import Chave, ParseStore
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.ingest.reader import parse_file


@pytest.fixture
def acervo(store, tmp_path):
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    original = raiz / "Política 📄.md"
    original.write_text("# Política\n\nTexto integral com ação, 日本語 e 📄.\n\n## Prazos\n\nAté amanhã.", encoding="utf-8")
    base = Base(id="teste", indice=store.diretorio, raizes=(RootSpec("r", raiz),))
    sha = sha256(original.read_bytes()).hexdigest()
    store.registrar_documento(
        path=original.name, raiz="r", tamanho=original.stat().st_size,
        mtime=original.stat().st_mtime, sha256=sha, parser=parser_version_for(".md"),
        status="ok", n_chunks=0, model_id="falso:8",
    )
    store.commit()
    return LeitorDocumento(store, base), original, sha


def test_miss_reconstroi_sem_chunks_sem_mutar_original_ou_registro(acervo):
    leitor, original, _sha = acervo
    antes, db = original.read_bytes(), list(leitor.store.con.iterdump())
    esperado = renderizar(parse_file(str(original)).doc).markdown
    pagina = leitor.ler(original.name, max_chars=7)
    partes = [pagina["markdown"]]
    while "cursor_proximo" in pagina:
        pagina = leitor.ler(original.name, pagina["cursor_proximo"], 7)
        partes.append(pagina["markdown"])
    assert "".join(partes) == esperado
    assert pagina["completo"] and pagina["restante"] == 0
    assert pagina["documento"]["arquivo"] == original.name
    assert pagina["documento"]["total_chars"] == len(esperado)
    assert pagina["estrutura"]["versao"] == "blocos:1"
    assert leitor.ler(original.name)["blocos"][-1]["trilha"] == ["Política", "Prazos"]
    assert str(original.parent) not in str(pagina)
    assert original.read_bytes() == antes
    assert list(leitor.store.con.iterdump()) == db
    assert len(list(ParseStore(leitor.store.diretorio).entradas())) == 1


def test_hit_nao_abre_original_nem_chama_parser(acervo, monkeypatch):
    leitor, original, _sha = acervo
    primeira = leitor.ler(original.name, max_chars=5)
    def proibido(*_a, **_k):
        raise AssertionError("hit abriu original ou acionou parser")
    monkeypatch.setattr("segundocerebro.ingest.reader.read_bytes", proibido)
    monkeypatch.setattr("segundocerebro.index.isolamento.parse_isolado", proibido)
    outra = leitor.ler(original.name, primeira["cursor_proximo"], 5)
    assert outra["inicio"] == 5


def test_caminho_id_uri_sao_equivalentes(acervo):
    leitor, original, sha = acervo
    esperado = leitor.ler(original.name)
    assert leitor.ler(sha[:12]) == esperado
    assert leitor.ler(f"sc://teste/{sha[:12]}") == esperado
    assert leitor.ler("./" + original.name) == esperado


@pytest.mark.parametrize("ref", ["../segredo.md", "r/../segredo.md", "/etc/passwd", "C:/segredo.md", "C:segredo", "//servidor/pasta", "arquivo.md:ads", "a\x00b", "a//b"])
def test_recusa_caminhos_inseguros_antes_de_ler(acervo, ref, monkeypatch):
    leitor, _original, _sha = acervo
    monkeypatch.setattr("segundocerebro.acesso.documento.resolver", lambda *_a: pytest.fail("consultou referência insegura"))
    with pytest.raises(ErroLeitura, match="caminho relativo"):
        leitor.ler(ref)


def test_base_uri_nao_seleciona_outro_acervo(acervo):
    leitor, _original, sha = acervo
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(f"sc://outra/{sha[:12]}")
    assert erro.value.codigo == "referencia_invalida"


@pytest.mark.parametrize("cursor", ["", "x", "💣", "a" * 257, 0, -1, True, base64.b64encode(b'["gd:1", "x", 1]').decode()])
def test_cursor_invalido_e_barato(acervo, cursor, monkeypatch):
    leitor, original, _sha = acervo
    monkeypatch.setattr(leitor, "_canonico", lambda *_a: pytest.fail("parse para cursor inválido"))
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name, cursor)
    assert erro.value.codigo == "cursor_invalido"


@pytest.mark.parametrize("limite", [0, -1, True, 1.2, "10"])
def test_orcamento_invalido_nao_aciona_parse(acervo, limite):
    leitor, original, _sha = acervo
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name, max_chars=limite)
    assert erro.value.codigo == "orcamento_invalido"
    assert not list(ParseStore(leitor.store.diretorio).entradas())


def test_500_paginas_orcamentos_variaveis_e_offsets_exatos():
    canonico = renderizar(ParsedDoc("500.pdf", tuple(
        Block((f"Página {n}",), (f"Página {n}: ação 日本語 📄 e\u0301\n" * 9), locator=f"p. {n}")
        for n in range(1, 501)
    )))
    rng = random.Random(42)
    cursor, partes, vistos = None, [], set()
    while True:
        p = paginar(canonico, "versao", cursor=cursor, max_chars=rng.randint(1, 16000))
        assert p["markdown"] == canonico.markdown[p["inicio"]:p["fim"]]
        assert p["restante"] == len(canonico.markdown) - p["fim"]
        for b in p["blocos"]:
            assert canonico.markdown[b["inicio"]:b["fim"]].startswith("Página")
            vistos.add(b["onde"])
        partes.append(p["markdown"])
        if p["completo"]:
            break
        cursor = p["cursor_proximo"]
    assert "".join(partes).encode() == canonico.markdown.encode()
    assert len(vistos) == 500


def test_tetos_de_texto_e_sidecar_nao_perdem_conteudo():
    canonico = renderizar(ParsedDoc("micro.md", tuple(Block((), "x") for _ in range(500))))
    p = paginar(canonico, "v", cursor=None, max_chars=10**9)
    assert len(p["markdown"]) <= MAX_CHARS
    assert len(p["blocos"]) == MAX_BLOCOS
    partes = [p["markdown"]]
    while not p["completo"]:
        p = paginar(canonico, "v", cursor=p["cursor_proximo"], max_chars=10**9)
        partes.append(p["markdown"])
    assert "".join(partes) == canonico.markdown


def test_cursor_vincula_base_conteudo_e_sidecar(acervo):
    leitor, original, sha = acervo
    p = leitor.ler(original.name, max_chars=5)
    outro = LeitorDocumento(leitor.store, replace(leitor.base, id="outra"))
    with pytest.raises(ErroLeitura) as erro:
        outro.ler(original.name, p["cursor_proximo"])
    assert erro.value.codigo == "cursor_desatualizado"
    cache = ParseStore(leitor.store.diretorio)
    chave = Chave(sha, parser_version_for(".md"))
    canonico = cache.obter(chave)
    cache.gravar(chave, replace(canonico, blocos=(replace(canonico.blocos[0], locator="outra"), *canonico.blocos[1:])))
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name, p["cursor_proximo"])
    assert erro.value.codigo == "cursor_desatualizado"


def test_original_alterado_interrompe_paginacao(acervo):
    leitor, original, _sha = acervo
    p = leitor.ler(original.name, max_chars=5)
    original.write_text("nova versão", encoding="utf-8")
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name, p["cursor_proximo"])
    assert erro.value.codigo == "documento_alterado"


def test_miss_confere_hash_mesmo_com_tamanho_e_mtime_iguais(acervo):
    leitor, original, _sha = acervo
    st = original.stat()
    original.write_bytes(b"x" * st.st_size)
    os.utime(original, ns=(st.st_atime_ns, st.st_mtime_ns))
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name)
    assert erro.value.codigo == "documento_alterado"
    assert not list(ParseStore(leitor.store.diretorio).entradas())


def test_cache_corrompido_reconstroi_mesma_pagina(acervo):
    leitor, original, _sha = acervo
    p = leitor.ler(original.name)
    cache = ParseStore(leitor.store.diretorio)
    for entrada in cache.entradas():
        entrada.write_bytes(b"quebrado")
    assert leitor.ler(original.name) == p


def test_sem_raizes_serve_snapshot_quente_mas_miss_explica(acervo):
    leitor, original, _sha = acervo
    leitor.ler(original.name)
    sem_raizes = LeitorDocumento(leitor.store)
    p = sem_raizes.ler(original.name)
    assert p["original_conferido"] == "nao_configurado"
    ParseStore(leitor.store.diretorio).apagar_tudo()
    with pytest.raises(ErroLeitura) as erro:
        sem_raizes.ler(original.name)
    assert erro.value.codigo == "cache_ausente"


def test_raiz_removida_ou_exclusao_atual_negam_ate_cache_quente(acervo):
    leitor, original, _sha = acervo
    leitor.ler(original.name)
    for base in [replace(leitor.base, raizes=(RootSpec("outra", original.parent),)),
                 replace(leitor.base, exclude_globs=("*.md",))]:
        with pytest.raises(ErroLeitura):
            LeitorDocumento(leitor.store, base).ler(original.name)


def test_nao_grava_cache_no_acervo(acervo):
    leitor, original, _sha = acervo
    leitor.base = replace(leitor.base, raizes=(RootSpec("r", original.parent.parent),))
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name)
    assert erro.value.codigo == "cache_no_acervo"
    assert not list(ParseStore(leitor.store.diretorio).entradas())


def test_busy_nao_inicia_outro_parse_e_libera_depois(acervo):
    leitor, original, _sha = acervo
    with leitor._parse:
        with pytest.raises(ErroLeitura) as erro:
            leitor.ler(original.name)
    assert erro.value.codigo == "ocupado"
    assert leitor.ler(original.name)["markdown"]


def test_limite_recusa_antes_de_abrir_original(acervo, monkeypatch):
    leitor, original, _sha = acervo
    leitor.base = replace(leitor.base, limites=LimitesDeIndexacao(md=0.000001))
    monkeypatch.setattr("segundocerebro.ingest.reader.read_bytes", lambda *_a, **_k: pytest.fail("abriu arquivo acima do teto"))
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name)
    assert erro.value.codigo == "adiado"


@pytest.mark.parametrize("status", [ParseStatus.CLOUD_ONLY, ParseStatus.LOCKED, ParseStatus.ERROR])
def test_falha_do_parser_nao_vaza_caminho_e_libera_lock(acervo, monkeypatch, status):
    leitor, original, _sha = acervo
    def falhar(_path, **kwargs):
        assert not kwargs["allow_hydration"]
        assert kwargs["ram_mb"] and kwargs["timeout"] <= 60
        return ParseResult(str(original), status, detail=f"segredo {original}")
    monkeypatch.setattr("segundocerebro.index.isolamento.parse_isolado", falhar)
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name)
    assert str(original) not in str(erro.value)
    assert not leitor._parse.locked()


def test_ocr_indexado_nao_regride_para_texto_nativo(acervo, monkeypatch):
    leitor, original, _sha = acervo
    leitor.ler(original.name)
    leitor.store.con.execute("UPDATE documentos SET parser='ocr:1', digitalizado=1")
    leitor.store.commit()
    nativo = parse_file(str(original))
    monkeypatch.setattr("segundocerebro.index.isolamento.parse_isolado", lambda *_a, **_k: nativo)
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(original.name)
    assert erro.value.codigo == "ocr_indisponivel"


def test_sem_texto_e_scan_nao_fingem_original_vazio(acervo):
    leitor, original, sha = acervo
    leitor.store.con.execute("UPDATE documentos SET digitalizado=1")
    leitor.store.commit()
    ParseStore(leitor.store.diretorio).gravar(Chave(sha, parser_version_for(".md")), renderizar(ParsedDoc("vazio", ())))
    p = leitor.ler(original.name)
    assert p["completo"] and p["total"] == 0 and "cursor_proximo" not in p
    assert p["aviso"] and p["aviso_ocr"]


def test_leitura_nao_carrega_embedder_e_busca_reusa_store(tmp_path, monkeypatch):
    from segundocerebro.mcp.server import Recursos
    from tests.falsos import EmbedderFalso
    from segundocerebro.index.embeddings import MODELOS
    monkeypatch.setitem(MODELOS, "teste", replace(MODELOS["minilm"], dim=8))
    recursos = Recursos(tmp_path / "lazy", "teste", 1)
    def proibido(*_a, **_k):
        raise AssertionError("leitura carregou embedder")
    monkeypatch.setattr("segundocerebro.mcp.server.Embedder", proibido)
    store = recursos.store
    assert recursos._busca is None
    monkeypatch.setattr("segundocerebro.mcp.server.Embedder", lambda *_a, **_k: EmbedderFalso())
    assert recursos.busca and recursos.store is store
    store.fechar()


@pytest.mark.parametrize("sinal", ["abas_em_digesto", "digesto_parcial", "truncadas", "sem_valor_em_cache", "aviso"])
def test_limitacoes_do_parser_sao_visiveis_sem_vazar_mensagem(acervo, sinal):
    leitor, original, sha = acervo
    canonico = renderizar(ParsedDoc(original.name, (Block((), "texto"),), {sinal: "C:/segredo/erro"}))
    ParseStore(leitor.store.diretorio).gravar(Chave(sha, parser_version_for(".md")), canonico)
    p = leitor.ler(original.name)
    assert p["limitacoes_extracao"]
    assert "segredo" not in str(p)


def test_placeholder_e_recusado_pelo_reader_sem_abrir(acervo, monkeypatch):
    leitor, original, _sha = acervo
    monkeypatch.setattr("segundocerebro.ingest.reader.is_cloud_only", lambda _attrs: True)
    def proibido(*_a, **_k):
        pytest.fail("abriu placeholder")
    with monkeypatch.context() as portao:
        portao.setattr("builtins.open", proibido)
        with pytest.raises(ErroLeitura) as erro:
            leitor.ler(original.name)
    assert erro.value.codigo == "placeholder"


def _link_diretorio(alvo, link):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(alvo), str(link))
    else:
        link.symlink_to(alvo, target_is_directory=True)


def test_junction_fora_da_raiz_nao_e_lida(acervo, tmp_path):
    leitor, original, sha = acervo
    externo = tmp_path / "externo"
    externo.mkdir()
    (externo / original.name).write_bytes(original.read_bytes())
    link = original.parent / "atalho"
    _link_diretorio(externo, link)
    leitor.store.con.execute("UPDATE documentos SET path=?", ("atalho/" + original.name,))
    leitor.store.commit()
    with pytest.raises(ErroLeitura) as erro:
        leitor.ler(sha[:12])
    assert erro.value.codigo in {"link_recusado", "fora_da_base"}
    assert not list(ParseStore(leitor.store.diretorio).entradas())


def test_shard_de_cache_nao_segue_junction_externa(acervo, tmp_path):
    leitor, original, sha = acervo
    cache = ParseStore(leitor.store.diretorio)
    chave = Chave(sha, parser_version_for(".md"))
    externo = tmp_path / "cache-externo"
    externo.mkdir()
    cache.raiz.mkdir()
    _link_diretorio(externo, cache.raiz / chave.digest()[:2])
    with pytest.raises(OSError, match="fora do Parse Store"):
        leitor.ler(original.name)
    assert not list(externo.iterdir())


def test_pdf_real_de_500_paginas_no_fluxo_isolado(acervo):
    import pymupdf
    leitor, original, _sha = acervo
    pdf = original.with_suffix(".pdf")
    with pymupdf.open() as arquivo:
        for n in range(1, 501):
            arquivo.new_page().insert_text((72, 72), f"Pagina {n}: conteudo sintetico completo para teste de leitura integral.")
        arquivo.save(pdf)
    sha = sha256(pdf.read_bytes()).hexdigest()
    leitor.store.registrar_documento(
        path=pdf.name, raiz="r", tamanho=pdf.stat().st_size, mtime=pdf.stat().st_mtime,
        sha256=sha, parser=parser_version_for(".pdf"), status="ok", n_chunks=0,
        model_id="falso:8",
    )
    leitor.store.commit()
    esperado = renderizar(parse_file(str(pdf)).doc)
    assert len(esperado.blocos) == 500
    partes, cursor, localizadores = [], None, set()
    while True:
        p = leitor.ler(pdf.name, cursor, 3141)
        partes.append(p["markdown"])
        localizadores.update(b["onde"] for b in p["blocos"])
        if p["completo"]:
            break
        cursor = p["cursor_proximo"]
    assert "".join(partes) == esperado.markdown
    assert len(localizadores) == 500


def test_homonimo_so_censo_em_outra_raiz_nao_sobrescreve_documento_indexado(acervo, tmp_path):
    leitor, original, sha = acervo
    outra = tmp_path / "outra-raiz"
    outra.mkdir()
    (outra / original.name).write_text("conteúdo diferente ainda não indexado", encoding="utf-8")
    leitor.base = replace(leitor.base, raizes=(*leitor.base.raizes, RootSpec("outra", outra)))
    lido = leitor.ler(original.name)
    assert lido["documento"]["raiz"] == "r"
    assert "Texto integral" in lido["markdown"]
    assert leitor.ler(sha[:12])["documento"]["raiz"] == "r"
