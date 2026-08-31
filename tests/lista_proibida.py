"""A lista de nomes reais do acervo, e como falar dela sem repeti-la.

Saiu de `tests/test_saneamento.py` em 30/08/2026 (`Q17`), porque
`tests/test_gerador_sintetico.py` a importava de lá — de dentro de uma função,
e sem o prefixo do pacote. Arquivo de teste que serve de módulo de apoio é a
classe que `test_isolamento_da_suite.py` passou a recusar; a régua não distingue
o caso grande (`test_index.py`, 18 sítios) do caso pequeno.

A lista em si (`nomes-proibidos.txt`) **não é versionada**: ela contém nomes
reais, e o repositório é público. O `.example.txt` ao lado é o que o clone tem.
Sem a lista local, quem confere pula em vez de reprovar — é deliberado, e é o
que mantém o CI e um clone novo verdes.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LISTA = REPO / "nomes-proibidos.txt"
EXEMPLO = REPO / "nomes-proibidos.example.txt"


def termos() -> list[str]:
    linhas = LISTA.read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in linhas if t.strip() and not t.lstrip().startswith("#")]


def mascarar(termo: str) -> str:
    """`Fulano` -> `F*****`. A mensagem de falha não pode repetir o vazamento."""
    return termo[0] + "*" * (len(termo) - 1) if termo else "?"
