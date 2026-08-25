"""A pasta hostil cobre todo `ParseStatus`, e o checklist é o enum, não uma lista.

Absorve a porta `F6-E`: *a indexação termina, o registro diz por documento o que
aconteceu, e nada entra no índice como se tivesse texto quando não tem*. Falhar é
aceitável; travar ou mentir em silêncio, não.

**O teste confere contra `ingest.document.ParseStatus`.** Status novo sem fixture
reprova aqui, e o autor do status descobre no mesmo dia — que é a diferença entre
uma porta e uma lista de dez itens que alguém escreveu de cabeça.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

import pytest

from segundocerebro.census import Census, Config, RootSpec, caminho_estendido, iter_files
from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.reader import parse_file

from eval.gerador.__main__ import gerar
from eval.gerador.hostil import CORTE_CSV_MB, PASTA

SEM_FIXTURE_POSSIVEL = {
    ParseStatus.GONE: (
        "é a corrida entre enumerar e abrir — o arquivo existia na varredura e "
        "não existe mais no processamento. Uma pasta estática não tem corrida."
    ),
    ParseStatus.DUPLICATE: (
        "mora na fatia `duplicatas`, que espalha os mesmos bytes por três "
        "caminhos. Duplicar aqui seria a mesma fixture em dois lugares."
    ),
    ParseStatus.LOCKED: (
        "exige outro processo segurando o arquivo agora — ver "
        "`test_travado_precisa_de_lock_de_verdade`, que cria um."
    ),
}
"""Os status que **não** saem de um arquivo parado no disco, com o motivo.

