"""As ferramentas de acesso integral — mapa, leitura e empacote (`J.c`/`J.d`).

Em arquivo próprio e não em `mcp/server.py`, e o motivo é medido: `construir`
tem 148 linhas e já está em `FUNCOES_ACIMA_DO_TETO` de
`tests/test_tamanho_dos_modulos.py`, cuja tabela **só desce**. Tools com
descriptions que ensinam o padrão de uso não cabem lá — o teste reprova, e é
para isso que ele existe (`docs/plano-pacote-j.md` §3.10).

O que estas acrescentam à superfície é um **modo de consumo**, não mais
recuperação. `search` responde "onde está X" para uma pergunta; estas respondem
"o que existe aqui", "como este documento é por dentro" e "cubra esta pasta"
para um agente que vai ler uma pasta inteira. As descriptions ensinam a
sequência — enumerar, mapear, empacotar ou ler —, que é a mesma disciplina de
description do `R7.2`: quem escolhe a tool é o LLM cliente, e nenhum
classificador roda deste lado.

Invariantes que este arquivo não pode violar, e nenhuma delas é opinião:

- **Nada gera texto** (invariante 2). Estas tools enumeram e mapeiam; não
  resumem, não interpretam, não ordenam por relevância.
- **Cursor explícito sempre.** Toda resposta declara total, o que está mostrando
  e como pedir o resto.
- **A base na URI confere, não seleciona** (invariante 7): o servidor já é um
  processo por base, e uma referência de outra base é erro.
"""

from __future__ import annotations

from threading import Lock

from mcp.types import CallToolResult

from ..acesso import manifesto
from ..acesso.documento import LeitorDocumento
from ..acesso.identidade import conferir_base, interpretar
from ..acesso.original import ErroLeitura
from .documento import registrar as registrar_documento
from .empacote import registrar as registrar_empacote
from .respostas import erro_operacional, sucesso

DESCRICAO_LIST_FOLDER = (
    "Enumera os documentos de uma pasta da base: raiz, id estável quando já há hash, "
    "tipo, data, caracteres indexados e status. Inclui arquivos ainda não indexados "
    "como `so_censo`, sem abrir conteúdo. **Comece por aqui quando a tarefa for ler "
    "uma pasta inteira** — 'escreva um relatório sobre o projeto X', 'resuma esta pasta': "
    "`list_folder` para saber o que existe, `outline` nos maiores para decidir o que vale "
    "ler, `pack_folder` para cobrir a pasta sob orçamento, e `search` para perguntas "
    "pontuais. A ordem é por caminho e nunca por relevância. Devolve `cursor_proximo` "
    "quando há mais. cursor_opaco=true (opt-in) carrega revisão da enumeração: se o "
    "acervo mudar entre páginas, a continuação recusa com cursor_desatualizado — "
    "reinicie sem cursor. O cursor inteiro é legado e não garante snapshot."
)

DESCRICAO_OUTLINE = (
    "Mapa de um documento sem gastar contexto com ele: as seções na ordem do texto, onde "
    "cada uma está (página, slide ou aba) e quantos caracteres ocupa. Use depois de "
    "`list_folder`, para escolher **o que** ler antes de ler, e antes de pedir trechos com "
    "`search` ou `read_note`. Aceita o caminho do arquivo, o `id` devolvido por "
    "`list_folder` ou uma URI `sc://`."
)


def _referencia(documento: str, id_da_base: str):  # noqa: ANN202
    referencia = interpretar(documento)
    if referencia.erro:
        return None, {"erro": referencia.erro, "codigo": "referencia_invalida", "secoes": []}
    divergencia = conferir_base(referencia, id_da_base)
    if divergencia:
        return None, {"erro": divergencia, "codigo": "base_divergente", "secoes": []}
    return referencia, None


def registrar(servidor, recursos, limites=None) -> None:  # noqa: ANN001
    caixa: dict[str, LeitorDocumento | None] = {"leitor": None}
    trava = Lock()

    def obter() -> LeitorDocumento:
        if caixa["leitor"] is None:
            with trava:
                if caixa["leitor"] is None:
                    caixa["leitor"] = LeitorDocumento(
                        recursos.store, getattr(recursos, "base", None),
                    )
        assert caixa["leitor"] is not None
        return caixa["leitor"]

    registrar_documento(servidor, recursos, obter)
    registrar_empacote(servidor, recursos, obter, limites)
    _registrar_list_folder(servidor, recursos, limites)
    _registrar_outline(servidor, recursos)


def _registrar_list_folder(servidor, recursos, limites=None) -> None:  # noqa: ANN001
    """Acrescenta list_folder ao servidor MCP."""
    base = getattr(recursos, "base", None)
    id_da_base = getattr(base, "id", "") or ""
    censo_cfg = base.censo() if callable(getattr(base, "censo", None)) else None
    max_itens_teto = getattr(limites, "max_itens", None) or manifesto.LIMITE_ITENS_MAX

    @servidor.tool(description=DESCRICAO_LIST_FOLDER)
    def list_folder(
        pasta: str = "",
        recursivo: bool = False,
        cursor: int | str = 0,
        max_itens: int = manifesto.LIMITE_ITENS,
        cursor_opaco: bool = False,
    ) -> CallToolResult:
        """Args:
        pasta: caminho relativo à raiz da base, como aparece no campo `arquivo` de
            `search`. Vazio lista a raiz.
        recursivo: incluir as subpastas.
        cursor: de onde continuar, vindo de `cursor_proximo`. Inteiro é legado.
        max_itens: quantos documentos devolver por página.
        cursor_opaco: continuação com revisão; recusa se a pasta mudou.
        """
        limite = max(1, min(int(max_itens), max_itens_teto))
        try:
            res = manifesto.manifesto(
                recursos.store,
                pasta,
                recursivo=bool(recursivo),
                cursor=cursor,
                limite=limite,
                base=id_da_base,
                censo_cfg=censo_cfg,
                cursor_opaco=cursor_opaco,
            )
            return sucesso(res)
        except ErroLeitura as erro:
            return erro_operacional(str(erro), erro.codigo)


def _registrar_outline(servidor, recursos) -> None:  # noqa: ANN001
    """Acrescenta outline ao servidor MCP."""
    base = getattr(recursos, "base", None)
    id_da_base = getattr(base, "id", "") or ""

    @servidor.tool(description=DESCRICAO_OUTLINE)
    def outline(
        documento: str,
        cursor: int = 0,
        max_secoes: int = manifesto.LIMITE_SECOES,
    ) -> CallToolResult:
        """Args:
        documento: caminho, `id` de `list_folder`, ou URI `sc://<base>/<id>`.
        cursor: de onde continuar, vindo de `cursor_proximo`.
        max_secoes: quantas seções devolver por página.
        """
        referencia, recusa = _referencia(documento, id_da_base)
        if recusa is not None:
            return erro_operacional(recusa["erro"], recusa.get("codigo", "referencia_invalida"), {"secoes": []})

        try:
            limite = max(1, min(int(max_secoes), manifesto.LIMITE_SECOES_MAX))
            cursor_n = int(cursor or 0)
        except (TypeError, ValueError) as exc:
            return erro_operacional(str(exc), "parametro_invalido", {"secoes": []})
        try:
            res = manifesto.mapa(
                recursos.store,
                referencia,
                cursor=cursor_n,
                limite=limite,
                base=id_da_base,
            )
        except ErroLeitura as erro:
            return erro_operacional(str(erro), erro.codigo, {"secoes": []})
        if "erro" in res:
            return erro_operacional(res["erro"], "documento_nao_encontrado", res)
        return sucesso(res)

