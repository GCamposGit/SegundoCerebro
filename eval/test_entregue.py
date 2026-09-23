"""O caminho entregue como recuperador de primeira classe.

O módulo nasceu para tornar mensurável um defeito: **o `peso_nome` era inerte em
`buscar_chunks`**. A `F4-P` consertou o defeito, e por isso os dois testes de
inércia daqui viraram os testes do conserto — é o que se espera deles. O que o
módulo continua guardando é o resto, que não dependia do defeito: o harness mede
os dois caminhos, o adaptador pede trechos que bastem, e o rótulo diz qual
caminho foi medido.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.entregue import FATOR_DE_CHUNKS, CaminhoEntregue
from eval.harness import Pergunta, avaliar
from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida
from tests.falsos import DIM, EmbedderFalso, chunk


@pytest.fixture
def indice(tmp_path: Path):
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    textos = {
        # O nome grita "politica de ia"; o corpo não fala do assunto.
        "Politicas/politica de ia.md": "documento normativo interno sem termo util",
        # O corpo trata do assunto; o nome não denuncia.
        "Projetos/anexo iii.md": "a classificacao de risco de inteligencia artificial",
        "Outros/nota.md": "assunto diverso sem relacao",
    }
    chunks = [chunk(f"c{i}", p, 0, t) for i, (p, t) in enumerate(textos.items())]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()
    yield store, emb
    store.fechar()


def _busca(indice, peso_nome: float, *, usar_lexical: bool = True) -> BuscaHibrida:
    store, emb = indice
    return BuscaHibrida(
        store,
        emb,
        candidatos=10,
        usar_lexical=usar_lexical,
        usar_nome=bool(peso_nome),
        peso_nome=peso_nome,
    )


def test_o_trecho_entregue_declara_que_veio_pelo_nome(indice) -> None:
    """Era o defeito inteiro em quatro linhas; agora é o conserto, pela procedência.

    Até 25/08/2026 este teste afirmava o contrário — `buscar_chunks` devolvia
    exatamente o mesmo com `peso_nome` 0 e 0,5, verificado também no índice
    corporativo com três consultas.

    A asserção não é "a ordem mudou", e a razão é o `C3.a`: com o bm25 ligado a
    coluna `caminho` do FTS5 já carrega o nome do arquivo, então num acervo de
    três documentos os dois braços **empatam** — e um teste que passasse por
    empate mediria a dupla contagem, não o ranqueador. Procedência não empata: o
    `origem` do trecho diz por quais ranqueadores ele entrou, e é invariante 5.
    """
    acertos = _busca(indice, 0.5).buscar_chunks("politica de ia", 3)
    origem = {a.path: a.origem for a in acertos}

    assert "nome" in origem["Politicas/politica de ia.md"]
    assert "nome" not in origem.get("Outros/nota.md", "")


def test_search_de_documento_sente_o_peso_do_nome(indice) -> None:
    """O outro lado do mesmo fato: no caminho que o eval mede, o peso pesa.

    O bm25 fica **desligado** aqui, e a razão é o próprio `C3.a`: a coluna
    `caminho` do FTS5 já carrega o nome do arquivo, então num acervo de três
    documentos ela sozinha promove o mesmo alvo e o ranqueador de nome não tem o
    que acrescentar. Com o lexical ligado este teste passava por empate, não por
    acerto — a dupla contagem escondendo o efeito que ele quer mostrar.
    """
    consulta = "politica de ia"
    sem = [h.path for h in _busca(indice, 0.0, usar_lexical=False).search(consulta, 3)]
    com = [h.path for h in _busca(indice, 0.5, usar_lexical=False).search(consulta, 3)]

    assert sem != com
    assert com[0] == "Politicas/politica de ia.md", "o nome promove o documento certo"


def test_sem_o_bm25_o_nome_e_o_unico_que_alcanca_o_documento(indice) -> None:
    """A fatia cross-lingual do dourado, em miniatura — e o aceite da `F4-P`.

    Com o bm25 desligado, a coluna `caminho` do FTS5 sai de cena e o alvo passa a
    ser inalcançável por conteúdo: o nome grita o assunto e o corpo não fala
    dele. É a forma exata das três perguntas cross-lingual que o caminho entregue
    não alcançava nem em vinte posições (`docs/ablacao-caminho-entregue.md`) — o
    nome do arquivo era a ponte PT↔EN, e a ponte não existia neste caminho.

    Este teste é o que fica vermelho se `_nome_por_chunk` for removido, e ele
    afirma **presença**, não posição: a métrica que a `F4-P` tem de mover é
    recall@20, e recall é alcance.
    """
    consulta = "politica de ia"
    alvo = "Politicas/politica de ia.md"
    sem = CaminhoEntregue(interno=_busca(indice, 0.0, usar_lexical=False))
    com = CaminhoEntregue(interno=_busca(indice, 0.5, usar_lexical=False))

    assert alvo not in [h.path for h in sem.search(consulta, 3)]
    assert alvo in [h.path for h in com.search(consulta, 3)]


def test_rotulo_diz_qual_caminho_foi_medido(indice) -> None:
    """Relatório que diga só "híbrido" é indistinguível do que mediu o outro caminho."""
    nome = CaminhoEntregue(interno=_busca(indice, 0.5)).nome

    assert "buscar_chunks" in nome
    assert "caminho entregue" in nome


def test_documento_fica_com_a_posicao_do_seu_melhor_trecho(indice) -> None:
    """O mesmo colapso que `search` faz por dentro — senão mede-se a regra, não a busca."""
    store, emb = indice
    extra = chunk("c9", "Projetos/anexo iii.md", 1, "segundo trecho do mesmo arquivo")
    store.gravar_chunks([extra], emb.embed_passagens([extra.text]), mtime=1.0)
    store.commit()

    entregue = CaminhoEntregue(interno=_busca(indice, 0.5))
    caminhos = [h.path for h in entregue.search("classificacao de risco", 3)]

    assert len(caminhos) == len(set(caminhos)), "um documento aparece uma vez só"


def test_pede_trechos_suficientes_para_encher_k_documentos(indice) -> None:
    """`k` trechos rendem menos de `k` documentos — medido: 14 de 59 perguntas.

    O fator existe por causa disso, e baixá-lo faz o relatório dizer "o caminho
    entregue recupera menos" quando o que faltou foi o adaptador pedir o bastante.
    """
    pedidos: list[int] = []

    class _Espia:
        nome = "espia"

        def buscar_chunks(self, consulta: str, k: int, contexto: int = 0):
            pedidos.append(k)
            return []

    CaminhoEntregue(interno=_Espia()).search("qualquer", 20)

    assert pedidos == [20 * FATOR_DE_CHUNKS]


def test_entra_no_harness_como_recuperador_qualquer(indice) -> None:
    """É o ponto do pacote: o caminho entregue passa a ser mensurável como os outros."""
    perguntas = [
        Pergunta(
            id="q1",
            tipo="semantica",
            pergunta="classificacao de risco de inteligencia artificial",
            fontes=("Projetos/anexo iii.md",),
            validada=True,
        )
    ]

    resultado = avaliar(CaminhoEntregue(interno=_busca(indice, 0.5)), perguntas)

    assert resultado.recall(1) == 1.0
    assert "buscar_chunks" in resultado.retriever


def test_recusa_na_montagem_quem_nao_tem_caminho_de_trecho() -> None:
    """`--entregue` sobre `baseline` falhava na primeira pergunta, não na montagem.

    Medindo a `F4-P.1` em 27/08/2026 a passada carregou índice e modelo, correu
    até a primeira consulta e morreu com `AttributeError` — sem dizer que o
    problema era a combinação de bandeiras. Classe: **combinação impossível falha
    na montagem, não no meio da passada.**
    """
    class SemTrecho:
        nome = "baseline (nome de arquivo)"

        def search(self, consulta: str, k: int) -> list:
            return []

    with pytest.raises(TypeError, match="não tem esse caminho"):
        CaminhoEntregue(interno=SemTrecho())


def test_aceita_quem_tem_buscar_chunks() -> None:
    class ComTrecho:
        nome = "hibrido"

        def buscar_chunks(self, consulta: str, k: int) -> list:
            return []

    assert CaminhoEntregue(interno=ComTrecho()).nome.endswith("caminho entregue (buscar_chunks)")


def test_a_prosa_do_relatorio_nao_pode_contradizer_o_codigo() -> None:
    """O texto que o relatório imprime sobre este caminho tem de bater com o que roda.

    Até 27/08/2026 o `--entregue` imprimia, em todo relatório: *"o
    `RanqueadorDeNome` **não participa** deste caminho"*. Era verdade até a
    `F4-P` (25/08) criar `BuscaHibrida._nome_por_chunk` e levar o sinal de nome
    para `buscar_chunks`. Ficaram dois dias — e a `F4-P.1`, cujo assunto é
    exatamente o peso do nome nesse caminho, teria saído com um parágrafo
    dizendo ao leitor que a medição não media nada.

    O **comportamento** já tinha teste (`tests/test_hybrid.py`); a **prosa** não
    tinha nenhum. Classe: *relatório que se explica com um fato que deixou de ser
    verdade* — e nada falha, porque cada metade está certa sozinha.
    """
    import inspect

    from eval import rodar
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    fonte = inspect.getsource(rodar._montar)
    participa = hasattr(BuscaHibrida, "_nome_por_chunk")

    if participa:
        assert "não participa" not in fonte, (
            "o relatório do `--entregue` afirma que o ranqueador de nome não participa "
            "deste caminho, e `BuscaHibrida._nome_por_chunk` existe — a prosa está "
            "atrasada em relação ao código"
        )
        assert "_nome_por_chunk" in fonte, (
            "o sinal de nome participa do caminho entregue e o relatório não explica "
            "como; quem lê a ablação precisa saber que trecho recebe a contribuição"
        )
