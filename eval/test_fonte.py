"""O recorte por tipo de fonte — `C3.a`/`F4-P`."""

from __future__ import annotations

import pytest

from .fonte import EMAIL, ESCRITORIO, GRUPOS, MISTO, REUNIAO, grupo_de_fonte, grupo_de_pergunta


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("Projetos/Contrato VCE 2026.pdf", ESCRITORIO),
        ("Politicas/politica-de-ia_v6.docx", ESCRITORIO),
        ("Financeiro/orcamento.xlsx", ESCRITORIO),
        # Pasta de reunião, nos dois idiomas e com sufixo
        ("Meetings/2026-03-11 POC weekly.docx", REUNIAO),
        ("Meetings 2026/kickoff.docx", REUNIAO),
        ("Reuniões/ata da diária.docx", REUNIAO),
        ("Reunião de kickoff/nota.docx", REUNIAO),
        ("Atas/2026-01 comite.docx", REUNIAO),
        ("Projetos/VCE/Transcrições/daily.docx", REUNIAO),
        # Prefixo de ordenação: 14 dos 36 segmentos do dourado real têm um
        ("09. Meetings/2026-03-11 daily.txt", REUNIAO),
        ("Projetos/09. Meetings/daily.txt", REUNIAO),
        ("10 - Reuniões/ata.docx", REUNIAO),
        ("260722_Meetings/nota.docx", REUNIAO),
        # Formato de legenda é transcrição onde estiver
        ("Projetos/VCE/gravacao.vtt", REUNIAO),
        # Email é formato, não pasta
        ("Caixa de entrada/reembolso.msg", EMAIL),
        ("Projetos/VCE/aprovacao.eml", EMAIL),
    ],
)
def test_grupo_por_caminho(caminho: str, esperado: str) -> None:
    assert grupo_de_fonte(caminho) == esperado


def test_msg_dentro_de_pasta_de_reuniao_e_email() -> None:
    """Formato ganha de pasta, e isso é o achado da `F4` e não uma escolha de estilo.

    O `.msg` que tirou a `g045` do primeiro lugar era o convite da reunião diária
    (`docs/ablacao-f4-email.md`) — não a transcrição dela. Classificá-lo como
    reunião apagaria justamente a distinção que a regressão ensinou.
    """
    assert grupo_de_fonte("Meetings/POC diaria 2026-03-11.msg") == EMAIL


def test_prefixo_no_meio_de_palavra_nao_conta() -> None:
    """`meeting` tem de estar começando um segmento, não dentro de uma palavra."""
    assert grupo_de_fonte("Projetos/Remeeting-notes.pdf") == ESCRITORIO
    assert grupo_de_fonte("Projetos/premeetings/nota.pdf") == ESCRITORIO


@pytest.mark.parametrize(
    "caminho",
    [
        "Atacado/tabela de precos.xlsx",
        "Atalhos/link.pdf",
        "Ataque e defesa/relatorio.pdf",
        "Callback/registro.docx",
    ],
)
def test_ata_e_call_pedem_palavra_inteira(caminho: str) -> None:
    """Como prefixo, `ata` e `call` varreriam meio acervo para dentro de reunião."""
    assert grupo_de_fonte(caminho) == ESCRITORIO


def test_reuniao_com_til_conta():
    """A grafia que a primeira versão do padrão errava: depois de `reuni` vem `ã`."""
    assert grupo_de_fonte("Reunião/ata.docx") == REUNIAO
    assert grupo_de_fonte("01. Reuniao de diretoria/nota.docx") == REUNIAO


def test_separador_do_windows_e_o_mesmo_caminho() -> None:
    assert grupo_de_fonte(r"Meetings\2026\daily.docx") == REUNIAO


def test_arquivo_sem_extensao_nao_confunde_ponto_de_pasta() -> None:
    """`Projetos/v1.2/LEIAME` não tem extensão `.2/LEIAME`."""
    assert grupo_de_fonte("Projetos/v1.2/LEIAME") == ESCRITORIO


def test_pergunta_de_um_grupo_so() -> None:
    assert grupo_de_pergunta(["Meetings/a.docx", "Meetings/b.docx"]) == REUNIAO


def test_pergunta_multihop_entre_grupos_e_mista() -> None:
    """Ela mede a ponte, e somá-la a um dos lados contaminaria os dois."""
    assert grupo_de_pergunta(["Meetings/daily.docx", "Politicas/politica.docx"]) == MISTO


def test_pergunta_sem_fonte_e_mista() -> None:
    assert grupo_de_pergunta([]) == MISTO


def test_grupos_cobrem_o_vocabulario_todo() -> None:
    """Grupo fora de `GRUPOS` sumiria da tabela do relatório sem avisar."""
    caminhos = [
        "Projetos/x.pdf",
        "Meetings/y.docx",
        "Caixa/z.msg",
        "Projetos/v.vtt",
    ]
    assert {grupo_de_fonte(c) for c in caminhos} <= set(GRUPOS)
    assert grupo_de_pergunta(caminhos) in GRUPOS
