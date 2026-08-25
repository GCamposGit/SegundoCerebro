"""A suíte recusa nome real em arquivo versionado.

O vazamento aconteceu **três vezes em dois dias**, nos dois setups, e sempre da
mesma forma: alguém escreve o nome de um cliente real num exemplo de CLI, num
comentário ou num id de teste, e ninguém vê porque cada ocorrência é uma palavra
solta no meio de um diff grande. A regra já existia no `CLAUDE.md`; o que faltava
era alguém conferindo.

**A lista de nomes não vive aqui.** Um teste que trouxesse os nomes por extenso
seria o próprio vazamento, com a agravante de ficar no arquivo que existe para
impedi-lo. A lista mora em `nomes-proibidos.txt`, na raiz, **fora do Git** — cada
máquina tem a sua, com os nomes que aquele acervo conhece. Sem o arquivo o teste
pula, e é por isso que o CI e um clone novo continuam verdes.

O modelo é o mesmo de `test_baseline.py` com o `census.toml`: o dado real fica
fora, o teste sabe o que fazer quando ele não está.

**E o furo dessa escolha, medido em 25/08/2026.** A lista desta máquina tinha 3
termos e a suíte estava verde — com 8 nomes reais de cliente e fornecedor em 4
arquivos versionados, em fixture de teste, ao lado do vocabulário fictício
correto (`Acme`, `PO-ACME-007`). Eles entraram porque cada um é uma palavra solta
num diff grande, exatamente o modo de falha que este arquivo existe para fechar,
e sobreviveram porque **nenhuma máquina tinha o termo na lista**.

Lista magra não produz suíte incompleta: produz suíte **verde**, que é pior,
porque parece prova. A completude da lista é obrigação de processo e **não** é
propriedade testável — é o preço de ela ficar fora do Git, e o preço é declarado
em `nomes-proibidos.example.txt` em vez de escondido. O que este teste garante é
o outro lado: nenhum termo **que a lista conheça** passa.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LISTA = REPO / "nomes-proibidos.txt"
EXEMPLO = REPO / "nomes-proibidos.example.txt"

SUFIXOS_DE_TEXTO = {
    ".md", ".py", ".toml", ".txt", ".json", ".yml", ".yaml",
    ".cmd", ".ps1", ".sh", ".html", ".css", ".js", ".cfg", ".ini", ".jsonl",
}


def termos() -> list[str]:
    linhas = LISTA.read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in linhas if t.strip() and not t.lstrip().startswith("#")]


def mascarar(termo: str) -> str:
    """`Fulano` -> `F*****`. A mensagem de falha não pode repetir o vazamento."""
    return termo[0] + "*" * (len(termo) - 1) if termo else "?"


def versionados() -> list[Path]:
    saida = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [REPO / nome for nome in saida.split("\0") if nome]


def test_lista_de_exemplo_existe_e_explica_o_formato() -> None:
    """O exemplo é versionado; a lista de verdade, não. Sem ele ninguém adota."""
    assert EXEMPLO.exists(), "nomes-proibidos.example.txt sumiu — o formato deixa de ser descobrível"
    texto = EXEMPLO.read_text(encoding="utf-8")
    assert "#" in texto, "o exemplo precisa mostrar que aceita comentário"


@pytest.mark.skipif(not LISTA.exists(), reason="nomes-proibidos.txt ausente (lista local não configurada)")
def test_nenhum_nome_real_em_arquivo_versionado() -> None:
    alvos = termos()
    if not alvos:
        pytest.skip("nomes-proibidos.txt está vazio")

    padroes = [(t, re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)) for t in alvos]
    achados: list[str] = []

    for caminho in versionados():
        rel = caminho.relative_to(REPO).as_posix()
        # O nome do arquivo vaza tanto quanto o conteúdo.
        for termo, padrao in padroes:
            if padrao.search(rel):
                achados.append(f"{rel}: no próprio nome do arquivo ({mascarar(termo)})")
        if caminho.suffix.lower() not in SUFIXOS_DE_TEXTO or not caminho.exists():
            continue
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, linha in enumerate(linhas, start=1):
            for termo, padrao in padroes:
                if padrao.search(linha):
                    achados.append(f"{rel}:{n} ({mascarar(termo)})")

    assert not achados, (
        "nome real em arquivo versionado — o repositório é compartilhado e o "
        "vocabulário de exemplo é a VCE (docs/colaboracao.md §5):\n  "
        + "\n  ".join(achados)
    )


@pytest.mark.skipif(not LISTA.exists(), reason="nomes-proibidos.txt ausente (lista local não configurada)")
def test_a_propria_lista_nao_esta_versionada() -> None:
    """Guarda contra o erro que este teste tornaria tentador."""
    rel = LISTA.relative_to(REPO).as_posix()
    assert rel not in {p.relative_to(REPO).as_posix() for p in versionados()}, (
        f"{rel} entrou no Git — é o arquivo que existe justamente para não entrar"
    )
