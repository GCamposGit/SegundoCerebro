"""J.d: cobrir uma pasta sem corte intra-documento e sem o agente perder família."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from segundocerebro.acesso.documento import LeitorDocumento
from segundocerebro.acesso.empacote import empacotar
from segundocerebro.acesso.original import ErroLeitura
from segundocerebro.census import Config as CensoConfig
from segundocerebro.census import RootSpec
from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, ParsedDoc
from segundocerebro.ingest.parse_store import Chave, ParseStore
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.mcp import leitura

PROJETO = "Projetos/Gama"


def _gravar(store, caminho: str, texto: str, mtime: float) -> tuple[str, str]:
    canonico = renderizar(ParsedDoc(caminho, (Block(("VCE",), texto),)))
    digest = sha256(f"{caminho}\n{texto}".encode()).hexdigest()
    ParseStore(store.diretorio).gravar(Chave(digest, parser_version_for(".md")), canonico)
    store.registrar_documento(
        path=caminho, raiz="acervo", tamanho=len(texto), mtime=mtime, sha256=digest,
        status="ok", n_chunks=0, model_id="falso:8", parser=parser_version_for(".md"),
    )
    return digest, canonico.markdown


def _projeto(store, n: int = 30) -> dict[str, str]:
    """Pasta VCE com famílias plantadas: 30 canônicos e irmãos antigos ao lado."""
    textos: dict[str, str] = {}
    for i in range(n):
        vigente = f"{PROJETO}/NN-VCE-{i:03d}.md"
        textos[vigente] = _gravar(store, vigente, f"canônico {i} da Várzea Clara Energia", 400.0 + i)[1]
        if i < 3:
            antigo = f"{PROJETO}/NN-VCE-{i:03d}_v0.md"
            textos[antigo] = _gravar(
                store, antigo, f"rascunho {i} que o pack canônico não deve copiar", 100.0,
            )[1]
    store.commit()
    return textos


def _leitor(store) -> LeitorDocumento:
    return LeitorDocumento(store)


def _cobrir(store, pasta: str, budget: int, **kwargs) -> dict:
    """Agente de contexto limitado: pagina pack_folder até completo=true."""
    vistos: list[str] = []
    corpos: list[str] = []
    cursor = None
    leitor = _leitor(store)
    paginas = 0
    while True:
        saida = empacotar(
            store, pasta, leitor=leitor, budget_chars=budget, cursor=cursor, **kwargs,
        )
        for caminho in saida["incluidos"]:
            assert caminho not in vistos
        vistos.extend(saida["incluidos"])
        corpos.append(saida["markdown"])
        paginas += 1
        assert paginas < 200
        if saida["completo"]:
            assert "cursor_proximo" not in saida
            return {"incluidos": vistos, "markdown": "\n".join(corpos), "paginas": paginas, "saida": saida}
        cursor = saida["cursor_proximo"]


def test_canonicos_nunca_omite_familia_e_nao_empacota_o_rascunho(store) -> None:
    textos = _projeto(store)
    cobertura = _cobrir(store, PROJETO, 400, politica="canonicos")
    canonicos = [f"{PROJETO}/NN-VCE-{i:03d}.md" for i in range(30)]
    rascunhos = [f"{PROJETO}/NN-VCE-{i:03d}_v0.md" for i in range(3)]

    assert cobertura["incluidos"] == canonicos
    assert set(cobertura["incluidos"]) == set(canonicos)
    for rascunho in rascunhos:
        assert rascunho not in cobertura["incluidos"]
        assert textos[rascunho] not in cobertura["markdown"]
    for i, vigente in enumerate(canonicos):
        ident = sha256(f"{vigente}\ncanônico {i} da Várzea Clara Energia".encode()).hexdigest()[:12]
        assert textos[vigente] in cobertura["markdown"]
        assert f"arquivo: {vigente}" in cobertura["markdown"]
        assert f"id: {ident}" in cobertura["markdown"]


def test_separador_carrega_id_e_caminho_em_todo_documento(store) -> None:
    textos = _projeto(store, n=4)
    saida = empacotar(store, PROJETO, leitor=_leitor(store), budget_chars=8000, politica="canonicos")
    assert saida["completo"]
    for caminho in saida["incluidos"]:
        bloco = saida["markdown"].split("arquivo: " + caminho, 1)
        assert len(bloco) == 2
        cabeca = bloco[0][bloco[0].rfind("---"):]
        assert "id: " in cabeca
        assert textos[caminho] in saida["markdown"]


def test_todos_inclui_o_rascunho_e_apenas_listados_filtra(store) -> None:
    _projeto(store, n=4)
    todos = empacotar(store, PROJETO, leitor=_leitor(store), budget_chars=8000, politica="todos")
    assert any(n.endswith("_v0.md") for n in todos["incluidos"])
    assert len(todos["incluidos"]) == 7

    alvo = f"{PROJETO}/NN-VCE-001.md"
    filtrado = empacotar(
        store, PROJETO, leitor=_leitor(store), budget_chars=8000,
        politica="apenas_listados", ids=[alvo],
    )
    assert filtrado["incluidos"] == [alvo]


def test_nao_corta_no_meio_do_documento(store) -> None:
    textos = _projeto(store, n=8)
    cobertura = _cobrir(store, PROJETO, 180, politica="canonicos")
    assert cobertura["paginas"] > 1
    for caminho, texto in textos.items():
        if caminho.endswith("_v0.md"):
            continue
        assert cobertura["markdown"].count(texto) == 1
        assert caminho in cobertura["incluidos"]


def test_trinta_canonicos_em_n_passadas_sem_repeticao(store) -> None:
    _projeto(store, n=30)
    cobertura = _cobrir(store, PROJETO, 350, politica="canonicos", recursivo=True)
    assert cobertura["incluidos"] == [f"{PROJETO}/NN-VCE-{i:03d}.md" for i in range(30)]
    assert len(cobertura["incluidos"]) == len(set(cobertura["incluidos"]))
    assert cobertura["paginas"] > 1


def test_so_censo_e_sem_id_entram_em_omitidos_nao_no_bundle(store, tmp_path) -> None:
    _projeto(store, n=2)
    raiz = tmp_path / "acervo"
    novo = raiz / "Projetos" / "Gama" / "Novo.txt"
    novo.parent.mkdir(parents=True)
    novo.write_text("ainda não indexado", encoding="utf-8")
    cfg = CensoConfig(roots=[RootSpec(name="acervo", path=raiz)])
    saida = empacotar(
        store, PROJETO, leitor=_leitor(store), budget_chars=8000,
        politica="todos", censo_cfg=cfg,
    )
    assert any(o["arquivo"].endswith("Novo.txt") for o in saida["omitidos"])
    assert "Novo.txt" not in " ".join(saida["incluidos"])
    assert "ainda não indexado" not in saida["markdown"]


def test_ordem_e_por_caminho_nao_por_relevancia(store) -> None:
    _projeto(store, n=6)
    uma = empacotar(store, PROJETO, leitor=_leitor(store), budget_chars=8000)
    outra = empacotar(store, PROJETO, leitor=_leitor(store), budget_chars=8000)
    assert uma["incluidos"] == outra["incluidos"] == sorted(uma["incluidos"])


def test_cursor_invalido_e_politica_invalida_nao_empacotam(store) -> None:
    _projeto(store, n=2)
    leitor = _leitor(store)
    try:
        empacotar(store, PROJETO, leitor=leitor, cursor="x")
        raise AssertionError("cursor inválido passou")
    except ErroLeitura as erro:
        assert erro.codigo == "cursor_invalido"
    try:
        empacotar(store, PROJETO, leitor=leitor, politica="melhores")
        raise AssertionError("política inválida passou")
    except ErroLeitura as erro:
        assert erro.codigo == "politica_invalida"


class _Espiao:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, description: str = "", **_k):
        def registrar(fn):
            fn.description = description
            self.tools[fn.__name__] = fn
            return fn
        return registrar


class _Recursos:
    def __init__(self, store) -> None:
        self.store = store
        self.base = None


def test_ferramenta_mcp_devolve_is_error_e_o_bundle(store) -> None:
    _projeto(store, n=3)
    espiao = _Espiao()
    leitura.registrar(espiao, _Recursos(store))
    saida = espiao.tools["pack_folder"](pasta=PROJETO, budget_chars=8000)
    corpo = saida.structured_content
    assert not saida.is_error
    assert f"{PROJETO}/NN-VCE-000.md" in corpo["incluidos"]
    assert f"{PROJETO}/NN-VCE-000_v0.md" not in corpo["incluidos"]
    assert "id:" in corpo["markdown"] and "arquivo:" in corpo["markdown"]
    erro = espiao.tools["pack_folder"](pasta=PROJETO, politica="melhor")
    assert erro.is_error
    assert erro.structured_content["codigo"] == "politica_invalida"


class _LeitorEspiao:
    def __init__(self, leitor_real: LeitorDocumento) -> None:
        self.real = leitor_real
        self.chamadas: list[str] = []

    def carregar_documento(self, doc):
        self.chamadas.append(doc.caminho)
        return self.real.carregar_documento(doc)


def test_primeira_pagina_pequena_nao_carrega_mil_documentos(store) -> None:
    """FND-03a: Pasta com 1.000 documentos não faz 1.000 leituras para a 1ª página."""
    _projeto(store, n=1000)
    leitor_real = _leitor(store)
    espiao = _LeitorEspiao(leitor_real)

    saida = empacotar(store, PROJETO, leitor=espiao, budget_chars=400, politica="canonicos")

    assert not saida["completo"]
    assert saida["total"] == 1000
    assert len(saida["incluidos"]) >= 1
    # Verifica que apenas os documentos que couberam na primeira página foram lidos (<= 5 docs, NUNCA 1000)
    assert len(espiao.chamadas) <= 5
    assert len(espiao.chamadas) < 1000


def test_orcamento_invalido_tem_zero_leituras(store) -> None:
    """FND-03a: Orçamento inválido falha antes de enumerar/carregar qualquer documento."""
    _projeto(store, n=5)
    leitor_real = _leitor(store)
    espiao = _LeitorEspiao(leitor_real)

    try:
        empacotar(store, PROJETO, leitor=espiao, budget_chars=-1)
        raise AssertionError("Deveria falhar com orcamento_invalido")
    except ErroLeitura as erro:
        assert erro.codigo == "orcamento_invalido"

    assert len(espiao.chamadas) == 0


def test_continuacao_por_cursor_nao_reprocessa_anteriores(store) -> None:
    """FND-03a: Ao avançar com o cursor, documentos já empacotados não são relidos."""
    _projeto(store, n=20)
    leitor_real = _leitor(store)
    espiao_p1 = _LeitorEspiao(leitor_real)

    pag1 = empacotar(store, PROJETO, leitor=espiao_p1, budget_chars=300, politica="canonicos")
    assert not pag1["completo"]
    cursor1 = pag1["cursor_proximo"]
    lidos_pag1 = set(espiao_p1.chamadas)
    assert len(lidos_pag1) >= 1

    espiao_p2 = _LeitorEspiao(leitor_real)
    pag2 = empacotar(store, PROJETO, leitor=espiao_p2, budget_chars=300, cursor=cursor1, politica="canonicos")
    assert len(pag2["incluidos"]) >= 1

    # Nenhum arquivo já incluído na página 1 deve ser relido na página 2
    for arq in espiao_p2.chamadas:
        assert arq not in pag1["incluidos"]
    assert "Projetos/Gama/NN-VCE-000.md" not in espiao_p2.chamadas


def _erro_status(store, caminho: str, i: int) -> None:
    digest = sha256(f"erro-{i}".encode()).hexdigest()
    store.registrar_documento(
        path=caminho, raiz="acervo", tamanho=1, mtime=float(i), sha256=digest,
        status="erro", n_chunks=0, model_id="falso:8", parser="md:1",
    )


def _cobrir_estrito(store, pasta: str, budget: int, **kwargs) -> dict:
    """Agente estrito: pagina até completo sem o Markdown passar do teto."""
    vistos: list[str] = []
    encaminhados: list[str] = []
    omitidos: list[str] = []
    corpos: list[str] = []
    cursor = None
    paginas = 0
    while True:
        saida = empacotar(
            store, pasta, leitor=_leitor(store), budget_chars=budget,
            cursor=cursor, estrito=True, **kwargs,
        )
        assert len(saida["markdown"]) <= budget
        assert "token" not in saida["unidade"].lower()
        corpos.append(saida["markdown"])
        for caminho in saida["incluidos"]:
            assert caminho not in vistos
            assert caminho not in encaminhados
        vistos.extend(saida["incluidos"])
        for item in saida.get("encaminhados", []):
            assert item["proximo_passo"] == "get_document"
            assert item["id"]
            assert item["documento"]
            assert item["arquivo"] not in vistos
            encaminhados.append(item["arquivo"])
        omitidos.extend(o["arquivo"] for o in saida["omitidos"])
        paginas += 1
        assert paginas < 200, "cursor que não avança é laço"
        if saida["completo"]:
            assert "cursor_proximo" not in saida
            return {
                "incluidos": vistos, "encaminhados": encaminhados, "omitidos": omitidos,
                "paginas": paginas, "saida": saida, "markdown": "\n".join(corpos),
            }
        cursor = saida["cursor_proximo"]


def test_legado_ainda_excede_no_primeiro_da_pagina(store) -> None:
    """FND-03b: o default de J.d não muda — o primeiro da página pode estourar."""
    enorme = "Y" * 10_000
    _gravar(store, f"{PROJETO}/enorme.md", enorme, 1.0)
    store.commit()
    saida = empacotar(store, PROJETO, leitor=_leitor(store), budget_chars=500)
    assert len(saida["markdown"]) > 500
    assert saida["incluidos"] == [f"{PROJETO}/enorme.md"]
    assert enorme in saida["markdown"]


def test_estrito_documento_de_cem_mil_nao_entra_no_bundle(store) -> None:
    """FND-03b: 100.000 caracteres não cabem; o id aponta para get_document."""
    corpo = "Z" * 100_000
    _gravar(store, f"{PROJETO}/cem-mil.md", corpo, 1.0)
    store.commit()
    cobertura = _cobrir_estrito(store, PROJETO, 8_000, politica="todos")
    alvo = f"{PROJETO}/cem-mil.md"
    assert alvo in cobertura["encaminhados"]
    assert alvo not in cobertura["incluidos"]
    assert corpo not in cobertura["markdown"]
    assert cobertura["saida"]["completo"]
    enc = cobertura["saida"]["encaminhados"][0]
    assert enc["motivo"]
    assert enc["proximo_passo"] == "get_document"


def test_estrito_orcamento_um_nao_carrega_conteudo(store) -> None:
    """FND-03b: envelope mínimo não cabe → erro antes de parse."""
    _gravar(store, f"{PROJETO}/a.md", "texto", 1.0)
    store.commit()
    espiao = _LeitorEspiao(_leitor(store))
    try:
        empacotar(store, PROJETO, leitor=espiao, budget_chars=1, estrito=True)
        raise AssertionError("orçamento 1 deveria falhar")
    except ErroLeitura as erro:
        assert erro.codigo == "orcamento_insuficiente"
    assert espiao.chamadas == []


def test_estrito_conta_caracteres_unicode_nao_bytes(store) -> None:
    """FND-03b: á é um caractere; utf-8 tem dois bytes — o teto usa len()."""
    corpo = "á" * 400
    _gravar(store, f"{PROJETO}/acentos.md", corpo, 1.0)
    store.commit()
    folgado = empacotar(
        store, PROJETO, leitor=_leitor(store), budget_chars=8_000, estrito=True,
    )
    teto = len(folgado["markdown"])
    assert corpo in folgado["markdown"]
    assert teto < len(folgado["markdown"].encode("utf-8"))
    justo = empacotar(
        store, PROJETO, leitor=_leitor(store), budget_chars=teto, estrito=True,
    )
    assert len(justo["markdown"]) <= teto
    assert justo["incluidos"] == [f"{PROJETO}/acentos.md"]
    assert corpo in justo["markdown"]


def test_estrito_pagina_milhares_de_omitidos(store) -> None:
    """FND-03b: 1.200 omitidos não cabem numa página; o cliente chega ao fim."""
    _gravar(store, f"{PROJETO}/zz-ok.md", "canônico", 9_999.0)
    for i in range(1_200):
        _erro_status(store, f"{PROJETO}/omit-{i:04d}.md", i)
    store.commit()
    cobertura = _cobrir_estrito(store, PROJETO, 4_000, politica="todos")
    assert len(cobertura["omitidos"]) == 1_200
    assert cobertura["paginas"] > 1
    assert f"{PROJETO}/zz-ok.md" in cobertura["incluidos"] + cobertura["encaminhados"]
    assert cobertura["saida"]["total"] == 1_201


def test_estrito_enorme_no_meio_e_no_fim(store) -> None:
    """FND-03b: item enorme no meio e no fim é encaminhado; os pequenos entram."""
    _gravar(store, f"{PROJETO}/a-pequeno.md", "um", 1.0)
    _gravar(store, f"{PROJETO}/b-enorme.md", "M" * 100_000, 2.0)
    _gravar(store, f"{PROJETO}/c-pequeno.md", "dois", 3.0)
    _gravar(store, f"{PROJETO}/d-enorme.md", "F" * 100_000, 4.0)
    store.commit()
    cobertura = _cobrir_estrito(store, PROJETO, 8_000, politica="todos")
    assert cobertura["incluidos"] == [f"{PROJETO}/a-pequeno.md", f"{PROJETO}/c-pequeno.md"]
    assert cobertura["encaminhados"] == [f"{PROJETO}/b-enorme.md", f"{PROJETO}/d-enorme.md"]
    assert "M" * 100 not in cobertura["markdown"]
    assert "F" * 100 not in cobertura["markdown"]
    for item in cobertura["saida"]["itens"]:
        if item.get("papel") == "encaminhado":
            assert item["proximo_passo"] == "get_document"


def test_ferramenta_mcp_estrito_encaminha_e_respeita_teto(store) -> None:
    _gravar(store, f"{PROJETO}/enorme.md", "Q" * 100_000, 1.0)
    store.commit()
    espiao = _Espiao()
    leitura.registrar(espiao, _Recursos(store))
    saida = espiao.tools["pack_folder"](pasta=PROJETO, budget_chars=8000, estrito=True)
    corpo = saida.structured_content
    assert not saida.is_error
    assert len(corpo["markdown"]) <= 8000
    assert corpo["estrito"] is True
    assert corpo["encaminhados"]
    assert corpo["encaminhados"][0]["proximo_passo"] == "get_document"
    assert "Q" * 100 not in corpo["markdown"]

