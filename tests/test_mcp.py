"""A superfície MCP: o que ela devolve, e o que ela se recusa a fazer.

Os testes chamam as funções por trás das ferramentas em vez de subir o transporte
stdio: o que importa aqui é o contrato de retorno — procedência em tudo, id
estável, e nenhuma ferramenta que gere texto.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from segundocerebro.mcp.server import Recursos, construir


class EmbedderFalso:
    """Vetores determinísticos: o teste é sobre o contrato, não sobre semântica."""

    dim = 8
    model_id = "falso:8"

    class spec:
        id = "falso"
        prefixo_passagem = ""
        prefixo_consulta = ""

    def _vetor(self, texto: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for i, ch in enumerate(texto[:64]):
            v[i % self.dim] += ord(ch) % 7
        norma = float(np.linalg.norm(v))
        return v / norma if norma else v

    def embed_passagens(self, textos, batch_size: int = 32):
        return [self._vetor(t) for t in textos]

    def embed_consulta(self, texto: str) -> np.ndarray:
        return self._vetor(texto)


@pytest.fixture
def servidor(tmp_path: Path):
    """Índice minúsculo, montado à mão, com o embedder falso já plugado."""
    from segundocerebro.index.store import Store
    from segundocerebro.ingest.chunking import Chunk
    from segundocerebro.ingest.document import BlockKind

    emb = EmbedderFalso()
    store = Store(tmp_path / "indice", dim=emb.dim)

    chunks = [
        Chunk(
            id=f"doc1#{i}",
            doc_path="Politica de IA/PO-ACME-007.docx",
            ordinal=i,
            heading_path=("Política de IA", f"Seção {i}"),
            locator=f"p. {i}",
            kind=BlockKind.TEXT,
            text=f"Conteúdo da seção {i} sobre governança de inteligência artificial.",
        )
        for i in range(1, 4)
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)
    store.registrar_documento(
        path="Politica de IA/PO-ACME-007.docx",
        raiz="r",
        tamanho=1,
        mtime=0.0,
        status="ok",
        n_chunks=len(chunks),
        model_id=emb.model_id,
    )
    store.commit()

    recursos = Recursos(indice=tmp_path / "indice", modelo="falso", threads=1)
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)

    yield construir(recursos)
    store.fechar()


def ferramentas(servidor) -> dict:
    import asyncio

    return {t.name: t for t in asyncio.run(servidor.list_tools())}


def chamar(servidor, nome: str, **kwargs) -> dict:
    """Devolve o conteúdo estruturado da ferramenta, que é o que o cliente lê."""
    import asyncio

    resultado = asyncio.run(servidor.call_tool(nome, kwargs))
    assert not resultado.is_error, resultado
    return resultado.structured_content


def chamar_erro(servidor, nome: str, **kwargs) -> dict:
    """Chama a ferramenta e garante que devolveu erro operacional com is_error=True."""
    import asyncio

    resultado = asyncio.run(servidor.call_tool(nome, kwargs))
    assert resultado.is_error, resultado
    return resultado.structured_content



# --- o contrato da superfície -----------------------------------------------


SUPERFICIE = {
    "search",
    "read_note",
    "neighbors",
    "list_folder",
    "outline",
    "get_document",
    "pack_folder",
    "overview",
}
"""As sete ferramentas, e por que cada grupo está aqui.

`search` e `read_note` fecham o laço de **retrieval** — "onde está X" e "me
mostra o que tem em volta". `neighbors` entrou na F4 porque o traço de uso real
mostrou o limite concreto que ela rompe.

`list_folder` e `outline` entraram em 30/08/2026 pelo `J.c-mapa`, e não são mais
recuperação: são o **segundo modo de consumo** — enumerar e mapear, para o agente
que vai ler uma pasta inteira e precisa saber o que existe antes de gastar
contexto. `get_document` lê um; `pack_folder` cobre a pasta. Elas não ranqueiam.

