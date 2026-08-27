"""Registry mapping extension to parser.

A parser takes bytes and a file name and returns a ParsedDoc. It never touches
the filesystem — `reader.py` is the single gatekeeper for that, so the cloud
placeholder check cannot be bypassed by a new format being added here.
"""

from __future__ import annotations

from collections.abc import Callable

from ..document import ParsedDoc

Parser = Callable[[bytes, str], ParsedDoc]

_REGISTRY: dict[str, Parser] = {}
_VERSOES: dict[str, str] = {}

VERSAO_INICIAL = "1"
"""Versão de todo parser que existia antes de a versão ser registrada.

Serve a duas coisas, e é a mesma constante nas duas: é o default de `register`,
e é o que a migração do registro estampa nas linhas de um índice antigo. Se
fossem dois valores diferentes, um índice existente repescaria tudo — 1.608
documentos e 39 h — na primeira passada depois da atualização."""


def register(*extensions: str, version: str = VERSAO_INICIAL) -> Callable[[Parser], Parser]:
    """Registra o parser de uma ou mais extensões, com a **versão** dele.

    A versão existe porque `CHUNKER_VERSION` não cobre parser: um documento
    indexado por um parser que depois foi corrigido passa em tamanho, mtime,
    modelo e chunker, e nada o repesca. Foi o que aconteceu em 21/08/2026 — um
    `.msg` ficou no índice com 343 chunks de token de rastreio, e a única saída
    era script avulso apagando linha do registro à mão.

    Regra ao mexer num parser: **mudou o texto que ele produz, sobe a versão.**
    Refatoração que não muda a saída, não.

    Limite conhecido: a versão é por **extensão**, e a extensão pode mentir. O
    `.pdf` cujo conteúdo é MIME de email (ver `parser_for_familia`) é versionado
    pelo parser de PDF — subir a versão do email não o alcança. Quando for esse
    o caso, subir as duas.
    """

    def decorator(fn: Parser) -> Parser:
        for ext in extensions:
            _REGISTRY[ext.lower()] = fn
            _VERSOES[ext.lower()] = version
        return fn

    return decorator


def parser_for(extension: str) -> Parser | None:
    _load_all()
    return _REGISTRY.get(extension.lower())


def parser_version_for(extension: str) -> str:
    """Versão do parser que interpreta esta extensão.

    Extensão sem parser devolve `VERSAO_INICIAL` em vez de erro: o indexador
    consulta isto **antes** de saber se há parser, e um `sem_parser` já é
    repescado por status (`STATUS_PARA_REPESCAR`), não por versão.
    """
    _load_all()
    return _VERSOES.get(extension.lower(), VERSAO_INICIAL)


FAMILIA_SEM_AMBIGUIDADE: dict[str, str] = {
    "email": ".eml",
    "pdf": ".pdf",
}
"""Família de conteúdo (`natureza.familia_real`) → extensão que a interpreta.

Só entram as famílias que identificam **um** formato. `ooxml` pode ser docx, xlsx
ou pptx; `ole` pode ser doc, xls ou msg. Adivinhar nesses dois erraria calado, que
é o oposto do que o portão de leitura existe para fazer — e nenhum arquivo do
acervo precisa disso hoje: o único caso de extensão mentirosa medido é um `.pdf`
cujo conteúdo é MIME de email."""


def parser_for_familia(familia: str) -> Parser | None:
    """Parser para o conteúdo de fato, quando a extensão mentiu."""
    extensao = FAMILIA_SEM_AMBIGUIDADE.get(familia)
    return parser_for(extensao) if extensao else None


def supported_extensions() -> tuple[str, ...]:
    _load_all()
    return tuple(sorted(_REGISTRY))


_LOADED = False


def _load_all() -> None:
    """Import the parser modules so their @register calls run."""
    global _LOADED
    if _LOADED:
        return
    from . import mail, pdf, sheets, slides, text, vtt, word  # noqa: F401

    _LOADED = True
