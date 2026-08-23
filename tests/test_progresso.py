"""Publicação de progresso e nível de esforço.

A arquitetura que estes testes protegem: o indexador publica, o painel lê, e
fechar o painel não para nada.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from segundocerebro.index.esforco import PERFIS_DE_ESFORCO, aplicar, na_bateria
from segundocerebro.index.estimativa import Estimador, Relogio
from segundocerebro.index.progresso import NOME, Publicador, caminho_de, ler

MB = 1_000_000


def publicador(tmp_path: Path) -> Publicador:
    e = Estimador()
    e.declarar([(f"{i}.pdf", MB) for i in range(10)])
    return Publicador(indice=tmp_path, estimador=e, relogio=Relogio(), intervalo=0.0)


# --- publicação ---------------------------------------------------------------


def test_sem_indexacao_nao_ha_progresso(tmp_path: Path) -> None:
    """Ausência de dado não é erro: a tela só não mostra barra."""
    assert ler(tmp_path) is None


def test_publica_fracao_por_trabalho_e_nao_por_contagem(tmp_path: Path) -> None:
    """Custo por documento varia quase 600× — barra por contagem anda aos saltos."""
    e = Estimador()
    e.declarar([("pequeno.docx", 1000), ("enorme.xlsx", 100 * MB)])
    p = Publicador(indice=tmp_path, estimador=e, intervalo=0.0)
    e.registrar("pequeno.docx", 1000, 1.0)
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["documentos"] == {"feitos": 1, "totais": 2}
    assert dados["fracao"] < 0.02, "metade dos documentos, quase nada do trabalho"


def test_publica_restante_em_linguagem_humana(tmp_path: Path) -> None:
    p = publicador(tmp_path)
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert "restante" in dados and "s" not in dados["restante"].split()[0][-1:]
    assert dados["restante_segundos"] > 0
    assert dados["restante_p90_segundos"] >= dados["restante_segundos"]


def test_ativo_e_parado_ficam_separados(tmp_path: Path) -> None:
    """Somar os dois mente sobre a vazão: 40% do run foi máquina dormindo."""
    r = Relogio()
    r.tique(0.0)
    r.tique(30.0)
    r.tique(30.0 + 3600)  # suspensão

    e = Estimador()
    e.declarar([("a.pdf", MB)])
    Publicador(indice=tmp_path, estimador=e, relogio=r, intervalo=0.0).publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["ativo_segundos"] == 30
    assert dados["parado_segundos"] >= 3600
    assert dados["suspensoes"] == 1


def test_intervalo_limita_a_gravacao(tmp_path: Path) -> None:
    """Gravar a cada documento viraria carga de E/S disputando com a indexação."""
    p = publicador(tmp_path)
    p.intervalo = 3600
    p.publicar(forcar=True)
    primeiro = caminho_de(tmp_path).read_text(encoding="utf-8")

    p.estimador.registrar("0.pdf", MB, 1.0)
    p.publicar()  # dentro do intervalo: não deve gravar

    assert caminho_de(tmp_path).read_text(encoding="utf-8") == primeiro


def test_encerrar_deixa_o_arquivo(tmp_path: Path) -> None:
    """Apagar faria "terminou" virar indistinguível de "nunca rodou"."""
    p = publicador(tmp_path)
    p.encerrar("concluida")

    assert ler(tmp_path)["status"] == "concluida"


def test_anotar_acrescenta_o_que_a_tela_mostra(tmp_path: Path) -> None:
    p = publicador(tmp_path)
    p.anotar(base="trabalho", arquivo="Contrato.pdf", perfil="leve")
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["base"] == "trabalho" and dados["arquivo"] == "Contrato.pdf"


def test_anotar_publica_trecho_dentro_do_arquivo(tmp_path: Path) -> None:
    """A barra tem que andar durante o embed, não só entre documentos."""
    p = publicador(tmp_path)
    p.anotar(arquivo="dump.csv", etapa="embed", trecho=1200, trechos=4000)
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["etapa"] == "embed"
    assert dados["trecho"] == 1200
    assert dados["trechos"] == 4000


def test_gravacao_e_atomica(tmp_path: Path) -> None:
    """A barra lê a qualquer momento; JSON truncado mostraria erro no pior momento."""
    p = publicador(tmp_path)
    p.publicar(forcar=True)

    assert not list(tmp_path.glob("*.tmp"))
    json.loads(caminho_de(tmp_path).read_text(encoding="utf-8"))


def test_falha_ao_publicar_nao_derruba_a_indexacao(tmp_path: Path, monkeypatch) -> None:
    """Progresso é conveniência; indexar é o trabalho."""
    p = publicador(tmp_path)

    def explode(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise OSError("disco cheio")

    monkeypatch.setattr(Path, "write_text", explode)
    p.publicar(forcar=True)  # não levanta


def test_json_ilegivel_lido_como_ausencia(tmp_path: Path) -> None:
    (tmp_path / NOME).write_text("{truncado", encoding="utf-8")
    assert ler(tmp_path) is None


# --- esforço ------------------------------------------------------------------


@pytest.mark.parametrize("perfil", PERFIS_DE_ESFORCO)
def test_aplicar_esforco_nunca_levanta(perfil: str) -> None:
    """psutil pode faltar e o sistema pode recusar — nenhum é motivo para não indexar."""
    relato = aplicar(perfil)
    assert relato["perfil"] == perfil


def test_normal_nao_sobe_prioridade() -> None:
    """Normal restringe CPU; não compete em prioridade com o que está na tela."""
    relato = aplicar("normal")
    assert relato["perfil"] == "normal"
    assert relato["prioridade"] is None
    assert relato["cpu_percentual"] == 50


def test_relato_permite_a_tela_dizer_a_verdade() -> None:
    """"Pedi leve e o sistema não deixou" é melhor que mentir que está leve."""
    relato = aplicar("leve")
    assert "prioridade" in relato
    assert relato["prioridade"] == "leve" or "aviso" in relato


def test_na_bateria_responde_ou_admite_que_nao_sabe() -> None:
    assert na_bateria() in (True, False, None)
