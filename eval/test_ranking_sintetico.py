"""As fatias de ranking cobrem todo mecanismo de `retrieve/` — e a lista sai de lá.

Mesmo método dos outros dois checklists deste pacote: `tests/test_formatos.py`
deriva de `supported_extensions()`, `tests/test_pasta_hostil.py` deriva de
`ParseStatus`, e aqui a régua é o **conteúdo de `src/segundocerebro/retrieve/`**.

Mecanismo de recuperação sem fatia que o exercite é um mecanismo que nenhuma
medição toca. Ele pode quebrar, ou pode nunca ter funcionado, e o número agregado
não muda o suficiente para alguém perceber — foi literalmente o que aconteceu com
o peso do nome, inerte em produção por semanas (`F4-P.0`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eval.adaptador_sintetico import adaptar
from eval.gerador.__main__ import gerar
from eval.harness import Pergunta

RETRIEVE = Path(__file__).resolve().parents[1] / "src" / "segundocerebro" / "retrieve"

SEM_FATIA_PROPRIA: dict[str, str] = {}
"""Módulos que não ganham fatia, com o motivo. **Hoje está vazia, e é o ponto.**

Os sete mecanismos de `retrieve/` são todos exercitados. A tabela existe pelo
mesmo desenho de `SEM_FIXTURE_POSSIVEL` na pasta hostil — a lacuna declarada é a
única que não vira dívida — e há um teste que a impede de crescer por
conveniência. Vazia, ela documenta que não há dívida; se alguém acrescentar uma
linha, tem de escrever por quê.

