"""Baseline over the real golden set: the F0 starting number.

Skips when census.toml is absent — the roots are personal paths and are not
versioned, so a fresh clone runs the metric tests and skips this one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.census import load_config

from eval.baselines import BuscaPorNomeDeArquivo, tokenizar
from eval.harness import KS_PADRAO, avaliar, carregar_perguntas

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "census.toml"
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"


def test_tokenizar_remove_acento_e_palavra_vazia() -> None:
    assert tokenizar("Qual a versão vigente da Política de IA?") == ["versao", "vigente", "politica", "ia"]
    assert tokenizar("PO-ACME-007") == ["po", "acme", "007"]


def test_busca_por_nome_ordena_por_sobreposicao(tmp_path: Path) -> None:
    from eval.baselines import DocumentoIndexado

    docs = [
        DocumentoIndexado("Contratos/contrato Tess 2026.pdf", frozenset({"contrato", "tess", "2026"}), frozenset({"contratos"})),
        DocumentoIndexado("Outros/ata.pdf", frozenset({"ata"}), frozenset({"outros"})),
        DocumentoIndexado("Tess/anexo.pdf", frozenset({"anexo"}), frozenset({"tess"})),
    ]
    hits = BuscaPorNomeDeArquivo(docs).search("contrato da Tess", 10)

    assert [h.path for h in hits] == ["Contratos/contrato Tess 2026.pdf", "Tess/anexo.pdf"]
    assert hits[0].score > hits[1].score


def test_consulta_sem_termos_uteis(tmp_path: Path) -> None:
    from eval.baselines import DocumentoIndexado

    docs = [DocumentoIndexado("a.pdf", frozenset({"a"}), frozenset())]
    assert BuscaPorNomeDeArquivo(docs).search("o que é isso", 5) == []


SUBARVORE_DEV = "01. Inteligência Artificial"
"""Recorte de desenvolvimento da F1 — o mesmo que o indexador recebe em `--prefixo`."""


@pytest.mark.skipif(not CONFIG.exists(), reason="census.toml ausente (raízes reais não configuradas)")
@pytest.mark.parametrize("prefixo", [SUBARVORE_DEV, None], ids=["subárvore de dev", "raiz completa"])
def test_baseline_no_corpus_real(prefixo: str | None, capsys: pytest.CaptureFixture) -> None:
    """Imprime a referência que as portas do ROADMAP citam, nas duas condições.

    As duas, e não só uma, porque a escala move recall@1 em 16% sozinha
    (`docs/escala-f0.md`): comparar um recuperador da subárvore com um baseline
    da raiz inteira mede a diferença de acervo e a credita ao ranqueador.
    """
    cfg = load_config(CONFIG)
    perguntas = carregar_perguntas(GOLDEN)
    retriever = BuscaPorNomeDeArquivo.a_partir_de(cfg.roots, cfg, prefixo=prefixo)
    completo = avaliar(retriever, perguntas)
    resultado = completo.restrito_ao_escopo()

    with capsys.disabled():
        recorte = prefixo or "raiz completa"
        print(f"\n{completo.retriever} — {len(retriever.documentos)} documentos, recorte: {recorte}")
        print(f"  {len(resultado.itens)} perguntas no escopo, de {len(perguntas)}")
        cabecalho = "  ".join(f"r@{k}" for k in KS_PADRAO)
        print(f"          {cabecalho}   MRR    nDCG")
        vals = "  ".join(f"{resultado.recall(k):.2f}" for k in KS_PADRAO)
        print(f"  geral   {vals}  {resultado.mrr():.3f}  {resultado.ndcg():.3f}")
        for tipo in resultado.tipos:
            vals = "  ".join(f"{resultado.recall(k, tipo):.2f}" for k in KS_PADRAO)
            print(f"  {tipo:<7} {vals}  {resultado.mrr(tipo):.3f}  {resultado.ndcg(tipo):.3f}")
        vals = "  ".join(f"{completo.recall(k):.2f}" for k in KS_PADRAO)
        print(f"  (conjunto completo, {len(perguntas)} perguntas: {vals})")
        print(f"  sem nenhum acerto: {len(resultado.sem_nenhum_acerto)}/{len(resultado.itens)}")

    assert len(completo.itens) == len(perguntas)
    assert retriever.documentos, "corpus vazio — a configuração aponta para o lugar errado?"
    assert len(resultado.itens) < len(perguntas), "nenhuma pergunta anotada como fora de escopo?"
