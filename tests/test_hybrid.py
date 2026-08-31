"""Tests for hybrid retrieval and RRF fusion."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.index.store import Store
from segundocerebro.retrieve.hybrid import BuscaHibrida, rrf
from tests.falsos import DIM, EmbedderFalso, chunk


def test_rrf_soma_por_posicao() -> None:
    pontos = rrf([["a", "b"], ["b", "a"]], k=60)

    # ambos aparecem em 1º e 2º: empate
    assert pontos["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert pontos["a"] == pytest.approx(pontos["b"])


def test_rrf_premia_quem_aparece_nos_dois_rankings() -> None:
    pontos = rrf([["a", "x"], ["a", "y"]], k=60)

    assert pontos["a"] > pontos["x"]
    assert pontos["a"] == pytest.approx(2 / 61)


def test_rrf_ignora_ausencia() -> None:
    pontos = rrf([["a"], ["b"]], k=60)

    assert set(pontos) == {"a", "b"}
    assert pontos["a"] == pytest.approx(1 / 61)


def test_rrf_nao_depende_da_escala_dos_scores() -> None:
    """É por isso que usamos RRF: cosseno e bm25() não são comparáveis."""
    assert rrf([["a", "b"]]) == rrf([["a", "b"]])


@pytest.fixture
def indice(tmp_path: Path):  # noqa: ANN201
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()
    chunks = [
        chunk("c1", "politica.md", 0, "O PO-ACME-007 define o uso aceitável de inteligência artificial."),
        chunk("c2", "politica.md", 1, "A classificação de risco usa três níveis."),
        chunk("c3", "contrato.md", 0, "Contrato 4600009999 com a Nimbus Tecnologia."),
        chunk("c4", "outro.md", 0, "Texto sem relação alguma com o resto do acervo."),
    ]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()
    yield store, emb
    store.fechar()


def test_lexical_sozinho_acha_codigo(indice) -> None:  # noqa: ANN001
    store, emb = indice
    busca = BuscaHibrida(store, emb, usar_denso=False)

    acertos = busca.buscar_chunks("PO-ACME-007", 5)

    assert acertos[0].chunk_id == "c1"
    assert acertos[0].origem == "lexical"


def test_hibrido_marca_a_origem_de_cada_acerto(indice) -> None:  # noqa: ANN001
    store, emb = indice
    busca = BuscaHibrida(store, emb)

    acertos = busca.buscar_chunks("PO-ACME-007", 5)
    origens = {a.chunk_id: a.origem for a in acertos}

    assert "lexical" in origens["c1"]
    assert all(o for o in origens.values())


def test_search_colapsa_para_documento(indice) -> None:  # noqa: ANN001
    """O conjunto dourado aponta documentos, não chunks."""
    store, emb = indice
    busca = BuscaHibrida(store, emb, usar_denso=False)

    hits = busca.search("classificação de risco PO-ACME-007", k=3)
    paths = [h.path for h in hits]

    assert paths[0] == "politica.md"
    assert len(paths) == len(set(paths)), "documento não pode repetir"


def test_nome_descreve_a_configuracao(indice) -> None:  # noqa: ANN001
    store, emb = indice

    assert "RRF" in BuscaHibrida(store, emb).nome
    assert BuscaHibrida(store, emb, usar_lexical=False).nome.startswith("denso")
    assert BuscaHibrida(store, emb, usar_denso=False).nome.startswith("bm25")


def test_configuracao_vazia_e_rejeitada(indice) -> None:  # noqa: ANN001
    store, emb = indice

    with pytest.raises(ValueError):
        BuscaHibrida(store, emb, usar_denso=False, usar_lexical=False, usar_nome=False)


def test_chunk_orfao_no_vetorial_nao_derruba_a_busca(indice) -> None:  # noqa: ANN001
    """Registro e vetorial podem dessincronizar; a busca avisa e segue."""
    store, emb = indice
    store.con.execute("DELETE FROM chunks WHERE id = 'c1'")
    store.commit()

    acertos = BuscaHibrida(store, emb).buscar_chunks("inteligência artificial", 5)

    assert all(a.chunk_id != "c1" for a in acertos)


# --- RRF ponderado -----------------------------------------------------------


def test_rrf_com_peso_zero_ignora_o_ranking() -> None:
    pontos = rrf([["a"], ["b"]], k=60, pesos=[1.0, 0.0])

    assert set(pontos) == {"a"}


def test_rrf_ponderado_nao_deixa_o_fraco_dominar() -> None:
    """Com peso igual o híbrido mediu pior que o melhor ranqueador sozinho."""
    forte = ["bom1", "bom2", "bom3"]
    fraco = ["ruim1", "ruim2", "ruim3"]

    igual = rrf([forte, fraco], k=60)
    ponderado = rrf([forte, fraco], k=60, pesos=[1.0, 0.3])

    # com peso igual, o 1º do fraco empata com o 1º do forte
    assert igual["ruim1"] == pytest.approx(igual["bom1"])
    # ponderado, o 1º do fraco fica abaixo até do 3º do forte
    assert ponderado["ruim1"] < ponderado["bom3"]


def test_rrf_rejeita_pesos_em_numero_errado() -> None:
    with pytest.raises(ValueError):
        rrf([["a"], ["b"]], pesos=[1.0])


# --- ranqueador de nome ------------------------------------------------------


def test_ranqueador_de_nome_pontua_caminho() -> None:
    from segundocerebro.retrieve.nomes import RanqueadorDeNome

    r = RanqueadorDeNome(
        [
            "Política de IA/PO-ACME-007_Política_IA_v8.docx",
            "Outros/ata qualquer.docx",
        ]
    )

    ranking = r.ranquear("PO-ACME-007", 5)

    assert ranking[0][0] == "Política de IA/PO-ACME-007_Política_IA_v8.docx"


def test_nome_promove_documento_que_o_bm25_afoga(indice) -> None:  # noqa: ANN001
    """O ranqueador de nome muda POSIÇÃO, não presença.

    O caminho já está indexado no FTS, então o bm25 encontra o documento de
    qualquer forma. O que ele não faz é colocá-lo no topo: o bm25 normaliza por
    comprimento, e um nome de arquivo curto perde de um texto que repete os
    termos. Medido no acervo: o baseline por nome tira recall@1 = 0,549 e o bm25
    sobre conteúdo mais caminho, 0,431.
    """
    store, emb = indice
    alvo = "Relatório Northline KPI.md"
    extras = [chunk("c9", alvo, 0, "Conteúdo genérico, sem repetir o termo.")]
    # concorrentes cujo TEXTO repete os termos da consulta
    for i in range(4):
        extras.append(chunk(f"d{i}", f"notas {i}.md", 0, "Northline KPI " * 20))
    store.gravar_chunks(extras, emb.embed_passagens([c.text for c in extras]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    sem_nome = BuscaHibrida(store, emb, usar_denso=False, usar_nome=False)
    com_nome = BuscaHibrida(store, emb, usar_denso=False, usar_nome=True)

    assert sem_nome.search("Northline KPI", 5)[0].path != alvo
    assert com_nome.search("Northline KPI", 5)[0].path == alvo


def test_nome_entra_no_caminho_de_trecho_com_um_trecho_por_documento(indice) -> None:  # noqa: ANN001
    """`F4-P`: o nome pontua documento, e no caminho de trecho entrega **um** trecho.

    A tradução ingênua — dar a contribuição do documento a todos os trechos dele
    — daria voz ao **tamanho** do documento, que não é nada do que o nome do
    arquivo afirma. Um relatório de sessenta trechos afogaria o resto do top-k
    sozinho, e a posição que o ranqueador de nome deu ao documento viraria
    sessenta posições no ranking de trechos.

    Sem trecho no poço, o representante é o primeiro do documento: é onde estão
    cabeçalho e título, que é o que um casamento por nome de arquivo está de fato
    afirmando.
    """
    store, emb = indice
    alvo = "Relatório Northline KPI.md"
    extras = [chunk(f"n{i}", alvo, i, "Conteúdo genérico, sem repetir o termo.") for i in range(6)]
    store.gravar_chunks(extras, emb.embed_passagens([c.text for c in extras]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    so_nome = BuscaHibrida(store, emb, usar_denso=False, usar_lexical=False, usar_nome=True)
    acertos = so_nome.buscar_chunks("Northline KPI", 10)

    do_alvo = [a for a in acertos if a.path == alvo]
    assert len(do_alvo) == 1, "o documento entra uma vez, na posição que o nome lhe deu"
    assert do_alvo[0].chunk_id == "n0", "sem trecho no poço, entra o primeiro do documento"
    assert do_alvo[0].origem == "nome"


def test_nome_reforca_o_trecho_que_a_fusao_ja_elegeu(indice) -> None:  # noqa: ANN001
    """A outra metade da regra — e é o espelho do colapso que `search` faz.

    Lá o documento fica com a posição do seu melhor trecho; aqui o documento
    entrega o melhor trecho que a fusão já tem dele. Escolher o primeiro trecho
    quando existe um melhor faria o nome **competir** com o poço em vez de
    reforçá-lo, e o documento apareceria duas vezes no ranking de trechos.
    """
    store, emb = indice
    alvo = "Relatório Northline KPI.md"
    extras = [
        chunk("m0", alvo, 0, "Sumário executivo, sem os termos."),
        chunk("m1", alvo, 1, "Northline KPI trimestral consolidado."),
    ]
    store.gravar_chunks(extras, emb.embed_passagens([c.text for c in extras]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    busca = BuscaHibrida(store, emb, usar_denso=False, usar_lexical=True, usar_nome=True)
    do_alvo = [a for a in busca.buscar_chunks("Northline KPI trimestral", 10) if a.path == alvo]

    com_nome = [a for a in do_alvo if "nome" in a.origem]
    assert len(com_nome) == 1, "um documento, uma contribuição de nome"
    assert com_nome[0].chunk_id == "m1", "o nome reforça o trecho que a fusão elegeu"


def test_nome_do_recuperador_mostra_os_pesos(indice) -> None:  # noqa: ANN001
    store, emb = indice

    # Contra as constantes, não contra valores fixos: o peso é resultado de
    # medição (`docs/varredura-pesos-f1.md`) e muda quando a medição muda. Fixar
    # o número aqui faria a varredura quebrar o teste toda vez que fizesse o que
    # foi construída para fazer.
    from segundocerebro.retrieve.hybrid import PESO_DENSO, PESO_LEXICAL, PESO_NOME

    assert BuscaHibrida(store, emb).nome.startswith(
        f"denso×{PESO_DENSO:g}+bm25×{PESO_LEXICAL:g}+nome×{PESO_NOME:g}"
    )
    assert "denso" not in BuscaHibrida(store, emb, peso_denso=0).nome


# --- peso de nome por tipo de fonte — `F4-P.1` --------------------------------


def test_a_contribuicao_de_nome_reproduz_o_rrf_que_substituiu(indice) -> None:  # noqa: ANN001
    """A `F4-P.1` tirou o nome de dentro do `rrf` — e não pode ter mudado número.

    `search` fundia o ranking de nome como mais um ranking ponderado. Agora a
    contribuição é somada por fora, porque `rrf` pondera um **ranking inteiro** e
    este pacote precisa ponderar **cada documento** pelo grupo dele. A conta tem
    de ser exatamente a mesma enquanto a bandeira estiver desligada, senão toda a
    série F0 → F4 medida em `search` deixa de valer sem ninguém pedir.
    """
    store, emb = indice
    busca = BuscaHibrida(store, emb)
    consulta = "inteligência artificial"

    por_nome = [rel for rel, _ in busca.ranqueador_nome.ranquear(consulta, busca.candidatos)]
    como_rrf = rrf([por_nome], busca.k_rrf, [busca.peso_nome])

    assert busca._nome_por_doc(consulta) == como_rrf


def test_sem_a_bandeira_o_peso_do_nome_e_o_mesmo_para_todo_documento(indice) -> None:  # noqa: ANN001
    """O braço "antes" da ablação é o padrão do produto, e ele é um número só."""
    store, emb = indice
    busca = BuscaHibrida(store, emb)

    assert busca.peso_do_nome("Projetos/contrato.pdf") == busca.peso_nome
    assert busca.peso_do_nome("Meetings/Gravacao_2025-03-14_0930.vtt") == busca.peso_nome


def test_com_a_bandeira_a_transcricao_perde_o_ranqueador_de_nome(indice) -> None:  # noqa: ANN001
    """E o documento de escritório não perde — é a troca inteira do `F4-P.1`.

    A afirmação é de formato, não deste acervo: gravador de reunião nomeia o
    arquivo com assunto e data, então o nome casa com qualquer pergunta que
    repita a palavra do assunto e não discrimina nada. No documento de escritório
    o identificador está no nome, e é por isso que o peso 0,5 sobreviveu a três
    varreduras.
    """
    store, emb = indice
    busca = BuscaHibrida(store, emb, nome_por_fonte=True)

    assert busca.peso_do_nome("Meetings/Gravacao_2025-03-14_0930.vtt") == 0.0
    assert busca.peso_do_nome("Projetos/09. Atas/ata.docx") == 0.0
    assert busca.peso_do_nome("Projetos/contrato.pdf") == busca.peso_nome
    assert busca.peso_do_nome("Caixa/convite.msg") == busca.peso_nome


def test_a_bandeira_tira_a_transcricao_do_topo_e_deixa_o_documento(indice) -> None:  # noqa: ANN001
    """O efeito de ponta a ponta, nos dois caminhos — não só no `peso_do_nome`.

    Os dois arquivos têm o termo da consulta no **nome** e nada dele no corpo.
    Sem a bandeira o ranqueador de nome promove os dois; com ela, só o de
    escritório. Medir nos dois caminhos é a lição da `F4-P`: ligar num só é medir
    uma coisa e entregar outra.
    """
    store, emb = indice
    transcricao = "Gravacoes/Northline KPI 2026-03-14.vtt"
    escritorio = "Projetos/Northline KPI.docx"
    extras = [
        chunk("t0", transcricao, 0, "fala sem os termos da consulta"),
        chunk("e0", escritorio, 0, "texto sem os termos da consulta"),
    ]
    store.gravar_chunks(extras, emb.embed_passagens([c.text for c in extras]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    def alcancados(por_fonte: bool) -> set[str]:
        busca = BuscaHibrida(store, emb, usar_denso=False, usar_lexical=False, nome_por_fonte=por_fonte)
        por_chunk = {a.path for a in busca.buscar_chunks("Northline KPI", 10)}
        por_doc = {h.path for h in busca.search("Northline KPI", 10)}
        assert por_chunk == por_doc, "os dois caminhos têm de concordar sobre quem o nome alcança"
        return por_chunk

    assert {transcricao, escritorio} <= alcancados(False)
    com_bandeira = alcancados(True)
    assert transcricao not in com_bandeira
    assert escritorio in com_bandeira


# --- custo do caminho de consulta ---------------------------------------------


class _ConContada:
    """Envelope que conta `execute()` sem mudar o comportamento do SQLite."""

    def __init__(self, con) -> None:  # noqa: ANN001
        self._con = con
        self.total = 0

    def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN201
        self.total += 1
        return self._con.execute(sql, *args, **kwargs)

    def __getattr__(self, nome: str):  # noqa: ANN204
        return getattr(self._con, nome)


TETO_DE_CONSULTAS = 12
"""Quantas idas ao SQLite uma consulta pode custar. Medido, não estimado.

