"""Grafo derivado: construção das menções e caminhada por elas.

O que se guarda aqui é o que separa aresta útil de cano de ruído. Um `neighbors`
que devolve muito é pior que um que devolve pouco: cada vizinho custa contexto do
cliente, e vem com procedência correta e motivo possivelmente inventado.

Vocabulário fictício da VCE, nunca do acervo real.
"""

from __future__ import annotations



from segundocerebro.index.store import Store
from segundocerebro.retrieve.grafo import (
    MAX_DOCUMENTOS_POR_ID,
    construir,
    desatualizado,
    vizinhos,
)
from tests.falsos import EmbedderFalso, chunk




def semear(store: Store, documentos: dict[str, str]) -> None:
    """Um chunk por documento — é o mínimo que o grafo precisa ler.

    O grafo não olha vetor nenhum, mas `gravar_chunks` exige um por chunk: ele é
    a porta única de escrita, e ter uma porta só é o que mantém o FTS em sincronia
    com a tabela. O embedder falso resolve sem carregar modelo.
    """
    emb = EmbedderFalso()
    chunks = [chunk(f"c{i}", path, 0, texto) for i, (path, texto) in enumerate(documentos.items())]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.con.commit()


# --- construção ---------------------------------------------------------------


def test_constroi_mencoes_a_partir_do_indice(store: Store) -> None:
    semear(
        store,
        {
            "Politicas/plano.md": "o plano prevê certificação ISO 42001 em dezembro",
            "Normas/norma.md": "a ISO 42001 estabelece requisitos de gestão de IA",
        },
    )
    resumo = construir(store)

    assert resumo["documentos"] == 2
    assert resumo["com_mencao"] == 2
    assert ("norma", "ISO 42001", "") != store.mencoes_de("Normas/norma.md")[0]
    assert [(t, v) for t, v, _ in store.mencoes_de("Normas/norma.md")] == [("norma", "ISO 42001")]


def test_construir_e_idempotente(store: Store) -> None:
    """Rodar duas vezes tem que dar o mesmo resultado.

    É o que torna a passada retomável sem marcador próprio — e o que impede o
    grafo de dobrar de tamanho a cada execução.
    """
    semear(store, {"a.md": "conforme a ISO 42001 e o CT-VCE-2024-0142"})
    primeiro = construir(store)
    segundo = construir(store)

    assert primeiro == segundo
    assert len(store.mencoes_de("a.md")) == 2


def test_identificador_removido_do_texto_sai_do_grafo(store: Store) -> None:
    """A aresta não pode sobreviver ao fato que a justificava.

    Documento editado para não mais citar a norma deixa de estar ligado a ela.
    Sem a substituição por documento, a menção antiga ficaria e a aresta
    continuaria aparecendo — com procedência que já não confere.
    """
    semear(store, {"a.md": "conforme a ISO 42001"})
    construir(store)
    assert store.mencoes_de("a.md")

    store.con.execute("UPDATE chunks SET texto = 'texto sem identificador' WHERE path = 'a.md'")
    store.con.commit()
    construir(store)

    assert store.mencoes_de("a.md") == []


def test_documento_sem_identificador_nao_gera_mencao(store: Store) -> None:
    semear(store, {"a.md": "uma ata de reunião sobre o cronograma da obra"})
    resumo = construir(store)
    assert resumo["com_mencao"] == 0


# --- a caminhada --------------------------------------------------------------


def test_vizinho_ligado_por_norma_em_comum(store: Store) -> None:
    """O caso que motiva a fase: pastas diferentes, nomes diferentes, nenhum
    vocabulário em comum — só a norma citada pelos dois."""
    semear(
        store,
        {
            "Politicas/plano_de_acao.md": "meta: obter certificação ISO 42001",
            "Normas/gestao_de_ia.md": "a ISO 42001 define o sistema de gestão",
            "Orcamentos/planilha.md": "custos de obra sem identificador nenhum",
        },
    )
    construir(store)

    achados = vizinhos(store, "Politicas/plano_de_acao.md")

    assert [v.path for v in achados] == ["Normas/gestao_de_ia.md"]
    assert achados[0].ligacoes[0].valor == "ISO 42001"
    assert achados[0].ligacoes[0].tipo == "norma"


def test_o_motivo_vem_com_o_trecho_para_o_cliente_conferir(store: Store) -> None:
    """Sem o `chunk_id`, `neighbors` seria um oráculo: o cliente receberia
    "documento relacionado" e teria que confiar."""
    semear(
        store,
        {
            "a.md": "prevê a ISO 42001",
            "b.md": "a ISO 42001 exige",
        },
    )
    construir(store)

    ligacao = vizinhos(store, "a.md")[0].ligacoes[0]
    assert ligacao.chunk_id
    assert store.chunk(ligacao.chunk_id) is not None


