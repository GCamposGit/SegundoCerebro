"""O manifesto de uma pasta e o mapa de um documento — `J.c-mapa`.

As duas respostas que faltavam para o segundo modo de consumo. `search` responde
*onde está*; estas respondem **o que existe** e **como ele é por dentro**, que é
o que transforma "ler 50 arquivos" em plano viável para um agente com orçamento
de contexto.

Nenhuma das duas lê um byte do acervo nem roda parser: `list_folder` sai de
`documentos` + `quarentena`, `outline` sai de `chunks.trilha` + `locator` +
`ordinal`. Foi essa medição que deixou o `J.c-mapa` entrar sem esperar o parse
store (`docs/plano-pacote-j.md` §3.5).

**Cursor explícito sempre.** Toda resposta daqui declara o total, o que está
sendo mostrado e como pedir o resto. É a lição da truncagem silenciosa aplicada
a uma superfície **antes** do primeiro defeito: a tool que faz o agente acreditar
que viu tudo é o modo de falha clássico de ferramenta para agente, e ele não
aparece como erro — aparece como resposta confiante e incompleta.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..index.store import Store
from ..retrieve.familias import chave_de_familia, por_vigencia
from . import registro
from .identidade import Referencia, montar_uri

LIMITE_ITENS = 100
LIMITE_ITENS_MAX = 500
LIMITE_SECOES = 80
LIMITE_SECOES_MAX = 400

STATUS_LEGIVEL = {
    "ok": "indexado",
    "vazio": "sem_texto",
    "erro": "erro",
    "sem_parser": "formato_nao_lido",
    "travado": "sem_acesso",
}
"""O status do registro, com o nome que o cliente entende.

