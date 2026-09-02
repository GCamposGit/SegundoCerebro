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

    def tool(self, description: str = "", **_k):  # noqa: ANN201, ANN003
        def registrar(fn):  # noqa: ANN001, ANN202
            fn.description = description
            self.tools[fn.__name__] = fn
            return fn
        return registrar


class _Recursos:
    def __init__(self, store) -> None:  # noqa: ANN001
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
