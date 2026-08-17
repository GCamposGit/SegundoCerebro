"""Tests for chunking.

The property that matters most is determinism: same document in, same ids out.
Without it the eval cannot compare a number measured before a change with one
measured after, and the whole method of the project stops working.
"""

from __future__ import annotations

import pytest

from segundocerebro.ingest.chunking import (
    CHUNKER_VERSION,
    Chunk,
    ChunkConfig,
    chunk_document,
    chunk_id,
    estatisticas,
)
from segundocerebro.ingest.document import Block, BlockKind, ParsedDoc


def doc(*blocos: Block) -> ParsedDoc:
    return ParsedDoc(name="x.docx", blocks=blocos)


def bloco(texto: str, *titulos: str, kind: BlockKind = BlockKind.TEXT, locator: str = "") -> Block:
    return Block(heading_path=titulos, text=texto, kind=kind, locator=locator)


# --- regra 1: bloco que cabe é o chunk ---------------------------------------


def test_bloco_que_cabe_nao_e_cortado() -> None:
    chunks = chunk_document(doc(bloco("texto curto", "Título")), "a.docx")

    assert len(chunks) == 1
    assert chunks[0].text == "texto curto"
    assert chunks[0].heading_path == ("Título",)


def test_texto_do_embedding_leva_nome_e_trilha() -> None:
    chunks = chunk_document(doc(bloco("corpo", "Plano", "Riscos")), "Plano de Ação.docx")

    assert chunks[0].embedding_text == "Plano de Ação > Plano > Riscos\n---\ncorpo"


def test_sem_trilha_o_texto_do_embedding_ainda_leva_o_nome() -> None:
    chunks = chunk_document(doc(bloco("corpo solto")), "Alternativas de Equipe.docx")

    assert chunks[0].embedding_text == "Alternativas de Equipe\n---\ncorpo solto"


# --- regra 2: bloco grande é cortado com sobreposição ------------------------


def test_bloco_grande_e_cortado_repetindo_a_trilha() -> None:
    cfg = ChunkConfig(max_chars=200, overlap_chars=40, min_chars=0)
    paragrafos = "\n\n".join(f"Parágrafo {i} com texto suficiente para ocupar espaço." for i in range(12))
    chunks = chunk_document(doc(bloco(paragrafos, "Seção A")), "a.pdf", cfg)

    assert len(chunks) > 1
    assert all(c.heading_path == ("Seção A",) for c in chunks)
    assert all(c.chars <= cfg.max_chars + cfg.overlap_chars for c in chunks)
    assert all("/" in c.locator for c in chunks)  # parte i/n


def test_corte_prefere_fronteira_de_paragrafo() -> None:
    cfg = ChunkConfig(max_chars=120, overlap_chars=0, min_chars=0)
    primeiro = "Primeiro parágrafo com bastante texto para ocupar a maior parte do limite."
    segundo = "Segundo parágrafo com outro tanto de texto para forçar o corte no lugar certo."
    chunks = chunk_document(doc(bloco(f"{primeiro}\n\n{segundo}")), "a.md", cfg)

    assert len(chunks) == 2
    assert chunks[0].text == primeiro
    assert chunks[1].text == segundo


def test_sobreposicao_repete_o_fim_do_pedaco_anterior() -> None:
    cfg = ChunkConfig(max_chars=150, overlap_chars=50, min_chars=0)
    texto = " ".join(f"palavra{i}" for i in range(80))
    chunks = chunk_document(doc(bloco(texto)), "a.md", cfg)

    assert len(chunks) > 1
    fim_do_primeiro = chunks[0].text[-20:]
    assert any(fim_do_primeiro.split()[-1] in c.text for c in chunks[1:])


def test_bloco_sem_fronteira_nenhuma_ainda_e_cortado() -> None:
    """Texto sem espaço nem pontuação não pode travar o cortador."""
    cfg = ChunkConfig(max_chars=100, overlap_chars=10, min_chars=0)
    chunks = chunk_document(doc(bloco("x" * 500)), "a.txt", cfg)

    assert len(chunks) >= 5
    assert all(c.chars <= 110 for c in chunks)


# --- regra 3: blocos pequenos são juntados ----------------------------------


def test_blocos_pequenos_sob_a_mesma_trilha_sao_juntados() -> None:
    cfg = ChunkConfig(max_chars=2500, min_chars=250)
    chunks = chunk_document(doc(bloco("linha um", "T"), bloco("linha dois", "T"), bloco("linha três", "T")), "a.docx", cfg)

    assert len(chunks) == 1
    assert chunks[0].text == "linha um\nlinha dois\nlinha três"