A lacuna declarada é a única que não vira dívida. Sem esta tabela o teste
precisaria ou mentir (fingir cobertura) ou ser frouxo (não conferir o enum)."""


@pytest.fixture(scope="module")
def hostil(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destino = tmp_path_factory.mktemp("hostil")
    gerar(42, 4, destino, sem_docx=False)
    return destino / "corpus" / PASTA


def _status_da_pasta(raiz: Path) -> Counter:
    vistos: Counter = Counter()
    for entrada in _enumerar(raiz.parent):
        if PASTA not in entrada:
            continue
        resultado = parse_file(entrada, retries=0, limites_mb={".csv": float(CORTE_CSV_MB)})
        vistos[resultado.status] += 1
    return vistos


def _enumerar(corpus: Path) -> list[str]:
    """Enumera como o **produto** enumera, e não como `pathlib` enumeraria."""
    cfg = Config(roots=(RootSpec(name="hostil", path=corpus),))
    return [a.path for a in iter_files(cfg.roots[0], cfg, Census())]


def test_a_pasta_hostil_cobre_todo_o_ParseStatus(hostil: Path) -> None:
    """O checklist é o enum do produto. Status novo sem fixture reprova aqui."""
    vistos = _status_da_pasta(hostil)
    esperados = set(ParseStatus) - set(SEM_FIXTURE_POSSIVEL)

    faltando = esperados - set(vistos) - {ParseStatus.OK}
    assert not faltando, (
        f"status sem fixture na pasta hostil: {sorted(s.value for s in faltando)}. "
        f"Ou acrescente o arquivo em `eval/gerador/hostil.py`, ou declare a "
        f"impossibilidade em SEM_FIXTURE_POSSIVEL com o motivo — nunca em silêncio."
    )
    assert vistos[ParseStatus.OK] > 0, "sanidade: alguma coisa ali tem de ser legível"


def test_a_declaracao_de_impossibilidade_nao_esconde_status_possivel(hostil: Path) -> None:
    """A tabela de lacunas é para o que não cabe, não para o que dá trabalho.

    Sem esta metade, `SEM_FIXTURE_POSSIVEL` viraria o lugar onde se joga o status
    inconveniente — e o teste de cobertura passaria a provar nada."""
    vistos = _status_da_pasta(hostil)
    indevidos = {s for s in SEM_FIXTURE_POSSIVEL if s in vistos}

    assert not indevidos, (
        f"{sorted(s.value for s in indevidos)} tem fixture e está declarado impossível "
        f"— tirar de SEM_FIXTURE_POSSIVEL"
    )


def test_nada_entra_no_indice_como_se_tivesse_texto(hostil: Path) -> None:
    """O aceite da `F6-E`, literal: status não-`ok` não devolve texto nenhum."""
    for entrada in _enumerar(hostil.parent):
        if PASTA not in entrada:
            continue
        r = parse_file(entrada, retries=0, limites_mb={".csv": float(CORTE_CSV_MB)})
        if r.status is ParseStatus.OK:
            continue
        chars = sum(len(b.text) for b in (r.doc.blocks if r.doc else ()))
        assert chars == 0, f"{os.path.basename(entrada)}: status {r.status.value} com {chars} chars"


def test_o_owner_do_word_e_excluido_antes_de_chegar_ao_parser(hostil: Path) -> None:
    """`~$Contrato.docx` está no disco e **não** é enumerado — e é assim que tem de ser.

    O padrão `~$*` é exclusão técnica padrão do censo (`census.py`). A fixture
    existe para provar que a exclusão funciona: sem ela o arquivo chegaria ao
    parser e viraria `erro`, poluindo o registro com uma falha que não é falha."""
    assert (hostil / "~$Contrato em edicao.docx").exists(), "a fixture sumiu do disco"

    enumerados = [os.path.basename(p) for p in _enumerar(hostil.parent)]
    assert not [n for n in enumerados if n.startswith("~$")], enumerados[:5]


def test_o_caminho_longo_e_enumerado_e_lido(hostil: Path) -> None:
    """504 caracteres. O acervo real tem 34 acima de 260, o maior com 293.

    E o achado que veio junto, em 25/08/2026: **`pathlib.rglob` e `os.walk` perdem
    esse arquivo em silêncio** — devolvem menos arquivos, sem erro. `iter_files` o
    acha porque estende o caminho **a partir da raiz** e o prefixo sobrevive à
    descida. Quem escreve teste sobre o corpus tem de enumerar como o produto
    enumera; foi por isso que `_enumerar` existe aqui em vez de um `rglob`."""
    longos = [p for p in _enumerar(hostil.parent) if len(p) > 260]

    assert longos, "o caminho longo não foi enumerado"
    r = parse_file(longos[0], retries=0)
    assert r.status is ParseStatus.OK, r.status
    assert "CT-LP-001" in "\n".join(b.text for b in r.doc.blocks)


def test_pathlib_perde_caminho_longo_e_por_isso_nao_se_usa_no_corpus(tmp_path: Path) -> None:
    """A armadilha do lado de cá, travada com um caminho que ela mesma constrói.

    Não é defeito do produto — `iter_files` e `read_bytes` já estendem. É defeito
    de **ferramenta de teste**: `pathlib` e `os.walk` devolvem menos arquivos, sem
    erro, e subcontar em silêncio é como a métrica sobe com a regressão.

    A primeira versão deste teste media o corpus da fixture e era **frágil**: sob
    o `tmp_path` do pytest o caminho ficava curto e o `pathlib` acertava, então o
    teste passava ou falhava conforme onde o pytest guardasse os temporários. Aqui
    o caminho é construído para passar de 260 a partir de qualquer base."""
    fundo = tmp_path
    for i in range(4):
        fundo = fundo / ("Arquivo morto " + chr(97 + i) * 80)
    alvo = fundo / "contrato.txt"
    assert len(str(alvo)) > 260, len(str(alvo))

    os.makedirs(caminho_estendido(fundo), exist_ok=True)
    with open(caminho_estendido(alvo), "w", encoding="utf-8") as fh:
        fh.write("CT-LP-999")

    assert not alvo.exists(), "`Path.exists()` deixou de perder caminho longo"
    assert not list(tmp_path.rglob("*.txt")), "`rglob` deixou de perder caminho longo"
    assert os.path.exists(caminho_estendido(alvo)), "com o prefixo, existe"


def test_o_placeholder_de_nuvem_nao_e_lido(hostil: Path) -> None:
    """Ler um placeholder **baixa o arquivo**: o defeito custa banda, não métrica."""
    alvo = hostil / "Apresentacao na nuvem.txt"
    if os.name != "nt":
        pytest.skip("FILE_ATTRIBUTE_OFFLINE só existe no Windows")

    r = parse_file(str(alvo), retries=0)
    assert r.status is ParseStatus.CLOUD_ONLY, r.status


@pytest.mark.skipif(os.name != "nt", reason="lock exclusivo é do Windows")
def test_travado_precisa_de_lock_de_verdade(hostil: Path) -> None:
    """`travado` não sai de arquivo parado — e fingir que sai seria o defeito conhecido.

    `FileLocked` nasce de um `PermissionError` num `open()`, o que exige outro
    handle exclusivo **agora**. Aqui o lock é real: `CreateFileW` com
    `dwShareMode=0`, que é o que o Word faz. Mock de utilitário do sistema não
    prova permissão (`F3.5-D`); vale a mesma regra."""
    import ctypes
    from ctypes import wintypes

    alvo = hostil / "Scan_001.pdf"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(
        caminho_estendido(alvo),
        0x80000000,  # GENERIC_READ
        0,           # dwShareMode = 0 -> ninguém mais abre
        None,
        3,           # OPEN_EXISTING
        0x80,        # FILE_ATTRIBUTE_NORMAL
        None,
    )
    assert handle not in (0, -1, 2**64 - 1), ctypes.get_last_error()
    try:
        r = parse_file(str(alvo), retries=0)
        assert r.status is ParseStatus.LOCKED, (
            f"esperava `travado` com o arquivo aberto em modo exclusivo, veio {r.status.value}"
        )
    finally:
        kernel32.CloseHandle(handle)


def test_o_valor_que_so_existe_como_formula_esta_declarado_fora_de_escopo(tmp_path: Path) -> None:
    """O defeito silencioso do `C7.a`, medido e anotado em vez de escondido.

    Medido em 25/08/2026: uma planilha com `=SUM(1,2)` e sem cache rende **5
    caracteres** — o rótulo, e nada do resultado. O documento indexa como `ok` com
    o conteúdo faltando, que é pior que erro porque não há o que investigar.

    A resposta: **duas** perguntas sobre o mesmo arquivo. O rótulo é mensurável e
    tem de ser achado; o valor é `fora_de_escopo`, que é como o harness registra
    "não é desta fase" sem apagar a pergunta do conjunto."""
    from eval.adaptador_sintetico import adaptar
    from eval.harness import MOTIVOS_FORA_DE_ESCOPO

    gerar(42, 4, tmp_path / "g", sem_docx=True)
    perguntas = adaptar(tmp_path / "g", tmp_path / "p.jsonl")
    hostis = [p for p in perguntas if p.armadilha_fatia == "pasta_hostil"]

    fora = {p.fora_de_escopo for p in hostis if p.fora_de_escopo}
    assert fora == {"ocr", "formula_sem_cache"}, fora
    assert fora <= set(MOTIVOS_FORA_DE_ESCOPO), "motivo fora do catálogo do harness"

    no_escopo = [p for p in hostis if p.no_escopo]
    assert len(no_escopo) == 3, [p.id for p in no_escopo]


def test_o_corpus_hostil_nao_escala_com_n(tmp_path: Path) -> None:
    """Uma armadilha basta. Trinta cópias só encareceriam a passada.

    Fixado em teste porque a tentação é o contrário: toda fatia escala com `n`, e
    alguém vai querer uniformizar."""
    pequeno = gerar(42, 2, tmp_path / "a", sem_docx=True)["stats"]["pasta_hostil"]
    grande = gerar(42, 12, tmp_path / "b", sem_docx=True)["stats"]["pasta_hostil"]

    assert pequeno == grande, (pequeno, grande)


def test_o_gerador_grava_com_caminho_estendido() -> None:
    """A regra do `CLAUDE.md`, conferida no código e não na intenção.

    O gerador não usava o prefixo, e por isso o corpus **não conseguia conter** a
    armadilha de caminho longo: `mkdir` falha em 425 caracteres com `WinError 3`.
    Usar `census.caminho_estendido` e não uma cópia local é deliberado — gerador e
    leitor (`ingest/reader.py`) têm de concordar sobre o que é um caminho."""
    from eval.gerador import escrita

    fonte = Path(escrita.__file__).read_text(encoding="utf-8")
    assert "from segundocerebro.census import caminho_estendido" in fonte
    assert "open(caminho_estendido" in fonte
    assert "os.makedirs(caminho_estendido" in fonte


if sys.platform != "win32":  # pragma: no cover - documentação executável
    pytest.skip("a pasta hostil é sobre modos de falha do Windows", allow_module_level=True)
