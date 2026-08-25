"""Testes do gerador sintético (pacote `E1`). Suíte padrão, sem GPU.

A suíte que veio no zip tinha cinco testes e **todos passavam** — porque todos
rodavam com `n ≤ 11`, e o comando do próprio README (`--n-por-fatia 30`) não
terminava. É a lição da `F3.5-D` com outro nome: teste verde contra um caminho
que a máquina não executa.

Por isso o `n` daqui **não é digitado**: sai de `eval.estatistica.N_MINIMO`, que
é o piso que o `E5` exige por fatia. Se o `E5` subir o piso, este teste passa a
rodar no piso novo sem ninguém lembrar de editá-lo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.estatistica import N_MINIMO
from eval.gerador.__main__ import gerar
from eval.gerador.fatias import TETO_DE_SIGLAS, _sigla
from eval.gerador.nucleo import conferir_selo

REPO = Path(__file__).resolve().parent.parent


def test_o_comando_do_readme_termina_no_n_do_e5(tmp_path: Path) -> None:
    """O achado 1 do laudo, em forma de teste — e em subprocesso de propósito.

    Medido em 25/08/2026 com o gerador como veio: `--n-por-fatia 26` terminava,
    **27 e 30 travavam**. O laudo põe a parede em `i = 26`; a medição põe em
    `n = 27`, porque com `n = 26` o índice vai de 0 a 25 e a 26ª chamada ainda
    acha sigla livre. A conclusão do laudo não muda — 30 é o piso do `E5` e era
    inalcançável.

    **Subprocesso com relógio, e não `gerar()` direto**, porque o que se guarda
    aqui é a *terminação*. Um laço infinito em teste no mesmo processo pendura o
    CI inteiro e o modo de falha vira "a suíte não responde", que não diz nada
    sobre a causa. Com `timeout` a falha é uma linha nomeando este teste.
    """
    saida = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "eval.gerador",
            "--seed",
            "42",
            "--n-por-fatia",
            str(N_MINIMO),
            "--out",
            str(tmp_path / "readme"),
            "--sem-docx",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        timeout=180,
        check=False,
    )

    assert saida.returncode == 0, f"o comando do README não terminou: {saida.stderr[-500:]}"
    assert (tmp_path / "readme" / "manifesto.json").exists()


def test_espaco_de_siglas_tem_teto_e_o_teto_levanta_erro() -> None:
    """A generalização, e ela vale mais que o espaço maior.

    O conserto não é "26³ em vez de 26" — é **teto explícito que falha**. Um
    gerador que laça quando o espaço acaba fica verde na suíte pequena e trava no
    `n` de quem consome. Com erro, a próxima fatia que pedir mais do que cabe
    reprova aqui, com a conta na mensagem.
    """
    vistos: set[str] = set()
    siglas = {_sigla(vistos, i) for i in range(1000)}
    assert len(siglas) == 1000, "a tripla tem de ser bijeção sobre o índice"

    with pytest.raises(ValueError, match="nunca lacar"):
        _sigla(set(), TETO_DE_SIGLAS)


def test_determinismo(tmp_path: Path) -> None:
    assert (
        gerar(42, 8, tmp_path / "a", sem_docx=True)["agregado"]
        == gerar(42, 8, tmp_path / "b", sem_docx=True)["agregado"]
    )


def test_seed_diferente_muda_corpus(tmp_path: Path) -> None:
    assert (
        gerar(42, 6, tmp_path / "a", sem_docx=True)["agregado"]
        != gerar(43, 6, tmp_path / "b", sem_docx=True)["agregado"]
    )


def test_o_selo_e_seed_mais_caps_e_a_divergencia_se_nomeia(tmp_path: Path) -> None:
    """Achado 6 do laudo: mesma seed, `caps` diferente, agregado diferente.

    Isso está **certo** — os dois corpora são diferentes de verdade, porque o
    caminho carrega a extensão. O que estava errado era o diagnóstico: o `E3`
    receberia "hash diferente" e nenhuma explicação. Agora `conferir_selo` diz
    `caps` antes de dizer `agregado`, e a ordem é a entrega.
    """
    sem = gerar(42, 6, tmp_path / "sem", sem_docx=True)
    com = dict(sem, caps={"docx": True}, agregado="x" * 64)

    divergencias = conferir_selo(sem, com)
    assert len(divergencias) == 1, divergencias
    assert divergencias[0].startswith("caps:"), "a dimensão do selo vem antes do sintoma"

    assert conferir_selo(sem, sem) == []

    so_agregado = conferir_selo(sem, dict(sem, agregado="b" * 64))
    assert len(so_agregado) == 1 and "o gerador mudou" in so_agregado[0]


def test_gabarito_existe(tmp_path: Path) -> None:
    """Ground truth por construção: toda pergunta aponta para arquivo que existe."""
    gerar(7, N_MINIMO, tmp_path / "c", sem_docx=True)
    linhas = (tmp_path / "c" / "perguntas.sintetico.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(linhas) >= 10 * N_MINIMO, "dez das onze fatias emitem uma pergunta por `n`"
    ids: set[str] = set()
    for linha in linhas:
        p = json.loads(linha)
        assert p["id"] not in ids
        ids.add(p["id"])
        assert p["docs_relevantes"], p["id"]
        for d in p["docs_relevantes"]:
            assert (tmp_path / "c" / "corpus" / d).exists(), f"{p['id']}: {d}"


def test_sem_nomes_reais(tmp_path: Path) -> None:
    """A lista vem de fora do Git — nunca escrita aqui.

    A suíte do zip trazia dez nomes de cliente e fornecedor **por extenso**, num
    arquivo versionado, num repositório público. `tests/test_saneamento.py` existe
    exatamente para isso e a docstring dele já nomeia o anti-padrão: um teste que
    trouxesse os nomes por extenso seria o próprio vazamento, com a agravante de
    ficar no arquivo que existe para impedi-lo.

    Reusar `termos()` também é o que mantém o CI e um clone novo verdes: sem a
    lista local, o teste pula em vez de reprovar.
    """
    from test_saneamento import LISTA, mascarar, termos

    if not LISTA.exists():
        pytest.skip("nomes-proibidos.txt ausente (lista local não configurada)")

    gerar(11, 5, tmp_path / "d", sem_docx=True)
    proibidos = [t for t in termos() if t]
    for f in (tmp_path / "d" / "corpus").rglob("*"):
        if f.suffix in (".txt", ".md", ".csv") and f.is_file():
            texto = f.read_text(encoding="utf-8").lower()
            for termo in proibidos:
                assert termo.lower() not in texto, f"{mascarar(termo)} em {f.name}"


def test_venenosos_presentes(tmp_path: Path) -> None:
    """A fatia sem pergunta nenhuma — mede robustez do indexador, não ranking."""
    gerar(5, 4, tmp_path / "e", sem_docx=True)
    q = tmp_path / "e" / "corpus" / "Quarentena teste"

    assert len(list(q.iterdir())) == 9
    assert (q / "vazio_0.txt").stat().st_size == 0
