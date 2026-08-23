"""O salto pelo grafo, como instrumento de medição.

A posição em que os vizinhos entram é o que este arquivo guarda, porque o
primeiro rascunho os anexava **no fim** — e ali eles caem depois do `k` que o
harness pede, então nenhuma métrica os conta. O número teria "provado" que o
grafo não serve para nada, com a medição toda correta e a conclusão invertida.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from eval.com_grafo import ComSaltoNoGrafo
from eval.harness import Hit
from segundocerebro.index.store import Store
from segundocerebro.retrieve.grafo import construir
from tests.test_index import DIM, EmbedderFalso, chunk


@dataclass
class BuscaFalsa:
    """Devolve uma lista fixa — o que se mede aqui é o salto, não a busca."""

    caminhos: list[str]
    nome: str = "falsa"

    def search(self, consulta: str, k: int) -> list[Hit]:  # noqa: ARG002
        return [Hit(path=p, score=1.0 - i / 100) for i, p in enumerate(self.caminhos)][:k]


@pytest.fixture
def indice(tmp_path: Path):  # noqa: ANN201
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    textos = {
        "plano.md": "meta: certificação ISO 42001",
        "norma.md": "a ISO 42001 define requisitos",
        "ruido1.md": "sem identificador",
        "ruido2.md": "também sem",
        "ruido3.md": "nem aqui",
    }
    chunks = [chunk(f"c{i}", p, 0, t) for i, (p, t) in enumerate(textos.items())]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.con.commit()
    construir(store)
    yield store
    store.fechar()


def test_vizinho_entra_dentro_do_k_pedido(indice) -> None:  # noqa: ANN001
    """O defeito que motivou o arquivo: no fim da lista, o vizinho é invisível.

    Com a busca já devolvendo `k` resultados, anexar depois põe o vizinho na
    posição `k+1` — fora de toda métrica. O salto tem que entrar **dentro** do
    corte.
    """
    busca = BuscaFalsa(["plano.md", "ruido1.md", "ruido2.md", "ruido3.md"])
    com = ComSaltoNoGrafo(interno=busca, store=indice)

    caminhos = [h.path for h in com.search("qualquer", k=4)]

    assert "norma.md" in caminhos
    assert caminhos.index("norma.md") < 4


def test_as_tres_primeiras_posicoes_ficam_intactas(indice) -> None:  # noqa: ANN001
    """É o que torna a leitura honesta: recall@1 e recall@3 não podem mudar.

    Se mudarem, o ganho medido veio de reordenação e não de alcance — e as duas
    coisas exigem conclusões diferentes.
    """
    originais = ["plano.md", "ruido1.md", "ruido2.md", "ruido3.md"]
    com = ComSaltoNoGrafo(interno=BuscaFalsa(originais), store=indice)

    caminhos = [h.path for h in com.search("qualquer", k=8)]

    assert caminhos[:3] == originais[:3]


def test_vizinho_que_ja_esta_no_resultado_nao_se_repete(indice) -> None:  # noqa: ANN001
    """Repetir inflaria o recall sem achar nada de novo."""
    com = ComSaltoNoGrafo(interno=BuscaFalsa(["plano.md", "norma.md"]), store=indice)

    caminhos = [h.path for h in com.search("qualquer", k=8)]

    assert caminhos.count("norma.md") == 1


def test_o_trecho_diz_por_que_o_vizinho_entrou(indice) -> None:  # noqa: ANN001
    """Relatório de ablação que diz só "veio do grafo" não permite conferir."""
    com = ComSaltoNoGrafo(interno=BuscaFalsa(["plano.md"]), store=indice)

    vizinho = next(h for h in com.search("q", k=8) if h.path == "norma.md")

    assert vizinho.trecho.startswith("[grafo]")
    assert "ISO 42001" in vizinho.trecho
    assert "plano.md" in vizinho.trecho


def test_sem_vizinho_a_lista_nao_muda(indice) -> None:  # noqa: ANN001
    originais = ["ruido1.md", "ruido2.md"]
    com = ComSaltoNoGrafo(interno=BuscaFalsa(originais), store=indice)

    assert [h.path for h in com.search("q", k=8)] == originais


def test_o_salto_parte_so_dos_primeiros(indice) -> None:  # noqa: ANN001
    """Um cliente não chama `neighbors` em cinquenta documentos.

    Com `expandir=1`, um `plano.md` na quarta posição não origina salto — e o
    vizinho dele não aparece.
    """
    busca = BuscaFalsa(["ruido1.md", "ruido2.md", "ruido3.md", "plano.md"])
    com = ComSaltoNoGrafo(interno=busca, store=indice, expandir=1)

    assert "norma.md" not in [h.path for h in com.search("q", k=8)]


def test_o_nome_do_recuperador_declara_o_salto(indice) -> None:  # noqa: ANN001
    """O relatório imprime o nome; um relatório que omite o salto descreve outro
    experimento — foi assim que uma medição de 17/08 passou por confirmação sem
    confirmar nada."""
    com = ComSaltoNoGrafo(interno=BuscaFalsa([]), store=indice)
    assert "salto no grafo" in com.nome
