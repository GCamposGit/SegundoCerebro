"""`J.c-mapa`: enumerar e mapear sem nunca fazer o agente achar que viu tudo.

A classe de defeito que estas ferramentas existem para não ter é **a tool que
faz o agente acreditar que viu tudo**: ele pede uma pasta, recebe 8 de 40
documentos sem nenhum sinal de corte, e escreve o relatório confiante. Não
aparece como erro — aparece como resposta plausível e incompleta, que é o pior
modo de falha para ferramenta de agente.

A guarda é o `test_nenhuma_ferramenta_de_leitura_corta_sem_cursor`: ele **deriva
do módulo** quais são as tools de leitura, em vez de listá-las à mão. Lista
escrita de cabeça e prova escrita pela mesma cabeça concordam sempre — foi assim
que o dialeto de topo do `census.toml` saiu com uma chave quando o leitor lê três.
Tool nova em `mcp/leitura.py` sem caso declarado aqui reprova.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from segundocerebro.acesso import identidade, manifesto
from segundocerebro.index.store import Store
from segundocerebro.mcp import leitura

from tests.falsos import chunk

PASTA = "Projetos/Alfa"


@pytest.fixture
def indice(store: Store) -> Store:
    """Quatro documentos numa pasta, um em quarentena, um sem hash, e uma subpasta."""
    documentos = [
        ("Projetos/Alfa/Plano_v1.docx", "a" * 64, 300.0, "ok"),
        ("Projetos/Alfa/Plano_v2.docx", "b" * 64, 400.0, "ok"),
        ("Projetos/Alfa/Ata.pdf", "c" * 64, 200.0, "ok"),
        ("Projetos/Alfa/Escaneado.pdf", "", 100.0, "sem_parser"),
        ("Projetos/Alfa/Interno/Anexo.xlsx", "d" * 64, 150.0, "ok"),
        ("Projetos/Beta/Outro.docx", "e" * 64, 150.0, "ok"),
    ]
    for path, sha, mtime, status in documentos:
        store.registrar_documento(
            path=path,
            raiz="acervo",
            tamanho=100,
            mtime=mtime,
            sha256=sha,
            status=status,
            n_chunks=0,
            model_id="falso:8",
            chunker="v1",
            parser="p1",
        )
    store.registrar_quarentena(
        "Projetos/Alfa/Ata.pdf", hash="c" * 64, motivo="conversão estourou o tempo"
    )

    trechos = [
        chunk("p2#0", "Projetos/Alfa/Plano_v2.docx", 0, "a" * 500, ("Plano", "Escopo")),
        chunk("p2#1", "Projetos/Alfa/Plano_v2.docx", 1, "b" * 400, ("Plano", "Escopo")),
        chunk("p2#2", "Projetos/Alfa/Plano_v2.docx", 2, "c" * 300, ("Plano", "Prazos")),
        chunk("p2#3", "Projetos/Alfa/Plano_v2.docx", 3, "d" * 200, ("Plano", "Custos")),
    ]
    store.gravar_textos(trechos)
    store.commit()
    return store


class _Espiao:
    """Um servidor que só guarda o que foi registrado nele."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, description: str = "", **_k):  # noqa: ANN201, ANN003
        def registrar(fn):  # noqa: ANN001, ANN202
            fn.description = description
            self.tools[fn.__name__] = fn
            return fn

        return registrar


class _Recursos:
    def __init__(self, store: Store, base_id: str = "") -> None:
        self.store = store
        self.base = type("Base", (), {"id": base_id})() if base_id else None


def ferramentas_de_leitura(store: Store, base_id: str = "corp") -> dict[str, Any]:
    """As tools do `J.c`, **derivadas do módulo** e não escritas à mão."""
    espiao = _Espiao()
    leitura.registrar(espiao, _Recursos(store, base_id))
    return espiao.tools


# --- list_folder --------------------------------------------------------------


