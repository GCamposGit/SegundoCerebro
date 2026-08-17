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

    class spec:  # noqa: N801
        id = "falso"
        prefixo_passagem = ""
        prefixo_consulta = ""

    def _vetor(self, texto: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for i, ch in enumerate(texto[:64]):
            v[i % self.dim] += ord(ch) % 7
        norma = float(np.linalg.norm(v))
        return v / norma if norma else v

    def embed_passagens(self, textos, batch_size: int = 32):  # noqa: ANN001, ARG002
        return [self._vetor(t) for t in textos]

    def embed_consulta(self, texto: str) -> np.ndarray:
        return self._vetor(texto)


@pytest.fixture
def servidor(tmp_path: Path):  # noqa: ANN201
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


def ferramentas(servidor) -> dict:  # noqa: ANN001
    import asyncio

    return {t.name: t for t in asyncio.run(servidor.list_tools())}


def chamar(servidor, nome: str, **kwargs) -> dict:  # noqa: ANN001
    """Devolve o conteúdo estruturado da ferramenta, que é o que o cliente lê."""
    import asyncio

    resultado = asyncio.run(servidor.call_tool(nome, kwargs))
    assert not resultado.is_error, resultado
    return resultado.structured_content


# --- o contrato da superfície -----------------------------------------------


def test_expoe_exatamente_duas_ferramentas(servidor) -> None:  # noqa: ANN001
    assert set(ferramentas(servidor)) == {"search", "read_note"}


def test_nenhuma_ferramenta_gera_texto(servidor) -> None:  # noqa: ANN001
    """Invariante 2 do ARCHITECTURE: nada de `answer`, `summarize`, `explain`.

    Uma ferramenta dessas reintroduziria custo por consulta e amarraria o projeto
    a um fornecedor — é a razão de o servidor existir só para recuperar.
    """
    proibidas = {"answer", "summarize", "explain", "responder", "resumir", "gerar"}
    nomes = set(ferramentas(servidor))

    assert not (nomes & proibidas)
    for t in ferramentas(servidor).values():
        assert not any(p in (t.description or "").lower() for p in ("gera", "resume", "responde a pergunta"))


def test_toda_ferramenta_descreve_quando_usar(servidor) -> None:  # noqa: ANN001
    """Sem descrição útil o cliente não escolhe a ferramenta certa."""
    for t in ferramentas(servidor).values():
        assert t.description and len(t.description) > 60, t.name


# --- search ------------------------------------------------------------------


def test_search_devolve_procedencia_em_todo_trecho(servidor) -> None:  # noqa: ANN001
    """Invariante 5: procedência e id estável em todo retorno."""
    saida = chamar(servidor, "search", consulta="governança de inteligência artificial", k=3)

    assert saida["encontrados"] > 0
    for trecho in saida["trechos"]:
        assert trecho["id"]
        assert trecho["arquivo"] == "Politica de IA/PO-ACME-007.docx"
        assert "secao" in trecho and "onde" in trecho
        assert trecho["texto"]


def test_search_respeita_o_teto_de_k(servidor) -> None:  # noqa: ANN001
    saida = chamar(servidor, "search", consulta="governança", k=999)
    assert len(saida["trechos"]) <= 50


def test_search_com_consulta_vazia_nao_explode(servidor) -> None:  # noqa: ANN001
    saida = chamar(servidor, "search", consulta="   ")
    assert saida["trechos"] == [] and "erro" in saida


# --- read_note ---------------------------------------------------------------


def test_read_note_traz_vizinhos_e_marca_o_pedido(servidor) -> None:  # noqa: ANN001
    saida = chamar(servidor, "read_note", id="doc1#2", janela=1)

    ids = [t["id"] for t in saida["trechos"]]
    assert ids == ["doc1#1", "doc1#2", "doc1#3"]
    assert [t["e_o_pedido"] for t in saida["trechos"]] == [False, True, False]


def test_read_note_com_janela_zero_traz_so_o_pedido(servidor) -> None:  # noqa: ANN001
    saida = chamar(servidor, "read_note", id="doc1#2", janela=0)
    assert [t["id"] for t in saida["trechos"]] == ["doc1#2"]


def test_read_note_de_id_inexistente_diz_o_que_houve(servidor) -> None:  # noqa: ANN001
    """Erro explícito em vez de lista vazia: lista vazia é indistinguível de 'não tem nada'."""
    saida = chamar(servidor, "read_note", id="nao-existe#9")

    assert saida["trechos"] == []
    assert "não encontrado" in saida["erro"]


def test_o_id_de_search_serve_para_read_note(servidor) -> None:  # noqa: ANN001
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


def _base(**kwargs):  # noqa: ANN002, ANN201
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
    assert set(ferramentas(servidor)) == {"search", "read_note"}


def test_search_anexa_vizinhos_sem_misturar_com_o_trecho(servidor) -> None:  # noqa: ANN001
    """"A resposta estava no parágrafo seguinte" — mas a procedência é do trecho.

    O vizinho vai em `antes`/`depois`, nunca dentro de `texto`: misturar faria o
    cliente citar como achado um texto que o ranqueador nunca pontuou.
    """
    dados = chamar(servidor, "search", consulta="contrato", k=1, contexto=1)
    trecho = dados["trechos"][0]

    vizinhanca = trecho.get("antes", "") + trecho.get("depois", "")
    assert vizinhanca, "o índice de teste tem vizinhos para expandir"
    assert trecho["texto"] not in vizinhanca
    assert vizinhanca not in trecho["texto"]


def test_search_sem_contexto_nao_traz_campos_vazios(servidor) -> None:  # noqa: ANN001
    """Campo vazio em todo retorno é contexto do cliente gasto à toa."""
    trecho = chamar(servidor, "search", consulta="contrato", k=1, contexto=0)["trechos"][0]
    assert "antes" not in trecho and "depois" not in trecho


def test_contexto_tem_teto(servidor) -> None:  # noqa: ANN001
    """O custo do contexto é do cliente, então o servidor limita."""
    from segundocerebro.mcp.server import CONTEXTO_MAX

    generoso = chamar(servidor, "search", consulta="contrato", k=1, contexto=99)["trechos"][0]
    no_teto = chamar(servidor, "search", consulta="contrato", k=1, contexto=CONTEXTO_MAX)["trechos"][0]
    assert generoso.get("antes", "") == no_teto.get("antes", "")
    assert generoso.get("depois", "") == no_teto.get("depois", "")


def test_vizinho_que_ja_e_acerto_nao_se_repete(servidor) -> None:  # noqa: ANN001
    """Repetir gastaria contexto e faria parecer que há mais fontes do que há."""
    dados = chamar(servidor, "search", consulta="contrato", k=8, contexto=1)
    textos = {t["texto"] for t in dados["trechos"]}
    for t in dados["trechos"]:
        for vizinho in (t.get("antes", ""), t.get("depois", "")):
            assert vizinho not in textos or not vizinho


def test_k_e_janela_saem_da_base(tmp_path: Path) -> None:
    from segundocerebro.config import Busca

    base = _base(id="a", indice=tmp_path / "i", busca=Busca(k=3, k_max=5, janela=2, janela_max=4))
    ferrs = ferramentas(construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1, base=base)))

    assert ferrs["search"].input_schema["properties"]["k"]["default"] == 3
    assert ferrs["read_note"].input_schema["properties"]["janela"]["default"] == 2