def test_documento_sem_identificador_nao_tem_vizinho(store: Store) -> None:
    """Devolver vazio é o caso honesto, não um erro.

    Um acervo em que `neighbors` sempre devolve algo é um acervo com o teto mal
    calibrado.
    """
    semear(store, {"a.md": "ata sem identificador", "b.md": "outra ata"})
    construir(store)
    assert vizinhos(store, "a.md") == []


def test_identificador_citado_por_um_so_documento_nao_liga(store: Store) -> None:
    semear(store, {"a.md": "só aqui a ISO 42001 aparece", "b.md": "nada em comum"})
    construir(store)
    assert vizinhos(store, "a.md") == []


# --- o que faz a ferramenta valer: raridade ----------------------------------


def test_identificador_onipresente_nao_vira_aresta(store: Store) -> None:
    """O caso que fixa o teto: o CNPJ da própria empresa está em todo contrato.

    Sem o teto, `neighbors` de qualquer contrato devolveria todos os outros — uma
    aresta que liga tudo a tudo carrega zero informação e ocupa o lugar das que
    carregam.
    """
    onipresente = "inscrita no CNPJ 12.345.678/0001-90"
    documentos = {f"Contratos/c{i}.md": onipresente for i in range(MAX_DOCUMENTOS_POR_ID + 3)}
    semear(store, documentos)
    construir(store)

    assert vizinhos(store, "Contratos/c0.md") == []


def test_teto_configuravel_para_acervo_pequeno(store: Store) -> None:
    """Num acervo de 3 documentos, o teto padrão é o acervo inteiro."""
    semear(store, {f"c{i}.md": "CNPJ 12.345.678/0001-90" for i in range(3)})
    construir(store)

    assert vizinhos(store, "c0.md", max_documentos_por_id=2) == []
    assert len(vizinhos(store, "c0.md", max_documentos_por_id=5)) == 2


def test_identificador_raro_pesa_mais_que_o_comum(store: Store) -> None:
    """Entre os que passam o teto, a ordem é por raridade.

    O vizinho que compartilha um identificador citado só pelos dois vem antes do
    que compartilha um citado por dez — mesmo número de arestas, informação
    muito diferente.
    """
    comum = "conforme a ISO 9001"
    documentos = {f"Comuns/c{i}.md": comum for i in range(8)}
    documentos["alvo.md"] = "conforme a ISO 9001 e o CT-VCE-2024-0142"
    documentos["raro.md"] = "o contrato CT-VCE-2024-0142 detalha"
    semear(store, documentos)
    construir(store)

    achados = vizinhos(store, "alvo.md")

    assert achados[0].path == "raro.md"
    assert achados[0].peso > achados[1].peso


def test_dois_identificadores_em_comum_pesam_mais_que_um(store: Store) -> None:
    """Evidência independente acumula — a mesma lógica da fusão de ranqueadores."""
    semear(
        store,
        {
            "alvo.md": "a ISO 42001 e o CT-VCE-2024-0142",
            "dois.md": "cita a ISO 42001 e também o CT-VCE-2024-0142",
            "um.md": "cita apenas a ISO 42001",
        },
    )
    construir(store)

    achados = vizinhos(store, "alvo.md")
    assert achados[0].path == "dois.md"
    assert len(achados[0].ligacoes) == 2
    assert achados[0].peso > achados[1].peso


def test_limite_de_vizinhos_e_respeitado(store: Store) -> None:
    """Cada vizinho custa contexto do cliente."""
    semear(store, {f"c{i}.md": "o contrato CT-VCE-2024-0142" for i in range(12)})
    construir(store)

    assert len(vizinhos(store, "c0.md", limite=3, max_documentos_por_id=20)) == 3


def test_lei_e_norma_com_mesmo_numero_nao_ligam(store: Store) -> None:
    """O tipo separa espaços de nomeação — aqui, no grafo, não só na extração."""
    semear(
        store,
        {
            "lei.md": "nos termos da Lei 42.001/2020",
            "norma.md": "conforme a ISO 42001",
        },
    )
    construir(store)
    assert vizinhos(store, "lei.md") == []


# --- estado do grafo em relação ao índice ------------------------------------


def test_desatualizado_reporta_o_atraso(store: Store) -> None:
    """A passada é separada do indexador, então o grafo pode ficar velho — e uma
    métrica medida com grafo velho mediria a coisa errada sem avisar."""
    semear(store, {"a.md": "a ISO 42001", "b.md": "a ISO 42001"})
    assert desatualizado(store) == {"documentos_no_indice": 2, "documentos_no_grafo": 0}

    construir(store)
    assert desatualizado(store) == {"documentos_no_indice": 2, "documentos_no_grafo": 2}


