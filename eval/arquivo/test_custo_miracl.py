"""Porta de custo do MIRACL — o que a suíte padrão consegue pegar sozinha.

Nada aqui carrega encoder, nada aqui baixa dataset, nada aqui abre GPU. O smoke
real (`--medir`) fica atrás do marker que o C5.a ainda não precisa: a decisão
deste pacote sai da tabela de línguas e da conta da semente, e as duas estão
nesta suíte.
"""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import pytest

from eval.arquivo.custo_miracl import (
    ADOTAR,
    CORPUS_MIRACL,
    DESCARTAR,
    LINGUA_ALVO,
    MOTIVO_CABE,
    MOTIVO_CUSTO,
    MOTIVO_LINGUA,
    N_AMOSTRADO,
    N_COMPLETO,
    PORTA_HORAS,
    SEMENTE_GPU_CHUNKS,
    SEMENTE_GPU_SEGUNDOS,
    avaliar_porta,
    conferir_indexacao,
    decidir_custo,
    horas,
    lingua_no_miracl,
    main,
    medir_throughput,
    passagens_sinteticas,
    render,
    taxa_semente,
)

pytestmark = pytest.mark.arquivo
"""Pacote encerrado: fora da suíte padrão. `py -m pytest -m arquivo` roda."""

FONTE = Path(__file__).resolve().parent / "custo_miracl.py"
DOC = Path(__file__).resolve().parents[2] / "docs" / "custo-miracl.md"


# --- língua, sem download ---------------------------------------------------


def test_miracl_publicado_tem_dezoito_linguas_e_nenhuma_e_portugues() -> None:
    """A porta existe para descobrir isto *antes* de baixar 16 GB.

    Zhang et al., TACL 2023, tabela 2: 16 línguas conhecidas + 2 surpresa
    (alemão, iorubá). Português não está. Se um dia estiver, este teste quebra
    e o C5.a reabre — não um `load_dataset` no meio da indexação."""
    assert len(CORPUS_MIRACL) == 18
    assert "pt" not in CORPUS_MIRACL
    assert LINGUA_ALVO == "pt"
    assert not lingua_no_miracl("pt")
    assert not lingua_no_miracl("PT")
    assert lingua_no_miracl("es")
    assert lingua_no_miracl("yo")


def test_fonte_nao_baixa_dataset() -> None:
    """`load_dataset` no módulo da porta reintroduziria o defeito que ela fecha."""
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    imports = [
        alias.name.split(".")[0]
        for n in ast.walk(arvore)
        if isinstance(n, ast.Import)
        for alias in n.names
    ]
    froms = [
        n.module.split(".")[0]
        for n in ast.walk(arvore)
        if isinstance(n, ast.ImportFrom) and n.module
    ]
    proibidos = {"datasets", "huggingface_hub", "requests"}
    assert proibidos.isdisjoint(imports + froms)
    fonte = FONTE.read_text(encoding="utf-8")
    assert "load_dataset" not in fonte
    assert "snapshot_download" not in fonte


def test_fonte_nao_importa_encoder_no_topo() -> None:
    """Importar o módulo na suíte não pode carregar fastembed nem o indexador."""
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    for n in arvore.body:
        if isinstance(n, ast.ImportFrom) and n.module:
            assert "embeddings" not in n.module
            assert "gpu_pool" not in n.module
            assert n.module != "segundocerebro.index.indexer"


# --- conta e porta ----------------------------------------------------------


def test_semente_de_1m_estoura_a_porta_e_100k_nao() -> None:
    """A aritmética publicada: 7.873 chunks / 637 s, uma 980 Ti, 19/08/2026."""
    taxa = taxa_semente()
    assert taxa == pytest.approx(SEMENTE_GPU_CHUNKS / SEMENTE_GPU_SEGUNDOS)
    assert horas(N_COMPLETO, taxa) > PORTA_HORAS
    assert horas(N_AMOSTRADO, taxa) < PORTA_HORAS
    # O número redondo que o doc cita. Se a semente mudar, o doc tem de mudar.
    assert horas(N_COMPLETO, taxa) == pytest.approx(22.47, abs=0.05)


def test_empate_na_porta_adota_e_um_segundo_acima_descarta() -> None:
    """A regra do dossiê é `>` ~12 h, não `>=`. Empate não pede mais medição."""
    assert decidir_custo(PORTA_HORAS) == ADOTAR
    assert decidir_custo(PORTA_HORAS + 1e-9) == DESCARTAR
    assert decidir_custo(2.2) == ADOTAR


def test_taxa_zero_nao_vira_infinito_silencioso() -> None:
    with pytest.raises(ValueError, match="positiva"):
        horas(1000, 0.0)


def test_lingua_ausente_descarta_antes_do_custo() -> None:
    """Mesmo que 1M caiba numa hora, MIRACL-PT não existe — a porta para aí."""
    porta = avaliar_porta(lingua="pt", taxa=1_000.0, origem_taxa="teste")
    assert porta.sai_da_ablacao
    assert porta.recorte_completo == DESCARTAR
    assert porta.recorte_amostrado == DESCARTAR
    assert porta.motivo_completo == MOTIVO_LINGUA
    assert porta.baixou is False
    assert porta.horas_completo < PORTA_HORAS  # a conta rodou, e caberia


