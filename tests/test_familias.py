"""Famílias de versão — o mecanismo da F2 contra o caso `g010`.

Os nomes daqui são inspirados no acervo real, com identificadores trocados por
fictícios: refletem os padrões de nomenclatura (sufixo de versão, iniciais de
quem revisou, código de documento interno) que o censo de 11/08/2026 listou
como dominantes.
"""

from __future__ import annotations

import pytest

from segundocerebro.retrieve.familias import chave_de_familia, colapsar, familias_de, versao_de

PASTA = "01. Inteligência Artificial/Política de IA"


def test_versao_no_nome_nao_muda_a_familia() -> None:
    a = chave_de_familia(f"{PASTA}/Política Acme Holding de Inteligência Artificial_v6.docx")
    b = chave_de_familia(f"{PASTA}/Política Acme Holding de Inteligência Artificial_v8.docx")
    assert a == b


def test_marcadores_empilhados() -> None:
    """`_v6_Comentado` tem dois marcadores, e um só passe não tira os dois."""
    a = chave_de_familia(f"{PASTA}/Política Acme Holding de Inteligência Artificial_v6.docx")
    b = chave_de_familia(f"{PASTA}/Política Acme Holding de Inteligência Artificial_v6_Comentado.docx")
    assert a == b


def test_iniciais_de_quem_revisou() -> None:
    """O caso `g010`: `_revisadaTI` e `_revisadaTI_GC` são o mesmo documento."""
    a = chave_de_familia(f"{PASTA}/PL-ACME-XXX_Política de Inteligência Artificial_revisadaTI.docx")
    b = chave_de_familia(f"{PASTA}/PL-ACME-XXX_Política de Inteligência Artificial_revisadaTI_GC.docx")
    assert a == b


@pytest.mark.parametrize(
    "outro",
    [
        "Relatório (1).pdf",
        "Cópia de Relatório.pdf",
        "Relatório_bkp3.pdf",
        "Relatório_final.pdf",
        "Relatório - Copy.pdf",
    ],
)
def test_padroes_de_copia_do_acervo(outro: str) -> None:
    assert chave_de_familia(f"{PASTA}/Relatório.pdf") == chave_de_familia(f"{PASTA}/{outro}")


def test_familia_nao_atravessa_pasta() -> None:
    """Modelo e preenchido costumam ter o mesmo nome em pastas diferentes."""
    a = chave_de_familia("Modelos/Proposta_v1.docx")
    b = chave_de_familia("Clientes/ACME/Proposta_v1.docx")
    assert a != b


def test_documentos_diferentes_nao_se_fundem() -> None:
    """Agrupar demais perde documento — é a falha mais cara deste mecanismo."""
    chaves = {
        chave_de_familia(f"{PASTA}/{n}")
        for n in (
            "PL-ACME-007_Política_IA_v0.docx",
            "PO-ACME-007_Política_IA_v7.docx",
            "PR-ACME-003_Classificação_Risco_IA.docx",
            "PR-ACME-004_Aprovação_GoNoGo_IA.docx",
            "MA-ACME-001_Manifesto_IA.docx",
        )
    }
    assert len(chaves) == 5


def test_nome_que_e_so_marcador_nao_vira_chave_vazia() -> None:
    assert chave_de_familia("pasta/v2.docx").endswith("v2.docx")


# --- o colapso ----------------------------------------------------------------


def test_familia_fica_com_a_melhor_posicao_e_devolve_o_vigente() -> None:
    """O coração do `g010`, com os nomes reais dos gêmeos.

    `_revisadaTI` ranqueia melhor e é o antigo; `_revisadaTI_GC` é o vigente, de
    11/08/2026. A família herda a posição do irmão bem colocado e entrega o mais
    recente — que é a resposta que o conjunto dourado espera.
    """
    antigo = f"{PASTA}/PL-CORP-XXX_Política de Inteligência Artificial_revisadaTI.docx"
    novo = f"{PASTA}/PL-CORP-XXX_Política de Inteligência Artificial_revisadaTI_GC.docx"
    ranking = [antigo, "outro/Assunto.pdf", novo]
    mtimes = {antigo: 1_700_000_000.0, novo: 1_800_000_000.0, "outro/Assunto.pdf": 0.0}

    colapsado, familias = colapsar(ranking, mtimes)

    assert colapsado == [novo, "outro/Assunto.pdf"]
    assert familias[novo].anteriores == (antigo,)
    assert familias[novo].posicao == 0