`vazio` vira `sem_texto` porque "vazio" descreve o resultado do parse e o cliente
lê como "o arquivo está vazio" — que é outra coisa, e é a diferença entre um PDF
digitalizado esperando OCR e uma página em branco.
"""


@dataclass(frozen=True)
class Pagina:
    """Uma fatia de uma lista, com o que falta dito na cara."""

    itens: tuple[Any, ...]
    inicio: int
    total: int

    @property
    def fim(self) -> int:
        return self.inicio + len(self.itens)

    @property
    def restante(self) -> int:
        return max(0, self.total - self.fim)

    @property
    def cursor_proximo(self) -> int | None:
        return self.fim if self.restante else None

    def envelope(self) -> dict[str, Any]:
        """Os campos de continuação, iguais em toda tool que devolve lista."""
        saida: dict[str, Any] = {
            "total": self.total,
            "mostrando": f"{self.inicio + 1}-{self.fim} de {self.total}" if self.total else "0 de 0",
        }
        if self.cursor_proximo is not None:
            saida["cursor_proximo"] = self.cursor_proximo
            saida["restante"] = self.restante
        return saida


def paginar(itens: Sequence[Any], cursor: int, limite: int) -> Pagina:
    inicio = max(0, int(cursor or 0))
    return Pagina(itens=tuple(itens[inicio : inicio + limite]), inicio=inicio, total=len(itens))


def _data(mtime: float) -> str:
    if not mtime:
        return ""
    return datetime.fromtimestamp(mtime, tz=timezone.utc).date().isoformat()


def _tipo(caminho: str) -> str:
    nome = caminho.rsplit("/", 1)[-1]
    return "." + nome.rsplit(".", 1)[-1].lower() if "." in nome else ""


def _vigentes(caminhos: Sequence[str], mtimes: dict[str, float]) -> set[str]:
    """Um representante por família de versões, pela regra de `familias.py`.

    É o mesmo conceito de canônico que o `pack_folder` (`J.d`) vai consumir, e
    por isso ele sai daqui e não de uma segunda regra: `politica='canonicos'`
    tem de significar no manifesto o que significa no bundle.
    """
    por_familia: dict[str, list[str]] = {}
    for caminho in caminhos:
        por_familia.setdefault(chave_de_familia(caminho), []).append(caminho)
    return {por_vigencia(sorted(membros), mtimes)[0] for membros in por_familia.values()}


def _item(
    doc: registro.Documento,
    *,
    base: str,
    chars: int,
    trechos: int,
    vigente: bool,
    quarentena: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "arquivo": doc.caminho,
        "tipo": _tipo(doc.caminho),
        "status": "quarentena" if quarentena else STATUS_LEGIVEL.get(doc.status, doc.status),
        "modificado": _data(doc.mtime),
        "bytes": doc.tamanho,
        "chars": chars,
        "trechos": trechos,
        "vigente": vigente,
    }
    if doc.doc_id:
        item["id"] = doc.doc_id
        if base:
            item["uri"] = montar_uri(base, doc.doc_id)
    else:
        item["sem_id"] = doc.sem_id
    if doc.paginas:
        item["paginas"] = doc.paginas
    if doc.digitalizado:
        item["digitalizado"] = True
    if quarentena:
        item["motivo"] = quarentena
    if doc.duplicado:
        item["mesmo_conteudo_em"] = [c for c in doc.caminhos if c != doc.caminho]
    return item


def manifesto(
    store: Store,
    pasta: str,
    *,
    recursivo: bool = False,
    cursor: int = 0,
    limite: int = LIMITE_ITENS,
    base: str = "",
) -> dict[str, Any]:
    """O que existe nesta pasta, em ordem de caminho e com o que falta declarado."""
    documentos = registro.documentos_da_pasta(store, pasta, recursivo=recursivo)
    quarentena = registro.quarentena_da_pasta(store, pasta, recursivo=recursivo)

    pagina = paginar(documentos, cursor, limite)
    caminhos = [d.caminho for d in pagina.itens]
    tamanhos = registro.texto_por_documento(store, caminhos)
    mtimes = {d.caminho: d.mtime for d in documentos}
    vigentes = _vigentes([d.caminho for d in documentos], mtimes)

    itens = [
        _item(
            doc,
            base=base,
            chars=tamanhos.get(doc.caminho, (0, 0))[0],
            trechos=tamanhos.get(doc.caminho, (0, 0))[1],
            vigente=doc.caminho in vigentes,
            quarentena=quarentena.get(doc.caminho, ""),
        )
        for doc in pagina.itens
    ]

    saida: dict[str, Any] = {
        "pasta": registro.normalizar_prefixo(pasta).rstrip("/") or "(raiz da base)",
        "recursivo": recursivo,
        **pagina.envelope(),
        "itens": itens,
    }
    if not documentos:
        saida["aviso"] = (
            "nenhum documento do índice sob esta pasta. Confira o caminho como ele aparece "
            "no campo `arquivo` de `search` — o manifesto usa o caminho relativo à raiz da "
            "base, não o caminho absoluto da máquina."
        )
    saida["fronteira"] = (
        "este manifesto lista o que o índice conhece. Arquivo que a indexação ainda não "
        "alcançou não aparece aqui, e documento em quarentena aparece com status e motivo."
    )
    return saida


def _cabecalho(
    doc: registro.Documento, secoes: Sequence[registro.Secao], base: str
) -> dict[str, Any]:
    """A identidade do documento no topo do mapa, com o que falta dito na cara."""
    cabecalho: dict[str, Any] = {
        "arquivo": doc.caminho,
        "tipo": _tipo(doc.caminho),
        "status": STATUS_LEGIVEL.get(doc.status, doc.status),
        "modificado": _data(doc.mtime),
        "chars": sum(s.chars for s in secoes),
        "trechos": sum(s.trechos for s in secoes),
    }
    if doc.doc_id:
        cabecalho["id"] = doc.doc_id
        if base:
            cabecalho["uri"] = montar_uri(base, doc.doc_id)
    else:
        cabecalho["sem_id"] = doc.sem_id
    if doc.paginas:
        cabecalho["paginas"] = doc.paginas
    if doc.duplicado:
        cabecalho["mesmo_conteudo_em"] = [c for c in doc.caminhos if c != doc.caminho]
    return cabecalho


def mapa(
    store: Store,
    referencia: Referencia,
    *,
    cursor: int = 0,
    limite: int = LIMITE_SECOES,
    base: str = "",
) -> dict[str, Any]:
    """A estrutura de um documento: por onde ler antes de gastar contexto lendo."""
    doc = registro.resolver(store, referencia)
    if doc is None:
        pedido = referencia.doc_id or referencia.caminho
        return {
            "erro": f"documento não encontrado no índice desta base: {pedido}",
            "secoes": [],
            "dica": (
                "use o campo `arquivo` de `search` ou o `id` de `list_folder`. "
                "Um documento fora do índice não tem mapa."
            ),
        }

    secoes = registro.estrutura_de(store, doc.caminho)
    pagina = paginar(secoes, cursor, limite)
    cabecalho = _cabecalho(doc, secoes, base)

    saida: dict[str, Any] = {
        "documento": cabecalho,
        **pagina.envelope(),
        "secoes": [
            {
                "secao": s.trilha or "(sem título)",
                "onde": s.onde,
                "chars": s.chars,
                "trechos": s.trechos,
                "id": s.primeiro_id,
            }
            for s in pagina.itens
        ],
    }
    if not secoes:
        saida["aviso"] = (
            f"este documento está no registro com status '{cabecalho['status']}' e não tem "
            "trecho indexado — não há estrutura para mapear."
        )
    return saida
