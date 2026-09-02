"""As ferramentas de acesso integral — `list_folder` e `outline` (`J.c-mapa`).

Em arquivo próprio e não em `mcp/server.py`, e o motivo é medido: `construir`
tem 148 linhas e já está em `FUNCOES_ACIMA_DO_TETO` de
`tests/test_tamanho_dos_modulos.py`, cuja tabela **só desce**. Quatro tools com
descriptions que ensinam o padrão de uso não cabem lá — o teste reprova, e é
para isso que ele existe (`docs/plano-pacote-j.md` §3.10).

O que estas duas acrescentam à superfície é um **modo de consumo**, não mais
recuperação. `search` responde "onde está X" para uma pergunta; estas respondem
"o que existe aqui" e "como este documento é por dentro" para um agente que vai
ler uma pasta inteira. As descriptions ensinam a sequência — enumerar, mapear,
então ler —, que é a mesma disciplina de description do `R7.2`: quem escolhe a
tool é o LLM cliente, e nenhum classificador roda deste lado.

Invariantes que este arquivo não pode violar, e nenhuma delas é opinião:

- **Nada gera texto** (invariante 2). Estas tools enumeram e mapeiam; não
  resumem, não interpretam, não ordenam por relevância.
- **Cursor explícito sempre.** Toda resposta declara total, o que está mostrando
  e como pedir o resto.
- **A base na URI confere, não seleciona** (invariante 7): o servidor já é um
  processo por base, e uma referência de outra base é erro.
"""

from __future__ import annotations

from typing import Any

from ..acesso import manifesto
from ..acesso.identidade import conferir_base, interpretar

DESCRICAO_LIST_FOLDER = (
    "Enumera os documentos de uma pasta da base: raiz, id estável quando já há hash, "
    "tipo, data, caracteres indexados e status. Inclui arquivos ainda não indexados "
    "como `so_censo`, sem abrir conteúdo. **Comece por aqui quando a tarefa for ler "
    "uma pasta inteira** — 'escreva um relatório sobre o projeto X', 'resuma esta pasta': "
    "`list_folder` para saber o que existe, `outline` nos maiores para decidir o que vale "
    "ler, e `search` para perguntas pontuais. A ordem é por caminho e nunca por "
    "relevância. Devolve `cursor_proximo` quando há mais. Se o acervo mudar entre "
    "páginas, reinicie com cursor=0."
)

DESCRICAO_OUTLINE = (
    "Mapa de um documento sem gastar contexto com ele: as seções na ordem do texto, onde "
    "cada uma está (página, slide ou aba) e quantos caracteres ocupa. Use depois de "
    "`list_folder`, para escolher **o que** ler antes de ler, e antes de pedir trechos com "
    "`search` ou `read_note`. Aceita o caminho do arquivo, o `id` devolvido por "
    "`list_folder` ou uma URI `sc://`."
)


def _referencia(documento: str, id_da_base: str):  # noqa: ANN202
    """A referência pedida, ou a recusa pronta para devolver ao cliente.

    Fora de `registrar` porque a conferência de base é regra de arquitetura
    (invariante 7) e não detalhe de uma tool: a próxima ferramenta que aceitar
    `sc://` chama a mesma função em vez de reimplementar a conferência — que é
    como "duas guardas para a mesma coisa em dois ramos" nasce neste repositório.
    """
    referencia = interpretar(documento)
    if referencia.erro:
        return None, {"erro": referencia.erro, "secoes": []}
    divergencia = conferir_base(referencia, id_da_base)
    if divergencia:
        return None, {"erro": divergencia, "secoes": []}
    return referencia, None


def registrar(servidor, recursos, limites=None) -> None:  # noqa: ANN001
    """Acrescenta as tools de mapa ao servidor já construído.

    Recebe o servidor em vez de devolver um: a superfície MCP é uma só, e um
    segundo servidor para as tools novas seria duas superfícies para a mesma
    base — a anti-recomendação 5 do pacote J aplicada ao transporte.
    """
    base = getattr(recursos, "base", None)
    id_da_base = getattr(base, "id", "") or ""
    censo_cfg = base.censo() if callable(getattr(base, "censo", None)) else None
    max_itens_teto = getattr(limites, "max_itens", None) or manifesto.LIMITE_ITENS_MAX

    @servidor.tool(description=DESCRICAO_LIST_FOLDER)
    def list_folder(
        pasta: str = "",
        recursivo: bool = False,
        cursor: int = 0,
        max_itens: int = manifesto.LIMITE_ITENS,
    ) -> dict[str, Any]:
        """Args:
        pasta: caminho relativo à raiz da base, como aparece no campo `arquivo` de
            `search`. Vazio lista a raiz.
        recursivo: incluir as subpastas.
        cursor: de onde continuar, vindo de `cursor_proximo`.
        max_itens: quantos documentos devolver por página.
        """
        limite = max(1, min(int(max_itens), max_itens_teto))
        return manifesto.manifesto(
            recursos.store,
            pasta,
            recursivo=bool(recursivo),
            cursor=int(cursor or 0),
            limite=limite,
            base=id_da_base,
            censo_cfg=censo_cfg,
        )

    @servidor.tool(description=DESCRICAO_OUTLINE)
    def outline(
        documento: str,
        cursor: int = 0,
        max_secoes: int = manifesto.LIMITE_SECOES,
    ) -> dict[str, Any]:
        """Args:
        documento: caminho, `id` de `list_folder`, ou URI `sc://<base>/<id>`.
        cursor: de onde continuar, vindo de `cursor_proximo`.
        max_secoes: quantas seções devolver por página.
        """
        referencia, recusa = _referencia(documento, id_da_base)
        if recusa is not None:
            return recusa

        limite = max(1, min(int(max_secoes), manifesto.LIMITE_SECOES_MAX))
        return manifesto.mapa(
            recursos.store,
            referencia,
            cursor=int(cursor or 0),
            limite=limite,
            base=id_da_base,
        )