def test_lista_o_que_existe_com_id_status_e_vigencia(indice: Store) -> None:
    saida = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA)
    por_arquivo = {i["arquivo"]: i for i in saida["itens"]}

    assert set(por_arquivo) == {
        "Projetos/Alfa/Plano_v1.docx",
        "Projetos/Alfa/Plano_v2.docx",
        "Projetos/Alfa/Ata.pdf",
        "Projetos/Alfa/Escaneado.pdf",
    }, "sem `recursivo` a subpasta não entra, e a pasta irmã nunca entra"

    plano2 = por_arquivo["Projetos/Alfa/Plano_v2.docx"]
    assert plano2["id"] == "b" * 12
    assert plano2["uri"] == identidade.montar_uri("corp", "b" * 12)
    assert plano2["status"] == "indexado"
    assert plano2["chars"] == 1400
    assert plano2["trechos"] == 4
    assert plano2["vigente"] is True
    assert por_arquivo["Projetos/Alfa/Plano_v1.docx"]["vigente"] is False


def test_quarentena_aparece_com_motivo_em_vez_de_sumir(indice: Store) -> None:
    """Documento que existe e não foi lido é informação, não ausência.

    Omiti-lo seria a truncagem silenciosa de novo: quem lista uma pasta e recebe
    3 de 4 arquivos não tem como saber do quarto.
    """
    itens = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA)["itens"]
    ata = next(i for i in itens if i["arquivo"].endswith("Ata.pdf"))

    assert ata["status"] == "quarentena"
    assert "tempo" in ata["motivo"]


def test_documento_sem_hash_diz_por_que_nao_tem_id(indice: Store) -> None:
    itens = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA)["itens"]
    scan = next(i for i in itens if i["arquivo"].endswith("Escaneado.pdf"))

    assert "id" not in scan
    assert scan["sem_id"]
    assert scan["status"] == "formato_nao_lido"


def test_a_ordem_e_por_caminho_e_nao_por_relevancia(indice: Store) -> None:
    """Enumeração é neutra: a mesma pasta devolve a mesma lista toda vez.

    É o que permite o workflow repetível que o pacote J promete. Ranking dentro
    de `list_folder` é a anti-recomendação 6 — relevância é do `search`.
    """
    tools = ferramentas_de_leitura(indice)
    uma = [i["arquivo"] for i in tools["list_folder"](pasta=PASTA)["itens"]]
    outra = [i["arquivo"] for i in tools["list_folder"](pasta=PASTA)["itens"]]

    assert uma == outra == sorted(uma)


def test_recursivo_alcanca_a_subpasta(indice: Store) -> None:
    saida = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA, recursivo=True)
    assert any(i["arquivo"].endswith("Interno/Anexo.xlsx") for i in saida["itens"])


def test_pasta_vazia_avisa_em_vez_de_devolver_lista_vazia_muda(indice: Store) -> None:
    saida = ferramentas_de_leitura(indice)["list_folder"](pasta="Nao/Existe")
    assert saida["itens"] == []
    assert saida["total"] == 0
    assert "aviso" in saida, "lista vazia sem explicação parece acervo vazio"


def test_o_manifesto_declara_a_propria_fronteira(indice: Store) -> None:
    """O que o manifesto **não** cobre entra no retorno, não numa nota de rodapé."""
    saida = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA)
    assert "índice" in saida["fronteira"] and "quarentena" in saida["fronteira"]


# --- outline ------------------------------------------------------------------


def test_o_mapa_funde_trechos_da_mesma_secao(indice: Store) -> None:
    """A régua do chunker não é a estrutura do documento.

    Quatro chunks em três seções: quem lê o mapa quer as seções, não os cortes de
    orçamento que o chunker fez dentro de uma delas.
    """
    saida = ferramentas_de_leitura(indice)["outline"](documento="Projetos/Alfa/Plano_v2.docx")
    secoes = saida["secoes"]

    assert [s["secao"] for s in secoes] == ["Plano > Escopo", "Plano > Prazos", "Plano > Custos"]
    assert secoes[0]["chars"] == 900 and secoes[0]["trechos"] == 2
    assert saida["documento"]["chars"] == 1400
    assert saida["documento"]["id"] == "b" * 12