def test_estatisticas_separam_por_tipo(store: Store) -> None:
    semear(store, {"a.md": "a ISO 42001, a Lei 14.133/2021 e o CT-VCE-2024-0142"})
    construir(store)

    estado = store.estatisticas_do_grafo()
    assert estado["por_tipo"] == {"codigo": 1, "lei": 1, "norma": 1}
    assert estado["identificadores"] == 3


# --- o nome do arquivo como fonte, e o desempate que ele dá -------------------
# Medido no acervo real em 20/08/2026, e as duas coisas nasceram do mesmo caso: a
# norma que a `g048` precisa é um PDF digitalizado de 61 páginas, `status: vazio`,
# sem uma linha de texto extraível.


def test_documento_sem_texto_ainda_entra_no_grafo(store: Store) -> None:
    """PDF digitalizado tem o identificador só no nome — e é o único sinal dele.

    Varrer apenas documentos com chunk deixaria de fora exatamente o documento
    que motivou a fase.
    """
    from tests.falsos import EmbedderFalso, chunk

    # Registrado, mas sem chunk nenhum: é o que o indexador grava para um PDF
    # digitalizado (`status: vazio`).
    store.registrar_documento(
        path="Normas/ISO-420012023_-Web.pdf", raiz="r", tamanho=1, mtime=0.0, status="vazio"
    )
    emb = EmbedderFalso()
    citante = [chunk("p1", "Planos/plano.md", 0, "meta: certificação ISO 42001")]
    store.gravar_chunks(citante, emb.embed_passagens([c.text for c in citante]), mtime=1.0)
    store.con.commit()

    construir(store)

    assert [(t, v) for t, v, _ in store.mencoes_de("Normas/ISO-420012023_-Web.pdf")] == [
        ("norma", "ISO 42001")
    ]
    assert [v.path for v in vizinhos(store, "Planos/plano.md")] == [
        "Normas/ISO-420012023_-Web.pdf"
    ]


def test_menção_no_nome_nao_traz_chunk_para_ler(store: Store) -> None:
    """Sem corpo não há trecho, e o campo fica vazio em vez de apontar para nada.

    A procedência, aqui, é o próprio nome do arquivo.
    """
    from tests.falsos import EmbedderFalso, chunk

    store.registrar_documento(
        path="Normas/ISO-42001.pdf", raiz="r", tamanho=1, mtime=0.0, status="vazio"
    )
    emb = EmbedderFalso()
    cs = [chunk("p1", "plano.md", 0, "prevê a ISO 42001")]
    store.gravar_chunks(cs, emb.embed_passagens([c.text for c in cs]), mtime=1.0)
    store.con.commit()
    construir(store)

    ligacao = vizinhos(store, "plano.md")[0].ligacoes[0]
    assert ligacao.no_nome
    assert ligacao.chunk_id == ""


def test_documento_canonico_vem_antes_de_quem_so_cita(store: Store) -> None:
    """O desempate que consertou o resultado no acervo real.

    27 documentos citavam a `ISO 42001` e **todos empatavam no mesmo peso**, então
    o topo saía por ordem alfabética: exercícios de curso que mencionam a norma de
    passagem vinham antes do próprio texto da norma, que era o documento
    procurado. Nome e corpo não são o mesmo tipo de evidência.
    """
    semear(
        store,
        {
            "aaa_exercicio.md": "o exercício cita a ISO 42001 de passagem",
            "Normas/ISO-42001 norma.md": "texto da norma",
            "zzz_outro.md": "também menciona ISO 42001",
            "plano.md": "meta: certificação ISO 42001",
        },
    )
    construir(store)

    achados = vizinhos(store, "plano.md")

    assert achados[0].path == "Normas/ISO-42001 norma.md"
    assert achados[0].canonico
    # Empatam no peso — é só a categoria que os separa.
    assert achados[0].peso == achados[1].peso


def test_identificador_raro_ganha_do_canonico_comum(store: Store) -> None:
    """Canônico vem antes **no empate**, não sempre.

    Um identificador citado só por dois documentos é evidência mais forte que ser
    o documento canônico de uma norma que meio acervo cita. A ordem dos critérios
    poderia inverter isso sem que nenhum teste percebesse.
    """
    documentos = {f"c{i}.md": "conforme a ISO 9001" for i in range(9)}
    documentos["Normas/ISO-9001 norma.md"] = "texto da norma de qualidade"
    documentos["alvo.md"] = "cita ISO 9001 e o CT-VCE-2024-0142"
    documentos["raro.md"] = "só aqui o CT-VCE-2024-0142 aparece de novo"
    semear(store, documentos)
    construir(store)

    achados = vizinhos(store, "alvo.md")
    assert achados[0].path == "raro.md"
    assert not achados[0].canonico
