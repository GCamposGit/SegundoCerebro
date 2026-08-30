"""Os dublês da suíte de `eval/`. Um lugar, e não um arquivo de teste.

Irmão de `tests/falsos.py`, e pelo mesmo motivo (`Q17`, 30/08/2026):
`RecuperadorFixo` morava em `eval/test_escopo.py` e era importado de lá por
`eval/test_ablacao_f2.py` e `eval/test_idioma.py`. Arquivo de teste usado como
módulo de apoio é um conftest que ninguém declarou —
`tests/test_isolamento_da_suite.py` recusa a forma inteira desde 30/08.

Separado de `tests/falsos.py` de propósito: aquele importa
`segundocerebro.ingest` e o encoder falso do indexador, e `eval/` não indexa.
"""

from __future__ import annotations

from eval.harness import Hit


class RecuperadorFixo:
    """Devolve sempre a mesma lista — o que varia nos testes é o conjunto dourado."""

    nome = "fixo"

    def __init__(self, caminhos: list[str]) -> None:
        self.caminhos = caminhos

    def search(self, consulta: str, k: int) -> list[Hit]:  # noqa: ARG002
        return [Hit(path=p, score=1.0 / (i + 1)) for i, p in enumerate(self.caminhos[:k])]