def test_lingua_existente_amostrada_cabe_completo_nao() -> None:
    """sw existe; com a semente, 1M estoura e 100k cabe — o alarme amostrado vive."""
    porta = avaliar_porta(lingua="sw", taxa=taxa_semente(), origem_taxa="teste")
    assert porta.lingua_existe
    assert porta.recorte_completo == DESCARTAR
    assert porta.motivo_completo == MOTIVO_CUSTO
    assert porta.recorte_amostrado == ADOTAR
    assert porta.motivo_amostrado == MOTIVO_CABE
    assert porta.sai_da_ablacao is False


def test_lingua_existente_cara_demais_nos_dois_recortes_sai() -> None:
    porta = avaliar_porta(lingua="en", taxa=0.5, origem_taxa="teste")
    assert porta.sai_da_ablacao
    assert porta.motivo_completo == MOTIVO_CUSTO
    assert porta.motivo_amostrado == MOTIVO_CUSTO


# --- relatório --------------------------------------------------------------


def test_relatorio_nao_mente_sobre_download_nem_sobre_a_lingua() -> None:
    texto = render(avaliar_porta(lingua="pt", taxa=taxa_semente(), origem_taxa="semente"))
    assert "não" in texto.lower()
    assert "`pt`" in texto
    assert "sai da ablação" in texto
    assert "lingua_ausente" in texto
    assert "[[base]]" in texto
    # A vírgula decimal sobrevive: o replace nas linhas da tabela já quebrou isto.
    assert "22,5 h" in texto
    assert "22 5 h" not in texto


def test_relatorio_de_lingua_que_cabe_nao_manda_sair() -> None:
    # 1M @ 100 c/s = 2,8 h — cabe. yo existe no corpus publicado.
    texto = render(avaliar_porta(lingua="yo", taxa=100.0, origem_taxa="teste"))
    assert "MIRACL **não** sai da ablação" in texto
    assert "**MIRACL sai da ablação.**" not in texto


# --- lock e smoke sem encoder ----------------------------------------------


def test_smoke_recusa_indice_em_escrita(tmp_path: Path) -> None:
    (tmp_path / "indexacao.lock").write_text(str(os.getpid()), encoding="utf-8")
    from segundocerebro.index.store import IndiceEmEscrita

    with pytest.raises(IndiceEmEscrita, match="não compete"):
        conferir_indexacao([tmp_path])


def test_smoke_aceita_indice_sem_trava(tmp_path: Path) -> None:
    conferir_indexacao([tmp_path])  # não levanta


def test_passagens_sao_vce_deterministicas_e_distintas() -> None:
    a = passagens_sinteticas(3, seed=42)
    b = passagens_sinteticas(3, seed=42)
    c = passagens_sinteticas(3, seed=7)
    assert a == b
    assert a != c
    assert len(set(a)) == 3
    assert any("Várzea" in p or "VCE" in p or "Lagoa" in p for p in a)


class _EmbedderFalso:
    def __init__(self, atraso: float = 0.01) -> None:
        self.atraso = atraso
        self.chamadas = 0

    def embed_passagens(self, textos, batch_size=32):  # noqa: ANN001, ARG002
        self.chamadas += 1
        time.sleep(self.atraso)
        return [object()] * len(textos)


def test_smoke_descarta_aquecimento_e_devolve_taxa_positiva() -> None:
    embedder = _EmbedderFalso(atraso=0.02)
    taxa = medir_throughput(embedder, n=4, aquecimento=2, batch_size=4)
    assert embedder.chamadas == 2  # aquecimento + medição
    assert taxa > 0


def test_cli_semente_nao_carrega_encoder(capsys: pytest.CaptureFixture[str]) -> None:
    """O caminho padrão é o que pode rodar com a indexação do acervo no fundo."""
    codigo = main(["--lingua", "pt"])
    assert codigo == 0
    saida = capsys.readouterr().out
    assert "sai da ablação" in saida
    assert "não" in saida.lower()


def test_cli_medir_sem_indice_recusa_no_escuro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem config na cwd o smoke não adivinha se a indexação está viva."""
    monkeypatch.chdir(tmp_path)
    assert main(["--medir"]) == 2


def test_cli_medir_com_trava_viva_nao_sobe_encoder(tmp_path: Path) -> None:
    (tmp_path / "indexacao.lock").write_text(str(os.getpid()), encoding="utf-8")
    assert main(["--medir", "--indice", str(tmp_path)]) == 4


# --- o doc publicado --------------------------------------------------------


def test_doc_registra_a_decisao_e_nao_promete_download() -> None:
    """C5.a fecha com número e veredito em docs/custo-miracl.md — não com o dump."""
    assert DOC.is_file(), "docs/custo-miracl.md é o artefato de aceite do C5.a"
    texto = DOC.read_text(encoding="utf-8")
    assert "descart" in texto.lower()
    assert "12" in texto
    assert "pt" in texto.lower()
    assert "não" in texto.lower()
    assert "lingua_ausente" in texto or "língua" in texto.lower()
    # Caminho real de acervo não entra em doc versionado.
    assert "E:\\" not in texto
    assert "OneDrive" not in texto
