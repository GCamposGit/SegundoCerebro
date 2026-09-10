"""Adaptação MCP do empacotador de pasta; erros de execução têm isError=true."""

from __future__ import annotations

from typing import Any

from mcp.types import CallToolResult, ToolAnnotations

from ..acesso.empacote import CHARS_PADRAO, empacotar
from ..acesso.original import ErroLeitura

from .respostas import erro_operacional, sucesso

DESCRICAO = (
    "Empacota uma pasta em um bundle Markdown: primeiro o manifesto, depois os "
    "documentos canônicos inteiros. Use depois de list_folder quando a tarefa for "
    "ler a pasta — 'escreva um relatório sobre o projeto X'. politica=canonicos "
    "(padrão) traz um membro por família de versões; todos traz cada arquivo; "
    "apenas_listados exige ids. budget_chars conta caracteres Unicode do Markdown, "
    "não tokens. Orçamento estourado corta em fronteira de documento, nunca no "
    "meio, e devolve cursor_proximo. estrito=true (opt-in) nunca deixa o Markdown "
    "passar do orçamento: documento maior que a página é encaminhado a "
    "get_document, com id e próximo passo, e o cursor avança. O padrão continua "
    "o de J.d — o primeiro da página pode exceder. Continue até completo=true; "
    "não trate a primeira página como a pasta inteira. Não sintetiza e não ordena "
    "por relevância. Cite o arquivo original."
)


def registrar(servidor, recursos, obter, limites=None) -> None:  # noqa: ANN001
    base = getattr(recursos, "base", None)
    id_da_base = getattr(base, "id", "") or ""
    censo_cfg = base.censo() if callable(getattr(base, "censo", None)) else None
    teto = getattr(limites, "max_chars", None) or 0

    @servidor.tool(description=DESCRICAO, annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False,
    ))
    def pack_folder(
        pasta: str = "",
        budget_chars: int = CHARS_PADRAO,
        cursor: str | None = None,
        politica: str = "canonicos",
        ids: list[str] | None = None,
        recursivo: bool = False,
        estrito: bool = False,
    ) -> CallToolResult:
        """pasta: caminho relativo; budget_chars: teto Unicode; cursor: continuação;
        politica: canonicos|todos|apenas_listados; ids: filtro; recursivo: subpastas;
        estrito: Markdown nunca excede o teto; documento maior vai a get_document."""
        try:
            limite = min(int(budget_chars), teto) if teto else budget_chars
            saida: dict[str, Any] = empacotar(
                recursos.store, pasta, leitor=obter(), budget_chars=limite,
                cursor=cursor, politica=politica, ids=ids, recursivo=bool(recursivo),
                base=id_da_base, censo_cfg=censo_cfg, estrito=estrito,
            )
            return sucesso(saida)
        except ErroLeitura as erro:
            return erro_operacional(str(erro), erro.codigo)
        except OSError:
            return erro_operacional(
                "Original ou cache indisponível. Confira acesso ao disco e às raízes da base.",
                "acesso_indisponivel",
            )

