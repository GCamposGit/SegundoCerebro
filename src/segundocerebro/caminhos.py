"""Forma única para comparar caminhos reais, inclusive durante mkdir no Windows."""

from pathlib import Path, PureWindowsPath

from .census import caminho_normal


def caminho_ja_absoluto(caminho: Path) -> bool:
    """Drive e UNC do Windows continuam absolutos no pytest do Ubuntu.

    `Path.is_absolute` no POSIX não vê `C:\\...` nem `\\\\servidor\\pasta`.
    Sem isto o leitor cola a raiz debaixo do `config.toml`.
    """
    if caminho.is_absolute():
        return True
    return PureWindowsPath(str(caminho)).is_absolute()


def resolver_caminho(caminho: Path) -> Path:
    """Resolve links e normaliza o prefixo longo, sem alterar o alvo.

    Sob mkdir concorrente, Path.resolve pode devolver um pai com prefixo longo
    e a raiz sem ele. is_relative_to recusaria dois caminhos da mesma árvore.
    Reusa a normalização de caminhos Windows que o censo já aplica.
    """
    return Path(caminho_normal(str(caminho.resolve())))