def test_blocos_pequenos_de_trilhas_diferentes_nao_se_misturam() -> None:
    cfg = ChunkConfig(max_chars=2500, min_chars=250)
    chunks = chunk_document(doc(bloco("a", "T1"), bloco("b", "T2")), "a.docx", cfg)

    assert len(chunks) == 2
    assert [c.heading_path for c in chunks] == [("T1",), ("T2",)]


def test_juncao_registra_a_faixa_de_localizadores() -> None:
    cfg = ChunkConfig(max_chars=2500, min_chars=250)
    chunks = chunk_document(
        doc(bloco("a", "T", locator="p. 1"), bloco("b", "T", locator="p. 2")), "a.pdf", cfg
    )

    assert chunks[0].locator == "p. 1–p. 2"


# --- nunca cortar planilha nem tabela ---------------------------------------


@pytest.mark.parametrize("kind", [BlockKind.SHEET, BlockKind.TABLE])
def test_planilha_e_tabela_nao_sao_cortadas(kind: BlockKind) -> None:
    """Cortar uma tabela pela metade desalinha coluna e valor."""
    cfg = ChunkConfig(max_chars=100, min_chars=0)
    texto = "col1 | col2\n" + "\n".join(f"valor{i} | {i}" for i in range(60))
    chunks = chunk_document(doc(bloco(texto, "Aba", kind=kind)), "a.xlsx", cfg)

    assert len(chunks) == 1
    assert chunks[0].chars > cfg.max_chars


# --- determinismo e identidade ----------------------------------------------


def test_ids_sao_estaveis_entre_execucoes() -> None:
    entrada = doc(bloco("um", "T"), bloco("dois" * 200, "T", "S"))

    primeira = chunk_document(entrada, "a.docx")
    segunda = chunk_document(entrada, "a.docx")

    assert [c.id for c in primeira] == [c.id for c in segunda]


def test_ids_diferem_entre_documentos() -> None:
    a = chunk_document(doc(bloco("mesmo texto", "T")), "a.docx")
    b = chunk_document(doc(bloco("mesmo texto", "T")), "b.docx")

    assert a[0].id != b[0].id


def test_id_depende_da_versao_do_chunker() -> None:
    """Mudar a regra muda o id de propósito: é outro chunk."""
    atual = chunk_id("a.docx", ("T",), "", 0)
    assert atual == chunk_id("a.docx", ("T",), "", 0)
    assert CHUNKER_VERSION == "2"  # lembrete de atualizar quando a regra mudar


def test_ordinal_segue_a_ordem_do_documento() -> None:
    chunks = chunk_document(doc(bloco("a" * 300, "T1"), bloco("b" * 300, "T2")), "a.docx")

    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_blocos_vazios_sao_descartados() -> None:
    chunks = chunk_document(doc(bloco("   ", "T"), bloco("real", "T")), "a.docx")

    assert len(chunks) == 1
    assert chunks[0].text == "real"


def test_documento_sem_blocos() -> None:
    assert chunk_document(ParsedDoc(name="vazio.pdf"), "vazio.pdf") == []


def test_estatisticas() -> None:
    chunks = [
        Chunk(id="1", doc_path="a", ordinal=0, heading_path=(), text="abc"),
        Chunk(id="2", doc_path="a", ordinal=1, heading_path=(), text="de"),
    ]
    e = estatisticas(chunks)

    assert e["chunks"] == 2
    assert e["chars"] == 5
    assert e["maior"] == 3
    assert e["menor"] == 2
    assert estatisticas([])["chunks"] == 0


def test_nome_do_documento_entra_no_texto_do_embedding() -> None:
    """v2 do chunker: sem o nome do arquivo o denso perde o sinal mais forte."""
    chunks = chunk_document(doc(bloco("prazo de doze meses", "Vigência")), "Contratos/Contrato NN-ACME-450.2025.docx")

    texto = chunks[0].embedding_text
    assert texto.startswith("Contrato NN-ACME-450.2025 > Vigência\n---\n")
    assert chunks[0].text == "prazo de doze meses", "o texto guardado não muda, só o embeddado"


