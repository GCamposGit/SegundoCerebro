"""Conversores estritos usados na leitura do TOML.

`bool(valor)` não é um leitor de configuração: texto não vazio e qualquer
inteiro diferente de zero viram ``True``. Na porta de entrada do produto isso
faz um valor inválido parecer uma escolha aceita.
"""

from __future__ import annotations

VERDADEIROS = frozenset({"1", "true", "sim", "yes", "verdadeiro"})
FALSOS = frozenset({"0", "false", "não", "nao", "no", "falso"})


def booleano(
    valor: object,
    chave: str,
    *,
    erro: type[Exception] = ValueError,
) -> bool:
    """Converte apenas representações inequívocas; o restante é erro."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and valor in (0, 1):
        return bool(valor)
    if isinstance(valor, str):
        normalizado = valor.strip().lower()
        if normalizado in VERDADEIROS:
            return True
        if normalizado in FALSOS:
            return False
    aceitos = "true/false, sim/não, yes/no ou 1/0"
    raise erro(f"{chave}={valor!r} não é booleano válido ({aceitos})")
