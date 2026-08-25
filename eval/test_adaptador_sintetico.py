"""O adaptador do corpus sintético, e a conferência de eixo que é a entrega."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.adaptador_sintetico import (
    EixoColapsado,
    adaptar,
    adaptar_uma,
    censo_de_eixos,
    conferir_eixos,
)
from eval.gerador.__main__ import gerar
from eval.harness import Pergunta
from eval.idioma import CROSS_LINGUAL, MESMA_LINGUA


def _gerado(tmp_path: Path, n: int = 6) -> list[Pergunta]:
    gerar(42, n, tmp_path / "g", sem_docx=True)
    return adaptar(tmp_path / "g", tmp_path / "perguntas.jsonl")


def test_a_fatia_cross_lingual_deixou_de_ter_tamanho_zero(tmp_path: Path) -> None:
    """O achado 3 do laudo, em forma de teste — e é o número que ele mede.

    Antes: as 260 perguntas saíam `{'não declarado': 260}`, a fatia cross-lingual
    tinha tamanho **zero** e o relatório saía parecendo aprovado. Este teste falha
    se `idioma_fonte` voltar a não ser emitido, e falha dizendo o número, não
    dizendo "algo mudou".
    """
    perguntas = _gerado(tmp_path)
    fatias = censo_de_eixos(perguntas)["fatia"]

    assert fatias[CROSS_LINGUAL] > 0, f"a fatia voltou a colapsar: {dict(fatias)}"
    assert fatias[MESMA_LINGUA] > 0, "declarar `pt` onde é `pt` também é obrigação"
    assert "não declarado" not in fatias, dict(fatias)


def test_as_dez_outras_fatias_declaram_pt_em_vez_de_omitir(tmp_path: Path) -> None:
    """Declarar `pt` é diferente de omitir, e é a omissão que mata a fatia."""
    perguntas = _gerado(tmp_path)
    fora = [p for p in perguntas if p.armadilha_fatia != "cross_lingual"]

    assert fora, "sanidade: o corpus tem outras fatias"
    assert all(p.idioma == "pt" and p.idioma_fonte == "pt" for p in fora)


def test_o_gerador_nao_consegue_emitir_travessia_como_idioma() -> None:
    """Produtor que não emite código inválido é melhor que consumidor que o rejeita.

    `pt->en` é a **travessia**, não um idioma, e ela sai de cruzar os dois campos.
    O gerador do pacote a escrevia no campo que guarda o idioma da pergunta, e o
    `carregar_perguntas` só reclamava uma etapa depois. Agora reclama na emissão.
    """
    from eval.gerador.nucleo import perg

    with pytest.raises(ValueError, match="não é codigo de idioma|nao e codigo de idioma"):
        perg("q-x", "cross_lingual", "?", "!", ["a.txt"], idioma="pt->en")

    with pytest.raises(ValueError, match="idioma_fonte"):
        perg("q-x", "cross_lingual", "?", "!", ["a.txt"], idioma_fonte="ingles")


def test_conferir_eixos_recusa_eixo_que_ninguem_preencheu() -> None:
    """A generalização: nenhum eixo declarado pode ter pergunta no balde vazio.

    Não é "≥ 2 baldes" — um corpus legitimamente monolíngue tem um balde só e
    isso é verdade. O que nunca é legítimo é cair no balde que significa "ninguém
    preencheu", porque ele não distingue "não se aplica" de "esqueceram".
    """
    sem_fonte = Pergunta(
        id="g1", tipo="exato", pergunta="x", fontes=("a.pdf",),
        idioma="pt", idioma_fonte="", armadilha_fatia="versoes",
    )
    with pytest.raises(EixoColapsado, match="eixo 'fatia'.*g1"):
        conferir_eixos([sem_fonte])

    sem_armadilha = Pergunta(
        id="g2", tipo="exato", pergunta="x", fontes=("a.pdf",),
        idioma="pt", idioma_fonte="pt", armadilha_fatia="",
    )
    with pytest.raises(EixoColapsado, match="eixo 'armadilha_fatia'.*g2"):
        conferir_eixos([sem_armadilha])

    completa = Pergunta(
        id="g3", tipo="exato", pergunta="x", fontes=("a.pdf",),
        idioma="pt", idioma_fonte="pt", armadilha_fatia="versoes",
    )
    conferir_eixos([completa])


def test_o_dourado_real_nao_e_conferido_pelo_terceiro_eixo() -> None:
    """`armadilha_fatia` nasce vazio no dourado real, e isso é correto.

    Lá as perguntas vieram de uso, não de plantio. Conferir esse eixo no dourado
    real reprovaria um conjunto legítimo — por isso `EIXOS_EXIGIDOS` é o contrato
    do **sintético**, e quem chama escolhe.
    """
    de_uso = Pergunta(
        id="g10", tipo="exato", pergunta="x", fontes=("a.pdf",),
        idioma="pt", idioma_fonte="pt",
    )
    conferir_eixos([de_uso], eixos=("fatia",))

    with pytest.raises(EixoColapsado):
        conferir_eixos([de_uso])


def test_criterio_divergente_do_tipo_e_erro_alto() -> None:
    """O harness deriva o modo de `tipo`; copiar `criterio` deixaria os dois brigarem.

    O sintoma seria a pergunta dizer `todas` e a medição usar `qualquer`, em
    silêncio — a mesma classe do eixo colapsado, num campo diferente.
    """
    with pytest.raises(ValueError, match="criterio"):
        adaptar_uma({
            "id": "q-mh-000", "tipo": "multihop", "pergunta": "?",
            "docs_relevantes": ["a.txt", "b.txt"], "criterio": "qualquer",
            "idioma": "pt", "idioma_fonte": "pt", "armadilha_fatia": "multihop",
        })


def test_armadilha_vira_bool_mais_notas() -> None:
    """String descritiva no harness é `notas`; o bool é o que a fatia usa."""
    d = adaptar_uma({
        "id": "q-nr-000", "tipo": "exato", "pergunta": "?",
        "docs_relevantes": ["a.txt"], "criterio": "qualquer",
        "idioma": "pt", "idioma_fonte": "pt", "armadilha_fatia": "nomes_ruins",
        "armadilha": "nome de arquivo nao informativo",
    })

    assert d["armadilha"] is True
    assert d["notas"] == "nome de arquivo nao informativo"
    assert d["autoria"] == "gerador", "o diff nunca confunde plantio com uso"


def test_o_arquivo_guarda_o_que_o_harness_ignora(tmp_path: Path) -> None:
    """`meta` e `feature_alvo` sobrevivem à conversão — a matriz do `E2` precisa deles."""
    _gerado(tmp_path)
    linhas = [json.loads(l) for l in (tmp_path / "perguntas.jsonl").read_text(encoding="utf-8").splitlines()]

    assert all("feature_alvo" in d and "meta" in d for d in linhas)
    com_familia = [d for d in linhas if d["meta"].get("familia")]
    assert com_familia, "duplicatas@10 e o Δ de versões saem de meta.familia"