def test_nome_do_documento_troca_underscore_por_espaco() -> None:
    chunks = chunk_document(doc(bloco("corpo")), "x/PO-ACME-007_Política_IA_v8.docx")

    assert chunks[0].nome_documento == "PO-ACME-007 Política IA v8"


# --- orçamento por tokens ----------------------------------------------------


def contar_falso(texto: str) -> int:
    """Aproximação estável para teste: 4 caracteres por token."""
    return len(texto) // 4


def test_orcamento_de_tokens_corta_o_que_a_regra_de_caracteres_deixou_passar() -> None:
    """1800 caracteres podem passar de 512 tokens — e passar em silêncio."""
    cfg = ChunkConfig(max_chars=1800, max_tokens=100, contar_tokens=contar_falso, min_chars=0)
    texto = " ".join(f"palavra{i}" for i in range(150))  # ~1400 chars, ~350 tokens

    chunks = chunk_document(doc(bloco(texto, "Seção")), "doc.md", cfg)

    assert len(chunks) > 1
    for c in chunks:
        assert contar_falso(c.embedding_text) <= 100, "chunk acima da janela do encoder"


def test_tabela_grande_e_cortada_por_linha_repetindo_o_cabecalho() -> None:
    """Antes: tabela nunca era cortada e ia truncada para o encoder em silêncio."""
    cfg = ChunkConfig(max_chars=100000, max_tokens=60, contar_tokens=contar_falso, min_chars=0)
    texto = "Usuário | Área | Licença\n" + "\n".join(f"pessoa{i} | Inovação | Copilot" for i in range(40))

    chunks = chunk_document(doc(bloco(texto, "Licenças", kind=BlockKind.SHEET)), "planilha.xlsx", cfg)

    assert len(chunks) > 1
    for c in chunks:
        assert c.text.startswith("Usuário | Área | Licença"), "cabeçalho tem que ir em cada pedaço"
        assert contar_falso(c.embedding_text) <= 60


def test_sem_contador_a_regra_de_caracteres_continua_valendo() -> None:
    """Teste unitário não deve carregar tokenizador: caminho rápido preservado."""
    cfg = ChunkConfig(max_chars=200, min_chars=0)
    chunks = chunk_document(doc(bloco("x" * 500)), "a.md", cfg)

    assert len(chunks) >= 3


def test_linha_que_nao_cabe_nem_sozinha_e_cortada_em_vez_de_estourar() -> None:
    """O defeito medido em 13/08/2026: 365 chunks acima do orçamento numa planilha.

    Quando o cabeçalho **mais uma linha** já passa da janela, não existe
    agrupamento possível. A versão anterior emitia o pedaço assim mesmo — o maior
    tinha 4.386 tokens para um limite de 488, e o encoder truncava em silêncio o
    que sobrava. Agora cai para corte por caractere, que sempre cabe.
    """
    cfg = ChunkConfig(max_chars=100000, max_tokens=60, contar_tokens=contar_falso, min_chars=0)
    cabecalho = "Processo | Tribunal | Relator"
    gigante = " | ".join(f"valor-muito-longo-{i}" for i in range(40))  # ~800 chars, ~200 tokens
    texto = f"{cabecalho}\n{gigante}\nprocesso1 | TJSP | Alguem"

    chunks = chunk_document(doc(bloco(texto, "Aba", kind=BlockKind.SHEET)), "planilha.xlsx", cfg)

    assert chunks, "linha gigante não pode fazer o bloco desaparecer"
    for c in chunks:
        assert contar_falso(c.embedding_text) <= 60, (
            f"chunk com {contar_falso(c.embedding_text)} tokens acima do orçamento de 60"
        )


def test_orcamento_respeitado_com_prefixo_contextual_longo() -> None:
    """O prefixo entra na conta: nome de arquivo comprido come a janela.

    O acervo tem caminhos de 293 caracteres, e a trilha de headings soma em cima.
    Se o orçamento fosse conferido só no texto, o chunk caberia no teste e
    estouraria na indexação.
    """
    cfg = ChunkConfig(max_chars=100000, max_tokens=80, contar_tokens=contar_falso, min_chars=0)
    nome_longo = "Relatorio " * 20 + ".xlsx"
    texto = "A | B\n" + "\n".join(f"linha{i} | valor{i}" for i in range(60))

    chunks = chunk_document(doc(bloco(texto, "Aba", kind=BlockKind.SHEET)), nome_longo, cfg)

    for c in chunks:
        assert contar_falso(c.embedding_text) <= 80
