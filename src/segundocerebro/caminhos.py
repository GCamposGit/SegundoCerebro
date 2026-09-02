"""Forma única para comparar caminhos reais, inclusive durante mkdir no Windows."""

from pathlib import Path

from .census import caminho_normal


def resolver_caminho(caminho: Path) -> Path:
    """Resolve links e normaliza o prefixo longo, sem alterar o alvo.

    Sob mkdir concorrente, Path.resolve pode devolver um pai com prefixo longo
    e a raiz sem ele. is_relative_to recusaria dois caminhos da mesma árvore.
    Reusa a normalização de caminhos Windows que o censo já aplica.
    """
    return Path(caminho_normal(str(caminho.resolve())))
