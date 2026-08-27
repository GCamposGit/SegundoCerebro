"""O construtor de legenda do gerador, e o contrato que ele fecha.

O `F4-T` fechou um defeito em que o produto **classificava** um formato que não
**lia**. O gerador pode reintroduzi-lo pelo outro lado: escrever um `.srt` de prosa
passa toda guarda de cobertura e produz arquivo que o parser devolve vazio — corpus
com documento sem chunk, e pergunta do dourado apontando para nada.

Estes testes fecham as duas pontas: o construtor cobre toda extensão de
transcrição que o produto lê, e o que ele escreve volta pelo **despachante que o
indexador usa**, não por uma releitura própria.
"""

from __future__ import annotations

import pytest

from eval.gerador.transcricao import (
    POR_EXTENSAO,
    SEGUNDOS_POR_FALA,
    falas_de,
    sbv_de,
    srt_de,
    vtt_de,
)
from segundocerebro.ingest.parsers import parser_for
from segundocerebro.ingest.parsers.vtt import SALTO_DE_ASSUNTO
from segundocerebro.retrieve.fonte import EXTENSOES_DE_TRANSCRICAO

FALAS = [
    "Entao, deixa eu recapitular antes de encerrar.",
    "O comite aprovou o contrato NN-VCE-001 para o ciclo.",
    "Isso, e o valor esta fechado.",
]


def test_o_construtor_cobre_toda_extensao_de_transcricao_que_o_produto_le() -> None:
    """Extensão nova em `fonte.py` sem construtor aqui vira arquivo de prosa."""
    assert set(POR_EXTENSAO) == set(EXTENSOES_DE_TRANSCRICAO)


@pytest.mark.parametrize("ext", sorted(POR_EXTENSAO))
def test_o_que_o_gerador_escreve_volta_pelo_parser_do_produto(ext: str) -> None:
    """Instrumento real: o despachante do indexador, não uma releitura local."""
    conteudo = POR_EXTENSAO[ext](FALAS)
    parser = parser_for(ext)
    assert parser is not None, f"{ext} sem parser — o gerador escreveria para ninguém"
    doc = parser(conteudo.encode("utf-8"), f"Gravacao_2025-03-14_0930{ext}")
    texto = "\n".join(b.text for b in doc.blocks)
    assert "NN-VCE-001" in texto, f"{ext}: o identificador não voltou"
    assert doc.blocks, f"{ext}: zero blocos"


@pytest.mark.parametrize("ext", sorted(POR_EXTENSAO))
def test_as_falas_saem_no_mesmo_bloco(ext: str) -> None:
    """O corpus não pode medir a fronteira de bloco do parser sem querer.

    `SEGUNDOS_POR_FALA` existe abaixo de `SALTO_DE_ASSUNTO` justamente para isso.
    Se um dos dois mudar sem o outro, este teste avisa antes de o corpus mudar de
    forma por baixo de uma medição.
    """
    assert SEGUNDOS_POR_FALA - 11 < SALTO_DE_ASSUNTO
    doc = parser_for(ext)(POR_EXTENSAO[ext](FALAS).encode("utf-8"), f"g{ext}")
    assert len(doc.blocks) == 1, f"{ext}: {len(doc.blocks)} blocos para 3 falas curtas"


def test_cada_formato_tem_a_sua_sintaxe_e_nao_a_do_vizinho() -> None:
    """Três formatos, três sintaxes. Escrever VTT com extensão `.srt` passaria os
    testes acima — o parser é tolerante — e mentiria sobre a cobertura."""
    vtt, srt, sbv = vtt_de(FALAS), srt_de(FALAS), sbv_de(FALAS)
    assert vtt.startswith("WEBVTT")
    assert "-->" in vtt and "." in vtt.split("\n")[2]

    # SRT: índice numérico, e vírgula como separador decimal.
    assert srt.split("\n")[0] == "1"
    assert "-->" in srt and ",000" in srt

    # SBV: sem cabeçalho, sem índice, vírgula separando os dois tempos.
    assert not sbv.startswith("WEBVTT")
    assert "-->" not in sbv
    assert sbv.split("\n")[0].count(",") == 1


def test_falas_de_ignora_linha_vazia() -> None:
    assert falas_de("uma\n\n  \noutra\n") == ["uma", "outra"]


def test_sem_falas_nao_produz_cue() -> None:
    """Documento vazio tem de continuar vazio, e não virar cabeçalho solto."""
    for construtor in (vtt_de, srt_de, sbv_de):
        conteudo = construtor([])
        doc = parser_for(".vtt")(conteudo.encode("utf-8"), "g.vtt")
        assert doc.blocks == ()