def test_colapso_libera_posicoes() -> None:
    """Seis parentes ocupavam seis posições; passam a ocupar uma."""
    membros = [f"{PASTA}/Política_v{i}.docx" for i in range(1, 7)]
    ranking = membros + ["outro/A.pdf", "outro/B.pdf"]
    mtimes = {p: float(i) for i, p in enumerate(ranking)}

    colapsado, _ = colapsar(ranking, mtimes)

    assert len(colapsado) == 3
    assert colapsado[1:] == ["outro/A.pdf", "outro/B.pdf"]


def test_sem_irmaos_o_ranking_passa_intacto() -> None:
    ranking = ["a/Um.pdf", "b/Dois.pdf", "c/Tres.pdf"]
    colapsado, _ = colapsar(ranking, {p: 0.0 for p in ranking})
    assert colapsado == ranking


def test_representante_sai_de_quem_foi_recuperado() -> None:
    """Promover documento não pontuado seria inventar relevância a partir de data."""
    recuperado = f"{PASTA}/Política_v1.docx"
    colapsado, _ = colapsar([recuperado], {recuperado: 1.0, f"{PASTA}/Política_v9.docx": 9.0})
    assert colapsado == [recuperado]


def test_empate_de_data_e_deterministico() -> None:
    a, b = f"{PASTA}/Doc_v1.docx", f"{PASTA}/Doc_v2.docx"
    mesmos = {a: 5.0, b: 5.0}
    assert colapsar([a, b], mesmos)[0] == colapsar([b, a], mesmos)[0]


def test_formatos_diferentes_nao_sao_a_mesma_familia() -> None:
    """`g045`, medido: o mesmo deck exportado em PDF e PPTX, mesma data.

    Fundir os dois fazia o desempate escolher um formato ao acaso, e a pergunta
    caía do 1º lugar para fora do ranking. Quem pede o deck quer o deck.
    """
    a = chave_de_familia(f"{PASTA}/Apresentação IA RDE Dec-2025.pptx")
    b = chave_de_familia(f"{PASTA}/Apresentação IA RDE Dec-2025.pdf")
    assert a != b


def test_numero_declarado_vence_a_data() -> None:
    """`g045`, medido: `_v0` é de janeiro/2026 e `_v1` de setembro/2025.

    Um arquivo copiado ganha `mtime` novo sem virar versão nova. Onde os dois
    sinais discordam e há número declarado, o número decide.
    """
    v0 = f"{PASTA}/caderno_v0.xlsx"
    v1 = f"{PASTA}/caderno_v1.xlsx"
    mtimes = {v0: 1_768_000_000.0, v1: 1_757_000_000.0}  # v0 mais recente

    colapsado, familias = colapsar([v0, v1], mtimes)

    assert colapsado == [v1], "o número declarado manda"
    assert familias[v1].anteriores == (v0,)


def test_sem_numero_declarado_a_data_decide() -> None:
    """`g010`: nenhum dos gêmeos declara versão, então vale a data."""
    antigo = f"{PASTA}/Política_revisadaTI.docx"
    novo = f"{PASTA}/Política_revisadaTI_GC.docx"
    colapsado, _ = colapsar([antigo, novo], {antigo: 1_700_000_000.0, novo: 1_800_000_000.0})
    assert colapsado == [novo]


def test_versao_de() -> None:
    assert versao_de("a/Doc_v12.3.docx") == (12, 3)
    assert versao_de("a/Doc_v7.docx") == (7,)
    assert versao_de("a/Doc.docx") is None


def test_agrupamento_para_inspecao() -> None:
    familias = familias_de([f"{PASTA}/Doc_v1.docx", f"{PASTA}/Doc_v2.docx", f"{PASTA}/Outro.docx"])
    assert len(familias) == 2
    assert sorted(len(v) for v in familias.values()) == [1, 2]
