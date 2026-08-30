"""A fatia cross-lingual — detector, anotação e recorte no relatório.

O que estes testes protegem é uma regra só, e é a razão de a fatia existir: um
par pergunta→fonte **nunca** entra numa fatia por chute. Sem evidência de idioma
dos dois lados, ele vai para `não declarado` com o n à mostra. A alternativa —
assumir `pt` porque o acervo é majoritariamente PT — deixaria a fatia
cross-lingual pequena, otimista e errada exatamente onde ela deveria acusar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness import Pergunta, avaliar, carregar_perguntas, render_markdown
from eval.idioma import (
    CROSS_LINGUAL,
    EN,
    INDEFINIDO,
    MESMA_LINGUA,
    MISTO,
    NAO_DECLARADO,
    PT,
    DivergenciaDeIdioma,
    _atualizar_linha,
    conferir,
    detalhar,
    detectar,
    fatia,
    idioma_do_conjunto,
)
from eval.falsos import RecuperadorFixo

PARAGRAFO_PT = (
    "Este documento estabelece as diretrizes para a contratação de serviços de "
    "consultoria, conforme o disposto na política vigente, e deve ser observado "
    "por todas as áreas envolvidas no processo de aquisição."
)
PARAGRAFO_EN = (
    "This document sets out the guidelines for the procurement of consulting "
    "services, in accordance with the policy in force, and shall be observed by "
    "all of the areas involved in the acquisition process."
)


# --- detector ---------------------------------------------------------------


def test_paragrafo_longo_em_cada_idioma() -> None:
    assert detectar(PARAGRAFO_PT) == PT
    assert detectar(PARAGRAFO_EN) == EN


def test_pergunta_curta_em_portugues_e_decidida() -> None:
    """O caso que importa: o conjunto dourado é feito de frases de uma linha."""
    assert detectar("Qual o prazo de vigência do contrato?") == PT
    assert detectar("Quem assinou a política de segurança?") == PT


def test_pergunta_curta_em_ingles_e_decidida() -> None:
    assert detectar("What is the termination notice period?") == EN


def test_sigla_e_numero_sem_evidencia_ficam_indefinidos() -> None:
    """Duas das 62 perguntas do acervo corporativo são assim.

    Baixar o limiar para acertar estas duas passaria a errar as outras sessenta
    em silêncio — por isso a saída certa aqui é `indefinido`, e a correção é
    anotar `idioma` na pergunta."""
    assert detectar("SLA PO-CORP-007") == INDEFINIDO
    assert detectar("ISO 42001:2023") == INDEFINIDO


def test_palavra_dos_dois_idiomas_nao_conta_para_nenhum() -> None:
    """`a`, `do`, `no`, `as`, `so` existem nas duas línguas.

    Sem o desconto, um texto em inglês cheio de `as` acumularia pontos de
    português proporcionais ao tamanho — e quanto maior o documento, mais errado
    o veredito."""
    assert detectar("a do no as so") == INDEFINIDO


def test_so_sem_acento_nao_pontua_para_o_ingles() -> None:
    """`só` perde o acento na normalização e vira a palavra inglesa `so`.

    O detector normaliza para casar `política` com `politica`; o efeito colateral
    é criar palavra inglesa a partir de português. Uma frase PT curta com `só`
    não pode virar EN por causa disso."""
    assert detectar("Só o gestor da área pode aprovar.") == PT


def test_texto_metade_e_metade_e_misto() -> None:
    d = detalhar(PARAGRAFO_PT + " " + PARAGRAFO_EN)
    assert d.idioma == MISTO
    assert d.pt > 0 and d.en > 0


def test_vazio_e_indefinido() -> None:
    assert detectar("") == INDEFINIDO
    assert detectar("   ") == INDEFINIDO


def test_grafema_exclusivo_nao_decide_texto_longo_sozinho() -> None:
    """Um EN que cita dois nomes próprios portugueses continua EN.

    É o teto de `_grafemas`: sem ele o `ç` de um nome de fornecedor bastaria
    para reclassificar um contrato inteiro."""
    assert detectar(PARAGRAFO_EN + " Signed in São Paulo by Conceição.") == EN


# --- a fatia ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "f", "esperado"),
    [
        (PT, PT, MESMA_LINGUA),
        (EN, EN, MESMA_LINGUA),
        (PT, EN, CROSS_LINGUAL),
        (EN, PT, CROSS_LINGUAL),
        (PT, MISTO, NAO_DECLARADO),
        (PT, INDEFINIDO, NAO_DECLARADO),
        (INDEFINIDO, EN, NAO_DECLARADO),
        (PT, "", NAO_DECLARADO),
        ("", "", NAO_DECLARADO),
    ],
)
def test_tabela_da_fatia(q: str, f: str, esperado: str) -> None:
    assert fatia(q, f) == esperado


def test_fontes_que_discordam_nao_viram_cross_lingual() -> None:
    """Multi-hop com uma fonte PT e outra EN não é caso de ponte quebrada.

    O recuperador tinha alternativa no idioma da pergunta; contar como acerto
    cross-lingual mediria o contrário do que a fatia quer medir."""
    idiomas = {"a.pdf": PT, "b.pdf": EN}
    assert idioma_do_conjunto(("a.pdf", "b.pdf"), idiomas) == MISTO
    assert idioma_do_conjunto(("a.pdf",), idiomas) == PT
    assert idioma_do_conjunto(("a.pdf", "sumiu.pdf"), idiomas) == INDEFINIDO


# --- Pergunta ---------------------------------------------------------------


def _p(**kw) -> Pergunta:  # noqa: ANN003
    campos = {"id": "g1", "tipo": "exato", "pergunta": "SLA PO-CORP-007", "fontes": ("a.pdf",)}
    return Pergunta(**{**campos, **kw})


def test_anotacao_vence_a_deteccao_na_pergunta() -> None:
    assert _p().idioma_efetivo == INDEFINIDO
    assert _p(idioma=PT).idioma_efetivo == PT
    assert _p(idioma=PT, idioma_fonte=EN).fatia == CROSS_LINGUAL


def test_fonte_sem_anotacao_nao_tem_deteccao_de_reserva() -> None:
    """A assimetria é o ponto: o texto da pergunta está aqui, o do documento não.

    Detectá-lo no relatório exigiria índice aberto, e o baseline por nome não
    abre índice — a fatia sumiria justamente do lado F0 da comparação."""
    p = _p(pergunta="Qual o prazo de vigência do contrato?")
    assert p.idioma_efetivo == PT
    assert p.fatia == NAO_DECLARADO


def test_codigo_de_idioma_desconhecido_e_erro(tmp_path: Path) -> None:
    """`pt-BR` cairia calado em `não declarado` — o modo de falha que a fatia acaba."""
    arquivo = tmp_path / "p.jsonl"
    arquivo.write_text(
        json.dumps(
            {"id": "g1", "tipo": "exato", "pergunta": "x", "fontes": ["a.pdf"], "idioma_fonte": "pt-BR"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="idioma não reconhecido"):
        carregar_perguntas(arquivo)


def test_carrega_os_dois_campos(tmp_path: Path) -> None:
    arquivo = tmp_path / "p.jsonl"
    arquivo.write_text(
        json.dumps(
            {
                "id": "g1",
                "tipo": "exato",
                "pergunta": "x",
                "fontes": ["a.pdf"],
                "idioma": "pt",
                "idioma_fonte": "en",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (p,) = carregar_perguntas(arquivo)
    assert (p.idioma, p.idioma_fonte, p.fatia) == (PT, EN, CROSS_LINGUAL)


# --- relatório --------------------------------------------------------------


def _resultado(perguntas: list[Pergunta]):  # noqa: ANN202
    return avaliar(RecuperadorFixo(["a.pdf", "b.pdf"]), perguntas)


def test_as_tres_fatias_aparecem_mesmo_vazias() -> None:
    """Fatia com n=0 some da tabela se não for forçada — e some junto o aviso.

    "Medimos e não há par cross-lingual" e "a fatia não foi calculada" viram a
    mesma tabela, que é exatamente a lacuna que C4.5 fecha."""
    r = _resultado([_p(id="g1", idioma=PT, idioma_fonte=PT)])
    rotulos = [rotulo for rotulo, _ in r.por_fatia()]
    assert rotulos == [MESMA_LINGUA, CROSS_LINGUAL, NAO_DECLARADO]
    markdown = render_markdown(r, "t")
    assert "## Por idioma" in markdown
    for rotulo in rotulos:
        assert f"| {rotulo} |" in markdown
    assert f"| {CROSS_LINGUAL} | 0 |" in markdown


def test_razao_so_sai_com_as_duas_fatias_povoadas() -> None:
    so_mesma = render_markdown(_resultado([_p(id="g1", idioma=PT, idioma_fonte=PT)]), "t")
    assert "Razão cross-lingual" not in so_mesma
    assert "eval.idioma" in so_mesma

    das_duas = render_markdown(
        _resultado(
            [
                _p(id="g1", fontes=("a.pdf",), idioma=PT, idioma_fonte=PT),
                _p(id="g2", fontes=("b.pdf",), idioma=PT, idioma_fonte=EN),
            ]
        ),
        "t",
    )
    assert "Razão cross-lingual" in das_duas
    assert "0.80" in das_duas


def test_nao_declarado_nao_entra_em_nenhuma_das_duas() -> None:
    r = _resultado(
        [
            _p(id="g1", idioma=PT, idioma_fonte=PT),
            _p(id="g2", idioma=PT),
            _p(id="g3", idioma=PT, idioma_fonte=MISTO),
        ]
    )
    contagem = {rotulo: len(itens) for rotulo, itens in r.por_fatia()}
    assert contagem == {MESMA_LINGUA: 1, CROSS_LINGUAL: 0, NAO_DECLARADO: 2}


# --- conferência contra o índice --------------------------------------------


def test_conferir_separa_falta_de_anotacao_de_anotacao_mentindo() -> None:
    perguntas = [
        _p(id="g1", fontes=("a.pdf",)),
        _p(id="g2", fontes=("b.pdf",), idioma_fonte=PT),
        _p(id="g3", fontes=("c.pdf",), idioma_fonte=EN),
    ]
    idiomas = {"a.pdf": PT, "b.pdf": EN, "c.pdf": EN}
    por_id = {d.id: d for d in conferir(perguntas, idiomas)}
    assert por_id["g1"].especie == "sem_anotacao"
    assert por_id["g2"].especie == "divergente"
    assert "g3" not in por_id


def test_fonte_indetectavel_nao_vira_pendencia() -> None:
    """PDF digitalizado sem chunk é o estado normal, não uma anotação faltando."""
    assert conferir([_p(id="g1", fontes=("a.pdf",))], {"a.pdf": INDEFINIDO}) == []


def test_divergencia_e_um_registro_e_nao_uma_string() -> None:
    (d,) = conferir([_p(id="g1", fontes=("a.pdf",))], {"a.pdf": PT})
    assert isinstance(d, DivergenciaDeIdioma)


def test_escrita_preserva_ordem_e_campos_desconhecidos() -> None:
    """O conjunto dourado real não vai para o Git: a única revisão possível é o
    `git diff` local de quem o tem. Reordenar campos apagaria essa revisão."""
    linha = json.dumps(
        {"id": "g1", "tipo": "exato", "pergunta": "x", "fontes": ["a.pdf"], "campo_futuro": 7},
        ensure_ascii=False,
    )
    nova = json.loads(_atualizar_linha(linha, PT, EN))
    assert list(nova) == ["id", "tipo", "pergunta", "fontes", "campo_futuro", "idioma", "idioma_fonte"]
    assert nova["campo_futuro"] == 7


def test_indefinido_nao_e_gravado_no_idioma_da_pergunta() -> None:
    """Gravar `indefinido` em `idioma` congelaria a pergunta contra o detector.

    O campo tem detecção de reserva e **não** tem `conferir()`: uma anotação
    indecisa ali sobreviveria calada a qualquer melhora nas listas. Em
    `idioma_fonte` é o contrário — lá `indefinido` é dado, e `conferir()` o
    confronta com o índice a cada medição."""
    linha = json.dumps({"id": "g1", "fontes": ["a.pdf"]}, ensure_ascii=False)
    nova = json.loads(_atualizar_linha(linha, "", INDEFINIDO))
    assert "idioma" not in nova
    assert nova["idioma_fonte"] == INDEFINIDO


def test_escrita_atualiza_no_lugar_quando_o_campo_ja_existe() -> None:
    linha = json.dumps({"id": "g1", "idioma_fonte": "pt", "notas": "x"}, ensure_ascii=False)
    nova = json.loads(_atualizar_linha(linha, "", EN))
    assert list(nova) == ["id", "idioma_fonte", "notas"]
    assert nova["idioma_fonte"] == EN
