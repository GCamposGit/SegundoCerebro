"""Publicação de progresso e nível de esforço.

A arquitetura que estes testes protegem: o indexador publica, o painel lê, e
fechar o painel não para nada.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from segundocerebro.index.esforco import PERFIS_DE_ESFORCO, aplicar, na_bateria
from segundocerebro.index.estimativa import Estimador, Relogio
from segundocerebro.index.progresso import (
    LIMITE_SEM_AVANCO,
    NOME,
    Publicador,
    caminho_de,
    ler,
)

MB = 1_000_000

def _obs(rel, tamanho, segundos):
    """Observação mínima: a v2 registra medição por etapa, não um total solto."""
    from segundocerebro.index.calibracao import tipo_de
    from segundocerebro.index.estimativa import Observacao

    return Observacao(
        rel=rel,
        tipo=tipo_de(rel),
        mb=tamanho / 1_048_576,
        n_chunks=1,
        tokens=120,
        s_embed=segundos * 0.8,
        s_grava=segundos * 0.2,
        s_total_ativo=segundos,
    )




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
    e.registrar(_obs("pequeno.docx", 1000, 1.0))
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["documentos"] == {"feitos": 1, "totais": 2}
    assert dados["fracao"] < 0.02, "metade dos documentos, quase nada do trabalho"


def test_publica_restante_em_linguagem_humana(tmp_path: Path) -> None:
    p = publicador(tmp_path)
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert "restante" in dados and "s" not in dados["restante"].split()[0][-1:]
    # Máquina sem calibragem local: o estado é `cego` e **nenhum tempo** é
    # publicado — número sem base local é mentira (spec §9). O texto diz o que
    # está acontecendo em vez de inventar uma faixa.
    assert dados["estimativa_estado"] == "cego"
    assert dados["restante_segundos"] is None
    assert "medindo" in dados["restante"]
    assert dados["restante_p90_segundos"] is None


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

    p.estimador.registrar(_obs("0.pdf", MB, 1.0))
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


# --- Vigia: indexador parado não pode reportar que está indexando -------------
#
# Medido em 26/08/2026: a thread principal entrou num único `session.run` do
# ONNX com lote de 32 trechos de janela cheia e não voltou. `publicar()` nunca
# foi chamado, o arquivo congelou dizendo `"status": "indexando"` com ETA de 9 h,
# e o processo passou 3 h 22 min sem avançar um documento. O único jeito de
# descobrir era medir a CPU do processo por fora — que é o que ninguém faz.
#
# A classe é essa: **quem publica não pode ser quem trabalha**. Um vigia que
# dependesse da thread travada para bater não seria vigia.


def parado(tmp_path: Path, **kw) -> Publicador:
    e = Estimador()
    e.declarar([(f"{i}.pdf", MB) for i in range(10)])
    return Publicador(indice=tmp_path, estimador=e, intervalo=0.0, **kw)


def test_sem_avanco_zera_quando_documento_anda(tmp_path: Path) -> None:
    p = parado(tmp_path, limite_sem_avanco=0.05)
    p.estimador.registrar(_obs("0.pdf", MB, 1.0))
    assert p.sem_avanco() == 0.0

    time.sleep(0.08)
    assert p.sem_avanco() >= 0.05, "nada mudou: o relógio de parada tem de correr"

    p.estimador.registrar(_obs("1.pdf", MB, 1.0))
    assert p.sem_avanco() == 0.0, "documento novo reabre o crédito"


def test_trecho_dentro_do_arquivo_conta_como_avanco(tmp_path: Path) -> None:
    """PDF de 800 trechos é legítimo e demora — mas o trecho anda.

    Sem isto o vigia chamaria de travado justamente o documento grande que ele
    existe para acompanhar.
    """
    p = parado(tmp_path, limite_sem_avanco=0.05)
    p.anotar(arquivo="enorme.pdf", trecho=32)
    p.sem_avanco()
    time.sleep(0.08)

    p.anotar(trecho=64)

    assert p.sem_avanco() == 0.0


def test_status_troca_para_travada_e_a_estimativa_deixa_de_valer(tmp_path: Path) -> None:
    p = parado(tmp_path, limite_sem_avanco=0.05)
    p.publicar(forcar=True)
    assert ler(tmp_path)["status"] in {"indexando", "travada"}

    time.sleep(0.08)
    p.publicar(forcar=True)

    dados = ler(tmp_path)
    assert dados["status"] == "travada", "indexando com ETA enquanto nada anda é a mentira"
    assert dados["sem_avanco_segundos"] >= 0


def test_vigia_publica_sozinho_com_a_thread_principal_presa(tmp_path: Path) -> None:
    """O teste que vale: ninguém chama `publicar` e o arquivo mesmo assim avisa."""
    p = parado(tmp_path, limite_sem_avanco=0.05, intervalo_vigia=0.02)
    p.publicar(forcar=True)
    antes = ler(tmp_path)["atualizado_em"]
    p.iniciar_vigia()
    try:
        # a thread principal "não volta": só dorme, sem publicar nada
        limite = time.monotonic() + 3.0
        while time.monotonic() < limite:
            dados = ler(tmp_path)
            if dados["status"] == "travada":
                break
            time.sleep(0.05)
    finally:
        p.parar_vigia()

    dados = ler(tmp_path)
    assert dados["status"] == "travada"
    assert dados["atualizado_em"] > antes, "carimbo novo distingue processo parado de processo morto"
    assert dados["sem_avanco_segundos"] >= 0


def test_vigia_nao_sobrevive_ao_encerramento(tmp_path: Path) -> None:
    vivas = threading.active_count()
    p = parado(tmp_path, intervalo_vigia=0.02)
    p.iniciar_vigia()
    p.encerrar("concluida")

    assert threading.active_count() <= vivas
    assert ler(tmp_path)["status"] == "concluida"


def test_vigia_nao_derruba_a_indexacao_quando_a_batida_falha(tmp_path: Path, monkeypatch) -> None:
    """Ele lê estruturas que a thread principal está mutando. Isso pode explodir.

    O que não pode é explodir para cima: progresso é conveniência, indexação é o
    trabalho.
    """
    p = parado(tmp_path, limite_sem_avanco=0.0, intervalo_vigia=0.02)
    monkeypatch.setattr(
        type(p.estimador), "restante", lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    p.iniciar_vigia()
    time.sleep(0.15)
    vivo = p._vigia is not None and p._vigia.is_alive()
    p.parar_vigia()

    assert vivo, "uma batida que falha não pode matar o vigia"


def test_limite_padrao_e_generoso_o_bastante_para_documento_grande() -> None:
    """Dez minutos: PDF de 800 trechos na CPU passa de meia hora, e nele o
    avanço aparece por trecho. O que não é legítimo é *nada* mudar."""
    assert LIMITE_SEM_AVANCO >= 300
