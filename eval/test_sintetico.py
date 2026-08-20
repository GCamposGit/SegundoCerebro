"""O conjunto de exemplo e o corpus sintético — a régua de um clone fresco."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.harness import GOLDEN, GOLDEN_EXEMPLO, carregar_perguntas, conferir_base, resolver_dourado
from eval.sintetico.gerar import CORPUS, MTIMES

REPO = Path(__file__).resolve().parent.parent


def test_exemplo_existe_e_carrega() -> None:
    perguntas = carregar_perguntas(GOLDEN_EXEMPLO)
    assert len(perguntas) >= 8
    conferir_base(perguntas, "sintetico")
    assert all(p.base == "sintetico" for p in perguntas)
    assert all(p.validada for p in perguntas)


def test_fontes_do_exemplo_existem_no_corpus() -> None:
    if not CORPUS.exists():
        pytest.fail("rode `py -m eval.sintetico.gerar` e commite eval/sintetico/corpus/")
    perguntas = carregar_perguntas(GOLDEN_EXEMPLO)
    faltando = []
    for p in perguntas:
        for fonte in p.fontes:
            if not (CORPUS / fonte).is_file():
                faltando.append(f"{p.id}: {fonte}")
    assert not faltando, "fonte do exemplo sem arquivo:\n" + "\n".join(faltando)


def test_mtimes_do_gerador_cobrem_as_familias() -> None:
    """Sem data gravada, o desempate das famílias vira ordem de geração."""
    for rel in (
        "Politica de IA/PO-VCE-007_Politica de Inteligencia Artificial_v6.docx",
        "Politica de IA/PO-VCE-007_Politica de Inteligencia Artificial_revisada_GC.docx",
        "Apresentacoes/Deck_governanca_IA_v1.pptx",
        "Apresentacoes/Deck_governanca_IA_v2.pptx",
    ):
        assert rel in MTIMES


def test_familias_do_sintetico_agrupam_os_irmaos() -> None:
    from segundocerebro.retrieve.familias import chave_de_familia, colapsar

    politica_velha = "Politica de IA/PO-VCE-007_Politica de Inteligencia Artificial_v6.docx"
    politica_nova = "Politica de IA/PO-VCE-007_Politica de Inteligencia Artificial_revisada_GC.docx"
    assert chave_de_familia(politica_velha) == chave_de_familia(politica_nova)

    ranking, familias = colapsar(
        [politica_velha, politica_nova],
        {politica_velha: 1.0, politica_nova: 2.0},
    )
    assert ranking == [politica_nova]
    assert familias[politica_nova].anteriores == (politica_velha,)

    deck_v1 = "Apresentacoes/Deck_governanca_IA_v1.pptx"
    deck_v2 = "Apresentacoes/Deck_governanca_IA_v2.pptx"
    ranking, _ = colapsar([deck_v1, deck_v2], {deck_v1: 9.0, deck_v2: 1.0})
    assert ranking == [deck_v2], "número declarado vence mtime mais novo"


def test_resolver_implicito_cai_no_exemplo(tmp_path: Path) -> None:
    ausente = tmp_path / "perguntas.jsonl"
    # O fallback só vale para o caminho canônico, não para um arquivo qualquer.
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        resolver_dourado(ausente, implicito=True)

    caminho, aviso = resolver_dourado(GOLDEN, implicito=not GOLDEN.exists())
    if GOLDEN.exists():
        assert caminho == GOLDEN
        assert aviso is None
    else:
        assert caminho == GOLDEN_EXEMPLO
        assert aviso is not None
        assert "sintético" in aviso


def test_resolver_explicito_ausente_nao_substitui(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="invariante 4"):
        resolver_dourado(tmp_path / "sumiu.jsonl", implicito=False)


def test_config_sintetico_aponta_para_o_exemplo() -> None:
    from segundocerebro.config import carregar

    cfg = carregar(REPO / "config.sintetico.toml", ambiente={})
    base = cfg.base("sintetico")
    assert base.dourado.resolve() == GOLDEN_EXEMPLO.resolve()
    assert base.raizes[0].path.resolve() == CORPUS.resolve()


def test_baseline_roda_no_sintetico() -> None:
    """Clone fresco: o baseline por nome não precisa de encoder nem de GPU."""
    from eval.rodar import main

    assert main(["--config", str(REPO / "config.sintetico.toml"),
                 "--base", "sintetico", "--retriever", "baseline"]) == 0