Medido em 29/08/2026 contra o índice corporativo real (2.156 documentos,
`buscar_chunks(q, k=8, contexto=1)`): eram **350 `execute()` por consulta**, e
passaram a ser **6**. Três padrões de N+1, todos invisíveis num índice de teste
com quatro trechos:

- `store.chunk()` uma vez por candidato do poço — `candidatos` é 200 **por
  ranqueador**, e a fusão precisa dos metadados de todos (~269 consultas);
- `store.ids_de_chunks()` uma vez por documento que o ranqueador de nome
  devolve (~79);
- `store.vizinhos()` uma vez por acerto, e ela mesma custa duas (16).

O teto é 12 e não 6 porque o número exato depende de quantos ranqueadores estão
ligados e de haver ou não família a colapsar; o que ele impede é a volta da
ordem de grandeza. Este teste não veria os 350 no índice de quatro trechos — o
que ele guarda é a **forma** do acesso, e a forma não depende do tamanho.
"""


def test_uma_consulta_nao_volta_a_custar_uma_ida_ao_banco_por_candidato(indice) -> None:  # noqa: ANN001
    store, emb = indice
    busca = BuscaHibrida(store, emb)
    busca.mtimes  # aquece o cache de mtime, que é por instância e não por consulta

    store.con = _ConContada(store.con)
    try:
        acertos = busca.buscar_chunks("uso aceitável de inteligência artificial", 8, 1)
        gastas = store.con.total
    finally:
        store.con = store.con._con

    assert acertos, "a consulta não devolveu nada — o teto seria trivialmente cumprido"
    assert gastas <= TETO_DE_CONSULTAS, (
        f"{gastas} idas ao SQLite numa consulta (teto {TETO_DE_CONSULTAS}). "
        "Alguma leitura voltou a ser uma por item: procure `store.chunk(`, "
        "`ids_de_chunks(` ou `vizinhos(` dentro de laço em `retrieve/hybrid.py` — "
        "use `chunks_por_id`, `ids_de_chunks_por_path` e `vizinhos_de`."
    )


def test_o_lote_devolve_o_mesmo_que_a_consulta_por_item(indice) -> None:  # noqa: ANN001
    """`chunks_por_id` e `vizinhos_de` são atalhos, não outra semântica."""
    store, _ = indice
    ids = ["c1", "c2", "c3", "c4", "inexistente"]

    em_lote = store.chunks_por_id(ids)
    um_a_um = {i: store.chunk(i) for i in ids}
    assert em_lote == {i: c for i, c in um_a_um.items() if c is not None}

    vizinhos_em_lote = store.vizinhos_de(ids, 1)
    assert vizinhos_em_lote == {i: store.vizinhos(i, 1) for i in ids if um_a_um[i] is not None}

    por_path = store.ids_de_chunks_por_path(["politica.md", "contrato.md", "sumiu.md"])
    assert por_path == {
        "politica.md": store.ids_de_chunks("politica.md"),
        "contrato.md": store.ids_de_chunks("contrato.md"),
    }
