"""O contrato entre quem classifica o documento e quem consegue lê-lo.

`retrieve/fonte.py` nomeia extensões para decidir o **grupo de fonte** do
documento candidato, e `F4-P.1` usa esse grupo para escolher quanto o ranqueador
de nome vale. Só que grupo de um formato que o indexador não parseia é regra
sobre documento que **nunca existe**: o mecanismo fica inerte, e nada falha.

Foi o que aconteceu com `EXTENSOES_DE_TRANSCRICAO`. Medido no índice sintético do
`E1` em 27/08/2026: 200 documentos de reunião registrados, **3** com chunk, e as
**100** perguntas da fatia `reunião` apontando para `.vtt` — nenhuma alcançável.
A medição declarada da `F4-P.1` teria dado empate nos dois braços e o critério de
encerramento fecharia o pacote com "hipótese refutada", por falta de parser.

É a mesma classe do `F4-P.0` ("o eval mede um caminho e o cliente executa
outro"), um nível acima: **a régua nomeia um formato que o produto não ingere.**
O que passa a pegá-la sozinha é este arquivo — toda extensão citada em
`retrieve/fonte.py` tem de estar em `supported_extensions()`, ou estar declarada
aqui como lacuna conhecida, com o pacote que a fecha.

**A lacuna que motivou o arquivo foi fechada no mesmo dia** pelo `F4-T`
(`ingest/parsers/vtt.py`), e foi o quarto teste daqui que obrigou a limpar a
tabela: sem ele a dívida sobreviveria ao conserto e a fatia continuaria sendo
tratada como vazia depois de passar a medir.
"""

from __future__ import annotations

import pytest

from segundocerebro.ingest.parsers import supported_extensions
from segundocerebro.retrieve.fonte import (
    EXTENSOES_DE_EMAIL,
    EXTENSOES_DE_TRANSCRICAO,
    REUNIAO,
    grupo_de_fonte,
)

LACUNAS_DECLARADAS: dict[str, str] = {}
"""Vazia desde 27/08/2026, e o mecanismo fica.

Ela nasceu com `.vtt`/`.srt`/`.sbv` e **esvaziou no mesmo dia**: o `F4-T` entregou
`ingest/parsers/vtt.py` e o teste abaixo obrigou a limpar a entrada em vez de
deixá-la sobreviver ao próprio conserto. Fica no lugar porque a próxima extensão
que `retrieve/fonte.py` aprender a classificar antes de haver parser cai aqui, com
o pacote que a fecha, em vez de produzir fatia vazia em silêncio."""

_REGRA = """Entrada em LACUNAS_DECLARADAS é dívida declarada, não permissão:
enquanto a extensão estiver lá, nenhuma decisão de ranking pode ser tomada sobre o
grupo dela — a fatia é vazia por construção e qualquer Δ sai zero."""


def test_email_e_lido_pelo_indexador() -> None:
    """`.msg`/`.eml` fecham o contrato — é por isso que a fatia email mede 102."""
    faltando = sorted(EXTENSOES_DE_EMAIL - set(supported_extensions()))
    assert not faltando, f"fonte.py classifica {faltando} como email e o indexador não lê"


def test_toda_extensao_classificada_esta_lida_ou_declarada_como_lacuna() -> None:
    """A porta que faltava: classificar sem ler é regra sobre documento inexistente."""
    citadas = EXTENSOES_DE_EMAIL | EXTENSOES_DE_TRANSCRICAO
    lidas = set(supported_extensions())
    surpresas = sorted(citadas - lidas - set(LACUNAS_DECLARADAS))
    assert not surpresas, (
        f"{surpresas} são classificadas por retrieve/fonte.py e o indexador não as lê. "
        "Ou entra parser, ou entra em LACUNAS_DECLARADAS com o pacote que fecha — "
        "silêncio aqui produz fatia vazia e 'hipótese refutada' falso."
    )


def test_a_lacuna_declarada_nao_pode_virar_esquecimento() -> None:
    """Toda lacuna aponta um pacote. Sem isso ela deixa de ser dívida e vira hábito."""
    for ext, motivo in LACUNAS_DECLARADAS.items():
        assert ext.startswith("."), ext
        assert motivo.strip(), f"lacuna {ext} sem pacote declarado"


def test_lacuna_que_o_indexador_passou_a_ler_sai_da_tabela() -> None:
    """Quando o parser entrar, este teste falha e obriga a limpar a dívida.

    Sem ele a tabela sobrevive ao próprio conserto, e a próxima leitura acha que
    a fatia continua vazia quando ela já mede.
    """
    lidas = set(supported_extensions())
    resolvidas = sorted(set(LACUNAS_DECLARADAS) & lidas)
    assert not resolvidas, (
        f"{resolvidas} já são lidas pelo indexador: tirar de LACUNAS_DECLARADAS e "
        "medir a fatia, que deixou de ser vazia"
    )


@pytest.mark.parametrize(
    "caminho",
    [
        "Documentos/09. Meetings/2025/gravacao_2025-03-14_0930.vtt",
        "corpus/09. meetings/2024/gravacao_2024-01-03_1000.vtt",
    ],
)
def test_transcricao_segue_classificada_como_reuniao(caminho: str) -> None:
    """A classificação não está errada — ela está adiantada em relação ao parser.

    Manter o comportamento documentado evita que alguém "conserte" o grupo em vez
    do parser, que é o conserto de verdade.
    """
    assert grupo_de_fonte(caminho) == REUNIAO
