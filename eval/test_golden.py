"""Sanity checks for the golden set.

A question whose expected source has a typo is never retrieved, so the metric
drops and the blame lands on the retriever. These tests make that failure mode
loud instead of silent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"
CONFIG = REPO / "census.toml"

TIPOS = {"exato", "semantica", "temporal", "multihop"}
MIX_ALVO = {"exato": 15, "semantica": 20, "temporal": 8, "multihop": 7}


def carregar() -> list[dict]:
    if not GOLDEN.exists():
        pytest.skip("conjunto dourado ainda não existe")
    linhas = [l for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in linhas]


def raizes() -> list[Path]:
    """Roots from census.toml — absent in a fresh clone, so tests skip."""
    if not CONFIG.exists():
        return []
    import tomllib

    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    return [Path(r["path"]) for r in data.get("roots", []) if "path" in r]


def caminho_longo(p: Path) -> str:
    """Windows extended-length prefix: the corpus has paths over 260 chars."""
    if os.name != "nt":
        return str(p)
    return "\\\\?\\" + str(p)


@pytest.fixture(scope="module")
def perguntas() -> list[dict]:
    return carregar()


def test_ids_unicos(perguntas: list[dict]) -> None:
    ids = [p["id"] for p in perguntas]
    assert len(ids) == len(set(ids)), "ids duplicados quebram o histórico de métricas"


def test_campos_obrigatorios(perguntas: list[dict]) -> None:
    for p in perguntas:
        assert p.get("id"), p
        assert p.get("pergunta", "").strip(), p
        assert p.get("fontes"), f"{p['id']} sem fonte esperada"
        assert p.get("tipo") in TIPOS, f"{p['id']} tem tipo inválido: {p.get('tipo')}"


def test_fontes_usam_barra_normal(perguntas: list[dict]) -> None:
    for p in perguntas:
        for f in p["fontes"]:
            assert "\\" not in f, f"{p['id']}: use / como separador — {f}"
            assert not f.startswith("/"), f"{p['id']}: caminho deve ser relativo à raiz — {f}"


def test_fora_de_escopo_tem_motivo_catalogado(perguntas: list[dict]) -> None:
    """Excluir pergunta é decisão de escopo, e decisão precisa de motivo nomeado.

    Texto livre viraria um campo onde qualquer pergunta difícil pode ser
    escondida com uma justificativa nova. O catálogo fecha essa porta: motivo
    novo exige editar o harness, o que aparece em diff.
    """
    from eval.harness import MOTIVOS_FORA_DE_ESCOPO

    for p in perguntas:
        motivo = p.get("fora_de_escopo", "")
        if not motivo:
            continue
        assert motivo in MOTIVOS_FORA_DE_ESCOPO, f"{p['id']}: motivo `{motivo}` não catalogado"
        assert p.get("notas", "").strip(), f"{p['id']} está fora de escopo e não explica por quê"


def test_maioria_das_perguntas_continua_no_escopo(perguntas: list[dict]) -> None:
    """Guarda contra erosão: excluir aos poucos até o número ficar bonito.

    O limite é arbitrário de propósito — serve para forçar uma conversa quando
    a próxima exclusão for proposta, não para validar as que já existem.
    """
    fora = [p["id"] for p in perguntas if p.get("fora_de_escopo")]
    assert len(fora) <= len(perguntas) * 0.2, f"{len(fora)} de {len(perguntas)} fora de escopo: {fora}"


@pytest.mark.skipif(not CONFIG.exists(), reason="census.toml ausente (raízes reais não configuradas)")
def test_toda_fonte_existe(perguntas: list[dict]) -> None:
    todas = raizes()
    if not todas:
        pytest.skip("nenhuma raiz configurada")

    faltando: list[str] = []
    for p in perguntas:
        for f in p["fontes"]:
            rel = Path(f.replace("/", os.sep))
            if not any(os.path.exists(caminho_longo(raiz / rel)) for raiz in todas):
                faltando.append(f"{p['id']}: {f}")

    assert not faltando, "fontes inexistentes (erro de digitação silencia a métrica):\n" + "\n".join(faltando)


def test_relatorio_de_cobertura(perguntas: list[dict], capsys: pytest.CaptureFixture) -> None:
    """Not a gate — prints how far the set is from the target mix."""
    contagem = {t: sum(1 for p in perguntas if p["tipo"] == t) for t in TIPOS}
    total = len(perguntas)
    with capsys.disabled():
        print(f"\nconjunto dourado: {total}/50 perguntas")
        for tipo, alvo in MIX_ALVO.items():
            print(f"  {tipo:<10} {contagem[tipo]:>2}/{alvo}")
        nao_validadas = [p["id"] for p in perguntas if not p.get("validada")]
        if nao_validadas:
            print(f"  aguardando validação do usuário: {', '.join(nao_validadas)}")
    assert total > 0


# --- métrica é por base, nunca agregada --------------------------------------


def _pergunta(id_: str, base: str = "") -> str:
    d = {"id": id_, "tipo": "exato", "pergunta": "?", "fontes": ["a.pdf"]}
    if base:
        d["base"] = base
    return json.dumps(d, ensure_ascii=False)


def test_conjunto_sem_base_declarada_serve_a_qualquer_base(tmp_path: Path) -> None:
    """O conjunto de hoje não declara base, e continua medindo."""
    from .harness import carregar_perguntas, conferir_base

    alvo = tmp_path / "g.jsonl"
    alvo.write_text(_pergunta("g001") + "\n", encoding="utf-8")

    conferir_base(carregar_perguntas(alvo), "trabalho")  # não levanta


def test_conjunto_da_outra_base_e_recusado(tmp_path: Path) -> None:
    """Números plausíveis sobre o acervo errado são piores que um erro."""
    from .harness import carregar_perguntas, conferir_base

    alvo = tmp_path / "g.jsonl"
    alvo.write_text(
        _pergunta("g001", "pessoal") + "\n" + _pergunta("g002", "pessoal") + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="2 pergunta"):
        conferir_base(carregar_perguntas(alvo), "trabalho")


def test_base_declarada_e_igual_passa(tmp_path: Path) -> None:
    from .harness import carregar_perguntas, conferir_base

    alvo = tmp_path / "g.jsonl"
    alvo.write_text(_pergunta("g001", "trabalho") + "\n", encoding="utf-8")

    conferir_base(carregar_perguntas(alvo), "trabalho")


def test_o_conjunto_real_carrega_com_o_campo_novo() -> None:
    """O campo é opcional — as 51 perguntas existentes não mudam."""
    from .harness import carregar_perguntas

    assert all(p.base == "" for p in carregar_perguntas(GOLDEN))