def test_caminho_id_e_uri_dao_o_mesmo_mapa(indice: Store) -> None:
    outline = ferramentas_de_leitura(indice)["outline"]
    por_caminho = outline(documento="Projetos/Alfa/Plano_v2.docx")
    por_id = outline(documento="b" * 12)
    por_uri = outline(documento=identidade.montar_uri("corp", "b" * 12))

    assert por_caminho == por_id == por_uri


def test_uri_de_outra_base_e_recusada_e_nao_vira_seletor(indice: Store) -> None:
    """Invariante 7: a base no endereço confere, nunca escolhe."""
    saida = ferramentas_de_leitura(indice, base_id="corp")["outline"](
        documento=identidade.montar_uri("pessoal", "b" * 12)
    )
    assert "erro" in saida
    assert saida["secoes"] == []


def test_documento_fora_do_indice_explica_em_vez_de_estourar(indice: Store) -> None:
    saida = ferramentas_de_leitura(indice)["outline"](documento="Projetos/Alfa/Fantasma.docx")
    assert "erro" in saida and "dica" in saida


def test_documento_sem_trecho_indexado_diz_o_status(indice: Store) -> None:
    saida = ferramentas_de_leitura(indice)["outline"](documento="Projetos/Alfa/Escaneado.pdf")
    assert saida["secoes"] == []
    assert "aviso" in saida
    assert "formato_nao_lido" in saida["aviso"]


# --- o cursor, derivado do módulo ---------------------------------------------


CASOS_DE_CURSOR = {
    "list_folder": {"argumentos": {"pasta": PASTA, "recursivo": True}, "orcamento": "max_itens", "lista": "itens"},
    "outline": {
        "argumentos": {"documento": "Projetos/Alfa/Plano_v2.docx"},
        "orcamento": "max_secoes",
        "lista": "secoes",
    },
}
"""Como exercitar cada tool de leitura. A **lista** de tools não mora aqui."""


def test_todo_caso_de_cursor_cobre_uma_tool_que_existe(indice: Store) -> None:
    """Tool nova em `mcp/leitura.py` sem caso aqui reprova — e caso órfão também.

    É a diferença entre uma guarda derivada e uma lista escrita de cabeça: a
    segunda concorda com quem a escreveu e envelhece no arquivo seguinte.
    """
    assert set(ferramentas_de_leitura(indice)) == set(CASOS_DE_CURSOR)


def _paginar_tudo(tool, caso: dict, orcamento: int) -> list[Any]:
    """Segue o cursor até o fim, exigindo que ele exista sempre que houver mais."""
    colhidos: list[Any] = []
    cursor: int | None = 0
    vistos = 0
    while cursor is not None:
        saida = tool(**caso["argumentos"], cursor=cursor, **{caso["orcamento"]: orcamento})
        pagina = saida[caso["lista"]]
        colhidos.extend(pagina)

        faltavam = saida["total"] - (len(colhidos))
        if faltavam > 0:
            assert "cursor_proximo" in saida, (
                f"a tool cortou {faltavam} item(ns) sem devolver cursor — é exatamente a "
                "resposta que faz o agente acreditar que viu tudo"
            )
            assert saida["restante"] == faltavam
        else:
            assert "cursor_proximo" not in saida, "cursor na última página faz o cliente girar"
        cursor = saida.get("cursor_proximo")

        vistos += 1
        assert vistos < 200, "a paginação não terminou — cursor que não avança é laço infinito"
    return colhidos


