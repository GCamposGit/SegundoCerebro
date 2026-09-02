"""Citation contract: exact coordinates, provenance and backwards compatibility."""

from dataclasses import replace
import json
import zlib

import pytest

from segundocerebro.acesso.pagina_documento import paginar
from segundocerebro.ingest.canonico import BlocoCanonico, ParseCanonico, renderizar
from segundocerebro.ingest.document import Block, BlockKind, ParsedDoc
from segundocerebro.ingest.estrutura import VERSAO_ESTRUTURA, citar, validar
from segundocerebro.ingest.parse_store import Chave, ParseStore


@pytest.mark.parametrize("locator,pagina,slide", [
    ("p. 12", 12, None), ("slide 4", None, 4), ("slide 4 (notas)", None, 4),
    ("", None, None), ("p. 0", None, None), ("p. -2", None, None),
    ("p. 01", None, None), ("p. ١", None, None), ("p. 2 extra", None, None),
    ("tabela 3", None, None), ("Planilha!A1:F40", None, None), ("00:12", None, None),
])
def test_localizadores_nao_inventam_paginas(locator, pagina, slide):
    bloco = BlocoCanonico(("Página 99",), 0, 2, locator=locator)
    citacao = citar(bloco, 7)
    assert citacao == {"ordinal": 7, "inicio": 0, "fim": 2, "onde": locator,
                       "tipo": "texto", "trilha": ["Página 99"],
                       "pagina": pagina, "slide": slide}


def test_paginas_do_transporte_preservam_bloco_e_secao_globais():
    doc = ParsedDoc("vce.pdf", (
        Block(("Relatório", "Escopo"), "ação 📄 e\u0301 日本語", "p. 1"),
        Block(("Relatório", "Escopo"), "", "p. 1"),
        Block(("Relatório", "Anexo"), "| VCE | NN |", "p. 2", BlockKind.TABLE),
    ))
    canonico = renderizar(doc)
    cursor, partes, vistos = None, [], {}
    while True:
        resposta = paginar(canonico, "vce", cursor=cursor, max_chars=1)
        assert resposta["estrutura"] == {
            "versao": "blocos:1", "referencial": "markdown_canonico",
            "unidade": "caracteres_unicode", "base": 0, "intervalo": "[inicio,fim)",
            "ordinal_base": 0, "pagina_base": 1, "slide_base": 1,
        }
        partes.append(resposta["markdown"])
        for citacao in resposta["blocos"]:
            n = citacao["ordinal"]
            assert vistos.setdefault(n, citacao) == citacao
            assert canonico.markdown[citacao["inicio"]:citacao["fim"]] == doc.blocks[n].text
            assert citacao["trilha"] == list(doc.blocks[n].heading_path)
        if resposta["completo"]:
            break
        cursor = resposta["cursor_proximo"]
    assert "".join(partes).encode() == canonico.markdown.encode()
    assert set(vistos) == {0, 2}  # Empty blocks do not anchor quotations.
    assert vistos[2]["pagina"] == 2 and vistos[2]["tipo"] == "tabela"


@pytest.mark.parametrize("alteracao", [
    {"inicio": -1}, {"fim": 4}, {"inicio": 2, "fim": 1},
    {"inicio": True}, {"fim": 1.0}, {"trilha": (1,)},
    {"trilha": "seção"}, {"kind": None}, {"locator": 1},
])
def test_rejeita_spans_invalidos_na_escrita_e_na_leitura(tmp_path, alteracao):
    canonico = ParseCanonico("abc", (replace(BlocoCanonico((), 0, 3), **alteracao),))
    cache = ParseStore(tmp_path)
    with pytest.raises(ValueError):
        cache.gravar(Chave("a", "teste:1"), canonico)
    with pytest.raises(ValueError):
        paginar(canonico, "v", cursor=None, max_chars=10)
    assert not cache.raiz.exists()


@pytest.mark.parametrize("blocos", [
    (BlocoCanonico((), 0, 2), BlocoCanonico((), 1, 3)),
    (BlocoCanonico((), 2, 3), BlocoCanonico((), 0, 1)),
])
def test_sobreposicao_e_ordem_invalida_nao_sao_citaveis(blocos):
    with pytest.raises(ValueError):
        validar(ParseCanonico("abc", blocos))


def test_vazio_e_lacunas_de_renderizacao_sao_validos():
    validar(ParseCanonico(""))
    validar(ParseCanonico("# A\n\nx\n\n", (BlocoCanonico(("A",), 5, 6),)))


@pytest.mark.parametrize("versao,aceita", [(None, True), (VERSAO_ESTRUTURA, True), ("blocos:2", False)])
def test_cache_legado_e_versao_futura(tmp_path, versao, aceita):
    cache, chave = ParseStore(tmp_path), Chave("a", "teste:1")
    canonico = renderizar(ParsedDoc("vce.md", (Block(("VCE",), "ação 📄"),)))
    arquivo = cache.gravar(chave, canonico)
    dados = json.loads(zlib.decompress(arquivo.read_bytes()))
    assert dados.pop("estrutura_versao") == VERSAO_ESTRUTURA
    if versao is not None:
        dados["estrutura_versao"] = versao
    arquivo.write_bytes(zlib.compress(json.dumps(dados).encode()))
    assert cache.obter(chave) == (canonico if aceita else None)
    assert arquivo.exists() == aceita
