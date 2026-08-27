"""C5.c — o sucessor do MIRACL é decisão congelada, não download."""

from __future__ import annotations

import ast
from pathlib import Path

from eval.alarme_externo import (
    ARTEFATOS,
    CAMADA_3,
    CANARIO_CROSSLINGUAL,
    MOTIVO_CABE,
    MOTIVO_CUSTO,
    MOTIVO_DOMINIO,
    MOTIVO_LINGUA,
    MOTIVO_TRADUCAO,
    avaliar,
    camada_3,
    main,
    render,
)
from eval.custo_miracl import ADOTAR, DESCARTAR, PORTA_HORAS

FONTE = Path(__file__).resolve().parent / "alarme_externo.py"
DOC = Path(__file__).resolve().parents[1] / "docs" / "alarme-externo.md"


def test_camada_3_e_quati_50k_e_cabe_na_porta() -> None:
    v = camada_3()
    assert v.artefato.id == CAMADA_3 == "quati-50k"
    assert v.artefato.nativo and v.artefato.licenca_aberta
    assert v.horas < PORTA_HORAS
    assert v.recorte == ADOTAR
    assert v.motivo == MOTIVO_CABE
    assert v.baixou is False


def test_quati_1m_estoura_a_porta() -> None:
    v = avaliar(ARTEFATOS["quati-1m"])
    assert v.horas > PORTA_HORAS
    assert v.recorte == DESCARTAR
    assert v.motivo == MOTIVO_CUSTO


def test_mmarco_sai_por_traducao_antes_do_custo() -> None:
    v = avaliar(ARTEFATOS["mmarco-pt"])
    assert not v.artefato.nativo
    assert v.motivo == MOTIVO_TRADUCAO
    assert v.recorte == DESCARTAR


def test_miracl_pt_continua_lingua_ausente() -> None:
    v = avaliar(ARTEFATOS["miracl-pt"])
    assert v.motivo == MOTIVO_LINGUA
    assert v.recorte == DESCARTAR


def test_pira_e_canario_nao_alarme() -> None:
    assert CANARIO_CROSSLINGUAL == "pira-2"
    a = ARTEFATOS["pira-2"]
    assert a.papel == "canario"
    assert avaliar(a).recorte == ADOTAR


def test_juristcu_nao_substitui_a_camada_3() -> None:
    v = avaliar(ARTEFATOS["juristcu"])
    assert v.recorte == DESCARTAR
    assert v.motivo == MOTIVO_DOMINIO
    assert v.horas < PORTA_HORAS  # caberia; não é por custo


def test_fonte_nao_baixa_dataset() -> None:
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    froms = [
        n.module.split(".")[0]
        for n in ast.walk(arvore)
        if isinstance(n, ast.ImportFrom) and n.module
    ]
    assert "datasets" not in froms
    assert "huggingface_hub" not in froms
    assert "load_dataset" not in FONTE.read_text(encoding="utf-8")


def test_relatorio_congela_quati_e_recusa_mmarco() -> None:
    texto = render([avaliar(a) for a in ARTEFATOS.values()])
    assert "`quati-50k`" in texto
    assert "adotar" in texto
    assert "mMARCO" in texto or "mmarco" in texto
    assert "não" in texto.lower()
    assert "[[base]]" in texto


def test_cli_adota_camada_3(capsys: object) -> None:
    assert main([]) == 0
    saida = capsys.readouterr().out  # type: ignore[attr-defined]
    assert CAMADA_3 in saida


def test_doc_publica_a_decisao() -> None:
    assert DOC.is_file()
    texto = DOC.read_text(encoding="utf-8")
    assert "quati-50k" in texto
    assert "mMARCO" in texto or "mmarco" in texto.lower()
    assert "não" in texto.lower()
    assert "E:\\" not in texto
    assert "12" in texto