`list_recent` e `glossary` continuam de fora: são hipóteses que o uso real não
confirmou.
"""


def test_expoe_exatamente_as_ferramentas_previstas(servidor) -> None:
    """A superfície é fechada de propósito."""
    assert set(ferramentas(servidor)) == SUPERFICIE


def test_nenhuma_ferramenta_gera_texto(servidor) -> None:
    """Invariante 2 do ARCHITECTURE: nada de `answer`, `summarize`, `explain`.

    Uma ferramenta dessas reintroduziria custo por consulta e amarraria o projeto
    a um fornecedor — é a razão de o servidor existir só para recuperar.
    """
    proibidas = {"answer", "summarize", "explain", "responder", "resumir", "gerar"}
    nomes = set(ferramentas(servidor))

    assert not (nomes & proibidas)
    for t in ferramentas(servidor).values():
        assert not any(
            p in (t.description or "").lower() for p in ("gera", "resume", "responde a pergunta")
        )


def test_toda_ferramenta_descreve_quando_usar(servidor) -> None:
    """Sem descrição útil o cliente não escolhe a ferramenta certa."""
    for t in ferramentas(servidor).values():
        assert t.description and len(t.description) > 60, t.name


# --- search ------------------------------------------------------------------


def test_search_devolve_procedencia_em_todo_trecho(servidor) -> None:
    """Invariante 5: procedência e id estável em todo retorno."""
    saida = chamar(servidor, "search", consulta="governança de inteligência artificial", k=3)

    assert saida["encontrados"] > 0
    for trecho in saida["trechos"]:
        assert trecho["id"]
        assert trecho["arquivo"] == "Politica de IA/PO-ACME-007.docx"
        assert "secao" in trecho and "onde" in trecho
        assert trecho["texto"]


def test_search_respeita_o_teto_de_k(servidor) -> None:
    saida = chamar(servidor, "search", consulta="governança", k=999)
    assert len(saida["trechos"]) <= 50


def test_search_com_consulta_vazia_nao_explode(servidor) -> None:
    saida = chamar_erro(servidor, "search", consulta="   ")
    assert saida["trechos"] == [] and "erro" in saida
    assert saida.get("codigo") == "consulta_vazia"



def test_search_com_filtros_temporais(servidor) -> None:
    """search respeita filtros depois_de e antes_de via chamada MCP."""
    saida_fora = chamar(
        servidor,
        "search",
        consulta="governança",
        depois_de="2020",
    )
    assert saida_fora["encontrados"] == 0
    assert saida_fora["trechos"] == []

    saida_dentro = chamar(
        servidor,
        "search",
        consulta="governança",
        antes_de="1975",
    )
    assert saida_dentro["encontrados"] > 0
    assert len(saida_dentro["trechos"]) > 0


def test_search_com_familias_e_formatos(tmp_path: Path) -> None:
    """C6: search expõe versoes, anteriores (com id, data, caminho) e formatos."""
    from segundocerebro.index.store import Store
    from segundocerebro.ingest.chunking import Chunk
    from segundocerebro.ingest.document import BlockKind
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    emb = EmbedderFalso()
    store = Store(tmp_path / "indice_c6", dim=emb.dim)

    chunks = [
        Chunk(
            id="c_v1", doc_path="IA/Plano_v1.docx", ordinal=1,
            heading_path=("Plano",), locator="p. 1", kind=BlockKind.TEXT,
            text="Estratégia corporativa de IA versão 1.",
        ),
        Chunk(
            id="c_v2", doc_path="IA/Plano_v2.docx", ordinal=1,
            heading_path=("Plano",), locator="p. 1", kind=BlockKind.TEXT,
            text="Estratégia corporativa de IA versão 2.",
        ),
        Chunk(
            id="c_pdf", doc_path="IA/Plano_v2.pdf", ordinal=1,
            heading_path=("Plano",), locator="p. 1", kind=BlockKind.TEXT,
            text="Estratégia corporativa de IA versão 2 em PDF.",
        ),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 100.0, emb.model_id)
    store.registrar_documento(
        path="IA/Plano_v1.docx", raiz="r", tamanho=10, mtime=100.0, status="ok", n_chunks=1, model_id=emb.model_id
    )
    store.registrar_documento(
        path="IA/Plano_v2.docx", raiz="r", tamanho=12, mtime=200.0, status="ok", n_chunks=1, model_id=emb.model_id
    )
    store.registrar_documento(
        path="IA/Plano_v2.pdf", raiz="r", tamanho=15, mtime=200.0, status="ok", n_chunks=1, model_id=emb.model_id
    )
    store.commit()

    recursos = Recursos(indice=tmp_path / "indice_c6", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    srv = construir(recursos)

    saida = chamar(srv, "search", consulta="estratégia corporativa", k=5)
    assert saida["encontrados"] == 1
    t = saida["trechos"][0]
    assert t["versoes"] == 2
    assert "anteriores" in t
    assert len(t["anteriores"]) == 1
    ant = t["anteriores"][0]
    assert ant["arquivo"] == "IA/Plano_v1.docx"
    assert ant["caminho"] == "IA/Plano_v1.docx"
    assert ant["id"] == "c_v1"
    assert ant["data"]

    assert "formatos" in t
    assert len(t["formatos"]) == 1
    fmt = t["formatos"][0]
    assert fmt["caminho"] in ("IA/Plano_v2.docx", "IA/Plano_v2.pdf")
    assert fmt["id"] in ("c_v2", "c_pdf")
    store.fechar()


# --- read_note ---------------------------------------------------------------


def test_read_note_traz_vizinhos_e_marca_o_pedido(servidor) -> None:
    saida = chamar(servidor, "read_note", id="doc1#2", janela=1)

    ids = [t["id"] for t in saida["trechos"]]
    assert ids == ["doc1#1", "doc1#2", "doc1#3"]
    assert [t["e_o_pedido"] for t in saida["trechos"]] == [False, True, False]


def test_read_note_com_janela_zero_traz_so_o_pedido(servidor) -> None:
    saida = chamar(servidor, "read_note", id="doc1#2", janela=0)
    assert [t["id"] for t in saida["trechos"]] == ["doc1#2"]


def test_read_note_de_id_inexistente_diz_o_que_houve(servidor) -> None:
    """Erro explícito em vez de lista vazia: lista vazia é indistinguível de 'não tem nada'."""
    saida = chamar_erro(servidor, "read_note", id="nao-existe#9")

    assert saida["trechos"] == []
    assert "não encontrado" in saida["erro"]
    assert saida.get("codigo") == "trecho_nao_encontrado"



def test_o_id_de_search_serve_para_read_note(servidor) -> None:
    """O laço que faz a superfície ser componível — e que quebra se o id não for estável."""
    achados = chamar(servidor, "search", consulta="governança", k=1)
    alvo = achados["trechos"][0]["id"]

    lido = chamar(servidor, "read_note", id=alvo, janela=0)

    assert lido["trechos"][0]["id"] == alvo


# --- carregamento tardio -----------------------------------------------------


def test_construir_nao_abre_o_indice(tmp_path: Path) -> None:
    """O modelo leva ~80 s para carregar; abrir no import estoura o handshake MCP.

    O modo de falha seria "servidor não conecta", que não diz nada sobre a causa.
    """
    recursos = Recursos(indice=tmp_path / "nao-existe", modelo="e5-large", threads=1)
    construir(recursos)

    assert recursos._busca is None and recursos._store is None


# --- a base configura a superfície -------------------------------------------


def _base(**kwargs):
    from segundocerebro.config import Base

    return Base(**kwargs)


def test_servidor_toma_nome_titulo_e_instrucoes_da_base(tmp_path: Path) -> None:
    """Com duas bases no mesmo cliente, a descrição é o sinal de roteamento.

    Não é enfeite: é o único critério pelo qual o modelo escolhe entre elas
    (`ARCHITECTURE.md` §2), e por isso precisa chegar até a `instructions`.
    """
    base = _base(
        id="trabalho",
        nome="Acme Holding",
        descricao="Contratos, propostas e atas da Acme Holding",
        indice=tmp_path / "i",
    )
    servidor = construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1, base=base))

    assert servidor.name == "segundocerebro-trabalho"
    assert servidor.title == "Acme Holding"
    assert "Contratos, propostas e atas da Acme Holding." in servidor.instructions


def test_base_unica_preserva_o_nome_historico(tmp_path: Path) -> None:
    """Quem já registrou `segundocerebro` no cliente não precisa mexer no JSON."""
    from segundocerebro.config import BASE_UNICA

    servidor = construir(
        Recursos(
            indice=tmp_path / "i",
            modelo="falso",
            threads=1,
            base=_base(id=BASE_UNICA, indice=tmp_path / "i"),
        )
    )
    assert servidor.name == "segundocerebro"


def test_sem_base_a_superficie_nao_muda(tmp_path: Path) -> None:
    """O servidor continua construível com três valores soltos."""
    servidor = construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1))

    assert servidor.name == "segundocerebro"
    assert set(ferramentas(servidor)) == SUPERFICIE


def test_search_anexa_vizinhos_sem_misturar_com_o_trecho(servidor) -> None:
    """ "A resposta estava no parágrafo seguinte" — mas a procedência é do trecho.

    O vizinho vai em `antes`/`depois`, nunca dentro de `texto`: misturar faria o
    cliente citar como achado um texto que o ranqueador nunca pontuou.
    """
    dados = chamar(servidor, "search", consulta="contrato", k=1, contexto=1)
    trecho = dados["trechos"][0]

    vizinhanca = trecho.get("antes", "") + trecho.get("depois", "")
    assert vizinhanca, "o índice de teste tem vizinhos para expandir"
    assert trecho["texto"] not in vizinhanca
    assert vizinhanca not in trecho["texto"]


def test_search_sem_contexto_nao_traz_campos_vazios(servidor) -> None:
    """Campo vazio em todo retorno é contexto do cliente gasto à toa."""
    trecho = chamar(servidor, "search", consulta="contrato", k=1, contexto=0)["trechos"][0]
    assert "antes" not in trecho and "depois" not in trecho


def test_contexto_tem_teto(servidor) -> None:
    """O custo do contexto é do cliente, então o servidor limita."""
    from segundocerebro.mcp.server import CONTEXTO_MAX

    generoso = chamar(servidor, "search", consulta="contrato", k=1, contexto=99)["trechos"][0]
    no_teto = chamar(servidor, "search", consulta="contrato", k=1, contexto=CONTEXTO_MAX)[
        "trechos"
    ][0]
    assert generoso.get("antes", "") == no_teto.get("antes", "")
    assert generoso.get("depois", "") == no_teto.get("depois", "")


def test_vizinho_que_ja_e_acerto_nao_se_repete(servidor) -> None:
    """Repetir gastaria contexto e faria parecer que há mais fontes do que há."""
    dados = chamar(servidor, "search", consulta="contrato", k=8, contexto=1)
    textos = {t["texto"] for t in dados["trechos"]}
    for t in dados["trechos"]:
        for vizinho in (t.get("antes", ""), t.get("depois", "")):
            assert vizinho not in textos or not vizinho


def test_k_e_janela_saem_da_base(tmp_path: Path) -> None:
    from segundocerebro.config import Busca

    base = _base(id="a", indice=tmp_path / "i", busca=Busca(k=3, k_max=5, janela=2, janela_max=4))
    ferrs = ferramentas(
        construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1, base=base))
    )

    assert ferrs["search"].input_schema["properties"]["k"]["default"] == 3
    assert ferrs["read_note"].input_schema["properties"]["janela"]["default"] == 2


# --- neighbors: a aresta que a busca por texto não alcança -------------------


def test_neighbors_avisa_quando_o_grafo_nunca_foi_construido(servidor) -> None:
    """Grafo vazio e documento sem vizinho devolvem a mesma lista, e são coisas
    diferentes.

    Sem o aviso, um grafo não construído parece um acervo sem ligações — e
    ninguém investiga o que parece resposta legítima. É o modo de falha mais
    provável desta ferramenta, porque a passada do grafo é separada da indexação.
    """
    dados = chamar(servidor, "neighbors", arquivo="Politica de IA/PO-ACME-007.docx")

    assert dados["vizinhos"] == []
    assert "grafo" in dados["aviso"]
    assert "segundocerebro.retrieve.grafo" in dados["aviso"]


def test_neighbors_liga_documentos_por_norma_citada(tmp_path: Path) -> None:
    """O caso que motiva a F4: pastas diferentes, nomes diferentes, nenhum termo
    em comum — só a norma que os dois citam."""
    from segundocerebro.index.store import Store
    from segundocerebro.retrieve.grafo import construir as construir_grafo
    from segundocerebro.retrieve.hybrid import BuscaHibrida
    from tests.falsos import DIM, EmbedderFalso, chunk

    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    chunks = [
        chunk("p1", "Politicas/plano_de_acao.md", 0, "meta do plano: certificação ISO 42001"),
        chunk("n1", "Normas/gestao.md", 0, "a ISO 42001 define o sistema de gestão de IA"),
        chunk("o1", "Obras/medicao.md", 0, "quantidades medidas no trecho sul"),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)
    store.commit()
    construir_grafo(store)

    recursos = Recursos(indice=tmp_path / "indice", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    servidor = construir(recursos)

    dados = chamar(servidor, "neighbors", arquivo="Politicas/plano_de_acao.md")

    assert [v["arquivo"] for v in dados["vizinhos"]] == ["Normas/gestao.md"]
    porque = dados["vizinhos"][0]["porque"][0]
    assert porque["identificador"] == "ISO 42001"
    assert porque["tipo"] == "norma"
    assert "aviso" not in dados
    store.fechar()


def test_neighbors_devolve_id_que_serve_para_read_note(tmp_path: Path) -> None:
    """O motivo tem que ser conferível, senão a ferramenta é um oráculo.

    O `id` no `porque` é o trecho onde o vizinho cita o identificador — passar
    esse id a `read_note` é como o cliente confirma que a ligação é real.
    """
    from segundocerebro.index.store import Store
    from segundocerebro.retrieve.grafo import construir as construir_grafo
    from segundocerebro.retrieve.hybrid import BuscaHibrida
    from tests.falsos import DIM, EmbedderFalso, chunk

    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    chunks = [
        chunk("a1", "a.md", 0, "prevê a ISO 42001"),
        chunk("b1", "b.md", 0, "a ISO 42001 exige requisitos"),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)
    store.commit()
    construir_grafo(store)

    recursos = Recursos(indice=tmp_path / "indice", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    servidor = construir(recursos)

    id_do_motivo = chamar(servidor, "neighbors", arquivo="a.md")["vizinhos"][0]["porque"][0]["id"]
    lido = chamar(servidor, "read_note", id=id_do_motivo, janela=0)

    assert lido["documento"] == "b.md"
    assert "ISO 42001" in lido["trechos"][0]["texto"]
    store.fechar()


def test_neighbors_com_arquivo_vazio_nao_explode(servidor) -> None:
    dados = chamar_erro(servidor, "neighbors", arquivo="   ")
    assert dados["vizinhos"] == []
    assert "erro" in dados
    assert dados.get("codigo") == "arquivo_vazio"



def test_neighbors_respeita_o_teto_do_limite(servidor) -> None:
    """Cada vizinho custa contexto do cliente."""
    ferrs = ferramentas(servidor)
    assert ferrs["neighbors"].input_schema["properties"]["limite"]["default"] == 5
    dados = chamar(servidor, "neighbors", arquivo="qualquer.md", limite=9999)
    assert dados["vizinhos"] == []


# --- filtros e modo de auditoria do search (PR-F1) ----------------------------


def test_search_com_filtro_de_pasta_restringe_acertos(servidor) -> None:
    """Restringe a busca apenas aos documentos contidos no prefixo de pasta."""
    achados = chamar(servidor, "search", consulta="governança", pasta="Politica de IA")
    assert achados["encontrados"] > 0
    assert all(t["arquivo"].startswith("Politica de IA/") for t in achados["trechos"])


def test_search_com_pasta_inexistente_devolve_vazio(servidor) -> None:
    """Pasta sem documentos devolve lista limpa e zero encontrados."""
    achados = chamar(servidor, "search", consulta="governança", pasta="Projetos/Desconhecido")
    assert achados["encontrados"] == 0
    assert achados["trechos"] == []


def test_search_normaliza_separador_de_pasta_windows(servidor) -> None:
    """Barras invertidas ou barras no final são tratadas de forma transparente."""
    achados = chamar(servidor, "search", consulta="governança", pasta="Politica de IA\\")
    assert achados["encontrados"] > 0
    assert all(t["arquivo"].startswith("Politica de IA/") for t in achados["trechos"])


def test_search_incluir_versoes_antigas_preserva_minutas_superadas(tmp_path: Path) -> None:
    """Sem flag, a versão superada é omitida pelo colapso de famílias; com flag, ambas vêm."""
    from segundocerebro.index.store import Store
    from segundocerebro.ingest.chunking import Chunk
    from segundocerebro.ingest.document import BlockKind
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    emb = EmbedderFalso()
    store = Store(tmp_path / "indice_versoes", dim=emb.dim)
    chunks = [
        Chunk(
            id="v1#1",
            doc_path="Contratos/Minuta_v1.docx",
            ordinal=1,
            heading_path=("Contrato",),
            locator="p. 1",
            kind=BlockKind.TEXT,
            text="Cláusula de confidencialidade e rescisão comercial v1.",
        ),
        Chunk(
            id="v2#1",
            doc_path="Contratos/Minuta_v2.docx",
            ordinal=1,
            heading_path=("Contrato",),
            locator="p. 1",
            kind=BlockKind.TEXT,
            text="Cláusula de confidencialidade e rescisão comercial v2.",
        ),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)
    store.registrar_documento(
        path="Contratos/Minuta_v1.docx",
        raiz="r",
        tamanho=100,
        mtime=1000.0,
        status="ok",
        n_chunks=1,
        model_id=emb.model_id,
    )
    store.registrar_documento(
        path="Contratos/Minuta_v2.docx",
        raiz="r",
        tamanho=100,
        mtime=2000.0,
        status="ok",
        n_chunks=1,
        model_id=emb.model_id,
    )
    store.commit()

    recursos = Recursos(indice=tmp_path / "indice_versoes", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    srv = construir(recursos)

    # Por padrão (incluir_versoes_antigas=False): colapsa e devolve apenas v2 (mtime maior)
    padrao = chamar(srv, "search", consulta="confidencialidade", pasta="Contratos")
    arquivos_padrao = {t["arquivo"] for t in padrao["trechos"]}
    assert "Contratos/Minuta_v2.docx" in arquivos_padrao
    assert "Contratos/Minuta_v1.docx" not in arquivos_padrao

    # Com auditoria histórica (incluir_versoes_antigas=True): devolve v1 e v2
    auditoria = chamar(
        srv,
        "search",
        consulta="confidencialidade",
        pasta="Contratos",
        incluir_versoes_antigas=True,
    )
    arquivos_auditoria = {t["arquivo"] for t in auditoria["trechos"]}
    assert "Contratos/Minuta_v1.docx" in arquivos_auditoria
    assert "Contratos/Minuta_v2.docx" in arquivos_auditoria
    store.fechar()


# --- overview (R7.1) ---------------------------------------------------------


def test_overview_retorna_resumo_completo_da_base(servidor) -> None:
    """overview devolve documento total, chunks, formatos e pastas da base de teste."""
    dados = chamar(servidor, "overview")
    assert dados["documentos_total"] > 0
    assert dados["chunks_total"] > 0
    assert "mais_antigo" in dados["periodo"]
    assert "mais_recente" in dados["periodo"]
    assert "taxa_indexacao" in dados["status"]
    assert any(f["extensao"] == ".docx" for f in dados["formatos"])
    assert any(p["pasta"] == "Politica de IA" for p in dados["pastas_raiz"])


def test_overview_com_datas_reais_formata_periodo(tmp_path: Path) -> None:
    """Documentos com mtime real produzem datas ISO no período."""
    from segundocerebro.index.store import Store
    from segundocerebro.retrieve.hybrid import BuscaHibrida
    from tests.falsos import DIM, EmbedderFalso

    store = Store(tmp_path / "indice_com_datas", dim=DIM)
    emb = EmbedderFalso()
    store.registrar_documento(
        path="Doc1.txt",
        raiz="r",
        tamanho=10,
        mtime=1704067200.0,
        status="ok",
        n_chunks=1,
        model_id=emb.model_id,
    )
    store.registrar_documento(
        path="Doc2.txt",
        raiz="r",
        tamanho=10,
        mtime=1735689600.0,
        status="ok",
        n_chunks=1,
        model_id=emb.model_id,
    )
    store.commit()

    recursos = Recursos(indice=tmp_path / "indice_com_datas", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    srv = construir(recursos)

    dados = chamar(srv, "overview")
    assert dados["periodo"]["mais_antigo"] == "2024-01-01"
    assert dados["periodo"]["mais_recente"] == "2025-01-01"
    store.fechar()


def test_overview_em_base_vazia_retorna_zeros(tmp_path: Path) -> None:
    """Base vazia não falha nem divide por zero: entrega zeros estruturados."""
    from segundocerebro.index.store import Store
    from segundocerebro.retrieve.hybrid import BuscaHibrida
    from tests.falsos import DIM, EmbedderFalso

    store = Store(tmp_path / "indice_vazio", dim=DIM)
    emb = EmbedderFalso()
    recursos = Recursos(indice=tmp_path / "indice_vazio", modelo="falso", threads=1)
    recursos._store = store
    recursos._busca = BuscaHibrida(store, emb)
    srv = construir(recursos)

    dados = chamar(srv, "overview")
    assert dados["documentos_total"] == 0
    assert dados["chunks_total"] == 0
    assert dados["periodo"]["mais_antigo"] is None
    assert dados["periodo"]["mais_recente"] is None
    assert dados["status"]["taxa_indexacao"] == 0.0
    assert dados["formatos"] == []
    assert dados["pastas_raiz"] == []
    store.fechar()


def test_overview_nao_expoe_caminhos_absolutos(servidor) -> None:
    """Nenhum caminho com barra invertida absoluta ou letra de unidade vaza."""
    dados = chamar(servidor, "overview")
    for item in dados["pastas_raiz"]:
        p = item["pasta"]
        assert not p.startswith(("/", "\\", "C:", "D:"))