A primeira versão declarava `hybrid` aqui, supondo que a fusão não teria fatia
própria. O teste reprovou: `hybrid` é citado por `duplicatas`, `cross_lingual`,
`planilha_despejo` e `idioma_indeciso`. Declarar lacuna que não existe é o mesmo
defeito que esconder lacuna que existe, na direção contrária."""


@pytest.fixture(scope="module")
def perguntas(tmp_path_factory: pytest.TempPathFactory) -> list[Pergunta]:
    destino = tmp_path_factory.mktemp("ranking")
    gerar(42, 4, destino, sem_docx=True)
    return adaptar(destino, destino / "p.jsonl")


@pytest.fixture(scope="module")
def cruas(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    destino = tmp_path_factory.mktemp("ranking_cru")
    gerar(42, 4, destino, sem_docx=True)
    linhas = (destino / "perguntas.sintetico.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in linhas]


def _mecanismos() -> set[str]:
    return {
        p.stem for p in RETRIEVE.glob("*.py")
        if not p.stem.startswith("_")
    }


def test_todo_mecanismo_de_retrieve_e_exercitado_por_alguma_fatia(cruas: list[dict]) -> None:
    """A régua é a pasta `retrieve/`, não uma lista escrita à mão.

    Mecanismo novo sem fatia reprova aqui — e quem o escreveu descobre no mesmo
    dia, em vez de o mecanismo entrar em produção sem nada que o meça.
    """
    citados: set[str] = set()
    for p in cruas:
        citados.update(parte.strip() for parte in p["feature_alvo"].split("/"))

    faltando = _mecanismos() - citados - set(SEM_FATIA_PROPRIA)
    assert not faltando, (
        f"mecanismo de `retrieve/` sem fatia: {sorted(faltando)}. Acrescente a fatia, "
        f"ou nomeie-o em `feature_alvo` de uma existente, ou declare em "
        f"SEM_FATIA_PROPRIA com o motivo."
    )


def test_a_lista_de_mecanismos_sem_fatia_nao_cresce(cruas: list[dict]) -> None:
    """A tabela de lacunas é para o que não cabe, não para o que dá trabalho."""
    citados: set[str] = set()
    for p in cruas:
        citados.update(parte.strip() for parte in p["feature_alvo"].split("/"))

    indevidos = {m for m in SEM_FATIA_PROPRIA if m in citados}
    assert not indevidos, f"{sorted(indevidos)} tem fatia e está declarado sem — tirar da tabela"
    assert set(SEM_FATIA_PROPRIA) <= _mecanismos(), "a tabela cita módulo que não existe"


def test_o_vocabulario_de_idioma_e_exercitado_inteiro(perguntas: list[Pergunta]) -> None:
    """Os quatro valores de `IDIOMAS_ACEITOS`, e não os dois fáceis.

    `misto` e `indefinido` não são completismo: `idioma.decidido()` os **exclui**
    da fatia cross-lingual de propósito, para um documento metade PT metade EN não
    inflar justamente a métrica que existe para achar a fraqueza da ponte. Esse
    ramo nunca era exercitado com dado.
    """
    from eval.harness import IDIOMAS_ACEITOS

    usados = {p.idioma for p in perguntas} | {p.idioma_fonte for p in perguntas}
    assert usados == set(IDIOMAS_ACEITOS), sorted(usados)


def test_indeciso_anotado_nao_e_o_mesmo_que_nao_anotado(perguntas: list[Pergunta]) -> None:
    """A distinção que custou uma medição, travada em teste.

    A primeira versão de `conferir_eixos` exigia que nenhuma pergunta caísse no
    balde `não declarado` de `fatia`, e reprovou a fatia `idioma_indeciso` —
    **errado**: uma pergunta corretamente anotada `idioma_fonte="misto"` cai lá, e
    isso é a resposta certa. O harness já dizia em uma linha: *vazio é "ninguém
    olhou", `indefinido` é "olhou-se e não há evidência"*.
    """
    from eval.adaptador_sintetico import EixoColapsado, conferir_eixos

    indecisas = [p for p in perguntas if p.fatia == "não declarado"]
    assert indecisas, "a fatia `idioma_indeciso` sumiu"
    assert all(p.idioma and p.idioma_fonte for p in indecisas), "anotadas, não em branco"

    conferir_eixos(perguntas)  # não levanta: estão anotadas

    sem_anotacao = [*perguntas, Pergunta(id="g99", tipo="exato", pergunta="x",
                                         fontes=("a.pdf",), idioma="pt",
                                         armadilha_fatia="versoes")]
    with pytest.raises(EixoColapsado, match="idioma_fonte"):
        conferir_eixos(sem_anotacao)


def test_grafias_planta_o_que_liga_e_o_que_nao_pode_ligar(cruas: list[dict]) -> None:
    """Unificar as quatro grafias da norma **e** não unificar os dois PLs.

    A assimetria é da numeração legislativa, não da conveniência: para norma
    promulgada o ano é decoração (a LGPD é a Lei 13.709 com ou sem `/2018`), mas
    para projeto de lei o ano é identidade, porque a numeração reinicia a cada ano.
    Uma fatia que só medisse a unificação premiaria a "correção" que junta os dois
    PLs, que está errada.
    """
    grafias = [p for p in cruas if p["armadilha_fatia"] == "grafias"]
    unificar = [p for p in grafias if p["meta"].get("grafias")]
    separar = [p for p in grafias if p["meta"].get("nao_unificar")]

    assert unificar and separar, (len(unificar), len(separar))
    assert all(len(p["meta"]["grafias"]) == 4 for p in unificar)
    for p in separar:
        assert p["meta"]["nao_unificar"] not in p["docs_relevantes"], (
            "o PL de outro ano é distrator, nunca fonte esperada"
        )


def test_glossario_mede_os_dois_sentidos(cruas: list[dict]) -> None:
    """Acertar um sentido e errar o outro tem de aparecer, não sumir na média."""
    from collections import Counter

    sentidos = Counter(
        p["meta"]["sentido"] for p in cruas if p["armadilha_fatia"] == "glossario"
    )
    assert set(sentidos) == {"sigla->extenso", "extenso->sigla"}, dict(sentidos)
    assert sentidos["sigla->extenso"] == sentidos["extenso->sigla"]


def test_a_familia_sem_numero_tem_a_vigente_mais_nova_e_sem_sufixo(
    tmp_path: Path,
) -> None:
    """O número declarado aponta para o documento **errado**; só a data resolve.

    E o `mtime` é gravado pelo gerador — sem isso a fatia mediria a ordem em que
    os arquivos foram escritos, que é acidente.
    """
    from segundocerebro.census import caminho_estendido

    gerar(42, 3, tmp_path / "g", sem_docx=True)
    linhas = (tmp_path / "g" / "perguntas.sintetico.jsonl").read_text(encoding="utf-8").splitlines()
    fatia = [json.loads(x) for x in linhas if '"familia_sem_numero"' in x]
    assert fatia

    for p in fatia:
        esperada = p["docs_relevantes"][0]
        assert "_v" not in Path(esperada).stem, "a vigente não pode declarar número"
        familia = p["meta"]["familia"]
        assert len(familia) == 3

        idades = {
            c: os.stat(caminho_estendido(tmp_path / "g" / "corpus" / c)).st_mtime
            for c in familia
        }
        assert max(idades, key=idades.get) == esperada, "a vigente tem de ser a mais nova"
        numeradas = [c for c in familia if "_v" in Path(c).stem]
        assert numeradas and all(idades[c] < idades[esperada] for c in numeradas)


def test_o_chunk_hostil_poe_a_resposta_depois_do_corte(tmp_path: Path) -> None:
    """Se a resposta estivesse no primeiro parágrafo, a fatia mediria zero.

    A truncagem só aparece quando o que importa está depois do corte — foi assim
    que 80,7% do texto indexado deixou de virar vetor sem ninguém ver.
    """
    from segundocerebro.census import caminho_estendido

    gerar(42, 2, tmp_path / "g", sem_docx=True)
    linhas = (tmp_path / "g" / "perguntas.sintetico.jsonl").read_text(encoding="utf-8").splitlines()
    fatia = [json.loads(x) for x in linhas if '"chunk_hostil"' in x]
    assert len(fatia) >= 4, len(fatia)

    for p in fatia:
        alvo = caminho_estendido(tmp_path / "g" / "corpus" / p["docs_relevantes"][0])
        with open(alvo, encoding="utf-8") as fh:
            texto = fh.read()
        assert len(texto) > 8000, f"{p['id']}: documento de {len(texto)} chars não estressa nada"
        posicao = texto.rfind(p["resposta_esperada"].split()[-1])
        assert posicao > len(texto) * 0.5, f"{p['id']}: a resposta está cedo demais"