@pytest.mark.parametrize("nome", sorted(CASOS_DE_CURSOR))
def test_nenhuma_ferramenta_de_leitura_corta_sem_cursor(indice: Store, nome: str) -> None:
    """Orçamentos arbitrários, e a concatenação das páginas é a lista inteira.

    Sem perda e sem sobreposição: o agente que pagina até o fim tem cobertura
    total e nenhuma repetição, que é a garantia sobre a qual o `pack_folder` do
    `J.d` vai ser construído.
    """
    tools = ferramentas_de_leitura(indice)
    caso = CASOS_DE_CURSOR[nome]
    inteiro = _paginar_tudo(tools[nome], caso, 1000)
    assert inteiro, "o índice de teste tem itens para paginar"

    sorteio = random.Random(20260830)
    for _ in range(12):
        orcamento = sorteio.randint(1, max(2, len(inteiro) + 2))
        assert _paginar_tudo(tools[nome], caso, orcamento) == inteiro


def test_o_orcamento_pedido_tem_teto(indice: Store) -> None:
    """O custo de uma página é do cliente, então o servidor limita — como no `search`."""
    saida = ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA, max_itens=10**6)
    assert len(saida["itens"]) <= manifesto.LIMITE_ITENS_MAX


def test_a_paginacao_e_pura_e_nao_depende_de_ordem_de_chamada(indice: Store) -> None:
    """Pedir a página 2 antes da 1 devolve a mesma página 2."""
    tool = ferramentas_de_leitura(indice)["list_folder"]
    depois = tool(pasta=PASTA, recursivo=True, cursor=2, max_itens=2)["itens"]
    tool(pasta=PASTA, recursivo=True, cursor=0, max_itens=2)
    de_novo = tool(pasta=PASTA, recursivo=True, cursor=2, max_itens=2)["itens"]
    assert depois == de_novo


# --- o que a revisão achou ----------------------------------------------------


def test_item_cujo_id_resolve_para_outro_caminho_diz_isso(indice: Store) -> None:
    """Dois caminhos, um conteúdo, um id — e o id vai para **um** deles.

    Achado em revisão. Sem o campo, o manifesto lista dois itens com `id`
    idêntico, `outline` desse id devolve o preferido, e o agente que chaveie por
    id perde o outro item sem sinal nenhum.
    """
    mesmo = "f" * 64
    for path, mtime in (("Projetos/Alfa/Copia.docx", 100.0), ("Projetos/Alfa/Vigente.docx", 900.0)):
        indice.registrar_documento(
            path=path, raiz="acervo", tamanho=1, mtime=mtime, sha256=mesmo,
            status="ok", n_chunks=0, model_id="falso:8", chunker="v1", parser="p1",
        )
    indice.commit()

    itens = {i["arquivo"]: i for i in ferramentas_de_leitura(indice)["list_folder"](pasta=PASTA)["itens"]}
    copia, vigente = itens["Projetos/Alfa/Copia.docx"], itens["Projetos/Alfa/Vigente.docx"]

    assert copia["id"] == vigente["id"], "mesmo conteúdo, mesmo id — é o contrato do doc_id"
    assert copia["id_resolve_para"] == "Projetos/Alfa/Vigente.docx"
    assert "id_resolve_para" not in vigente, "o preferido não aponta para si mesmo"


def test_servidor_sem_base_declarada_recusa_uri_com_nome_de_base(indice: Store) -> None:
    """Achado em revisão: a conferência era no-op justamente onde mais importa.

    Sem `config.toml` o servidor sobe com três valores soltos e não tem nome para
    conferir contra. Aceitar qualquer `<base>` em silêncio entrega conteúdo deste
    índice a quem pediu outro acervo, achando que pediu certo.
    """
    saida = ferramentas_de_leitura(indice, base_id="")["outline"](
        documento=identidade.montar_uri("qualquer", "b" * 12)
    )
    assert "erro" in saida
    assert "sem base declarada" in saida["erro"]


def test_servidor_sem_base_declarada_aceita_caminho_e_id_nu(indice: Store) -> None:
    """A recusa é sobre o nome da base, não sobre a leitura."""
    tools = ferramentas_de_leitura(indice, base_id="")
    assert tools["outline"](documento="Projetos/Alfa/Plano_v2.docx")["secoes"]
    assert tools["outline"](documento="b" * 12)["secoes"]
