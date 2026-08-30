"""Escopo da fase: o que entra na média, o que fica de fora, e por quê.

A regra que estes testes protegem é uma só: a exclusão tem que ser uma decisão
declarada, e nunca um efeito colateral do índice. Um parser que quebrasse não
pode fazer a métrica subir por ter derrubado as perguntas que ele passou a
errar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness import (
    MOTIVOS_FORA_DE_ESCOPO,
    Pergunta,
    avaliar,
    carregar_perguntas,
    render_markdown,
    verificar_escopo,
)
from eval.falsos import RecuperadorFixo


def pergunta(id_: str, fontes: list[str], *, tipo: str = "exato", fora: str = "") -> Pergunta:
    return Pergunta(id=id_, tipo=tipo, pergunta=f"pergunta {id_}", fontes=tuple(fontes), fora_de_escopo=fora)


# --- anotação ---------------------------------------------------------------


def test_motivo_nao_catalogado_e_erro(tmp_path: Path) -> None:
    arquivo = tmp_path / "p.jsonl"
    arquivo.write_text(
        json.dumps(
            {"id": "x1", "tipo": "exato", "pergunta": "?", "fontes": ["a.pdf"], "fora_de_escopo": "porque sim"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="não catalogado"):
        carregar_perguntas(arquivo)


def test_pergunta_sem_anotacao_esta_no_escopo() -> None:
    assert pergunta("x1", ["a.pdf"]).no_escopo
    assert not pergunta("x2", ["digitalizado.pdf"], fora="ocr").no_escopo


# --- agregação --------------------------------------------------------------


def test_restrito_ao_escopo_muda_o_denominador() -> None:
    perguntas = [
        pergunta("x1", ["achado.pdf"]),
        pergunta("x2", ["inalcancavel.pdf"], fora="ocr"),
    ]
    resultado = avaliar(RecuperadorFixo(["achado.pdf"]), perguntas)

    assert resultado.recall(1) == pytest.approx(0.5), "conjunto completo carrega a fonte ilegível"
    assert resultado.restrito_ao_escopo().recall(1) == pytest.approx(1.0)
    assert [i.pergunta.id for i in resultado.fora_do_escopo] == ["x2"]


def test_relatorio_mostra_os_dois_conjuntos_e_lista_a_exclusao() -> None:
    perguntas = [
        pergunta("x1", ["achado.pdf"]),
        pergunta("x2", ["digitalizado.pdf"], fora="ocr"),
    ]
    texto = render_markdown(avaliar(RecuperadorFixo(["achado.pdf"]), perguntas), "t")

    assert "**no escopo da fase**" in texto
    assert "conjunto completo" in texto
    assert "## Fora de escopo — 1 de 2" in texto
    assert "x2" in texto and MOTIVOS_FORA_DE_ESCOPO["ocr"] in texto


def test_relatorio_sem_exclusao_diz_que_nao_ha() -> None:
    texto = render_markdown(avaliar(RecuperadorFixo(["a.pdf"]), [pergunta("x1", ["a.pdf"])]), "t")
    assert "Nenhuma — todas as perguntas" in texto


# --- guarda de consistência -------------------------------------------------


def test_fonte_ausente_em_pergunta_do_escopo_e_erro_silencioso() -> None:
    divergencias = verificar_escopo([pergunta("x1", ["sumiu.pdf"])], indexados=set())

    assert [(d.id, d.especie) for d in divergencias] == [("x1", "silenciosa")]


def test_multihop_com_uma_fonte_faltando_ja_conta_como_silenciosa() -> None:
    """Multi-hop pontua por `todas`: uma fonte ausente trava a pergunta em zero.

    Sem a regra por modo, esta pergunta passaria pela guarda — tem fonte no
    índice — e mediria zero para sempre sem ninguém saber o motivo.
    """
    p = pergunta("x1", ["tem.pdf", "nao_tem.msg"], tipo="multihop")

    assert [d.especie for d in verificar_escopo([p], {"tem.pdf"})] == ["silenciosa"]
    assert verificar_escopo([p], {"tem.pdf", "nao_tem.msg"}) == []


def test_pergunta_comum_basta_uma_fonte() -> None:
    p = pergunta("x1", ["tem.pdf", "nao_tem.msg"])
    assert verificar_escopo([p], {"tem.pdf"}) == []


def test_anotacao_velha_quando_a_fonte_virou_indexavel() -> None:
    p = pergunta("x1", ["antes_ilegivel.pdf"], fora="ocr")
    divergencias = verificar_escopo([p], {"antes_ilegivel.pdf"})

    assert [(d.id, d.especie) for d in divergencias] == [("x1", "anotacao_velha")]


def test_fora_de_escopo_ainda_ilegivel_nao_reclama() -> None:
    assert verificar_escopo([pergunta("x1", ["digitalizado.pdf"], fora="ocr")], set()) == []


def test_baseline_por_nome_nao_dispara_anotacao_velha() -> None:
    """O baseline alcança um PDF digitalizado pelo nome sem abrir o arquivo.

    Presença no disco não é evidência de texto extraível, então a direção
    `anotacao_velha` não se aplica a quem ranqueia sem ler conteúdo — senão
    todo arquivo fora de escopo viraria alarme falso a cada rodada do baseline.
    """
    p = pergunta("x1", ["digitalizado.pdf"], fora="ocr")

    assert [d.especie for d in verificar_escopo([p], {"digitalizado.pdf"})] == ["anotacao_velha"]
    assert verificar_escopo([p], {"digitalizado.pdf"}, universo_de_conteudo=False) == []


def test_fonte_sumida_do_disco_alerta_mesmo_sem_conteudo() -> None:
    """Arquivo movido ou apagado interessa aos dois tipos de recuperador."""
    p = pergunta("x1", ["sumiu.pdf"])
    assert [d.especie for d in verificar_escopo([p], set(), universo_de_conteudo=False)] == ["silenciosa"]
