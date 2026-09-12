"""`doc_id` público, a URI `sc://` e a regra de preferência entre caminhos.

Três decisões, e as três foram medidas contra o registro corporativo em
30/08/2026 (`docs/plano-pacote-j.md` §3.2 e §3.3):

**1. O id é derivado do conteúdo, não do caminho.** Um acervo real move e
renomeia arquivo o tempo todo; id derivado de caminho quebra o workflow que o
pacote J promete — *"repetível semana após semana com resultado idêntico"*. O id
é o prefixo do `sha256` que o registro já guarda.

**2. Nem todo documento tem id, e isso é dito, não escondido.** Dos 2.156
documentos do acervo, **29 (1,3%) não têm `sha256`** — 27 `sem_parser` e 2
`travado`. O portão de leitura recusa placeholder de nuvem **antes** de abrir,
porque abrir dispara download do SharePoint, e isso é invariante do projeto, não
otimização. Então ou o manifesto admite item sem id, ou o censo baixa o acervo
para hashear. Admitimos o nulo — com motivo legível junto, nunca string vazia:
campo vazio no retorno é o silêncio que este repositório já pagou caro.

**3. "Um conteúdo, N caminhos" é 1 em 10, e o preferido é declarado.** São
**223 de 2.127 paths (10,5%)** byte-idênticos a outro. Até aqui o "principal"
era o primeiro `ok` que o SQLite entregasse — ordem de indexação, que é
aleatoriedade com cara de determinismo. A regra passa a ser a **mesma** de
`retrieve/familias.py::por_vigencia`: número de versão declarado vence, data
desempata, caminho desempata a data. Uma noção de "o principal" no produto
inteiro, não duas.

A URI `sc://<base>/<doc_id>` encosta no invariante 7 (isolamento entre bases é
físico) e por isso `<base>` aqui é **conferência, nunca seletor**: o servidor já
é um processo por base, então uma referência que nomeie outra base é erro, e
nunca um pedido para ir buscar lá.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..retrieve.familias import por_vigencia

TAMANHO_DOC_ID = 12
"""Quantos hex do `sha256` formam o id público.

48 bits. Num acervo de 10^5 documentos a chance de colisão de aniversário fica
na casa de 10^-5, e a colisão aqui não corrompe nada: `caminhos_de_doc_id`
devolve **todos** os caminhos da faixa, então uma colisão vira dois caminhos
listados, que é exatamente o que "um conteúdo, N caminhos" já produz. Curto
porque o id vai em todo separador de citação de um bundle, e o agente paga cada
caractere em contexto.
"""

ESQUEMA_URI = "sc"

_HEX = re.compile(r"^[0-9a-f]+$")
_DOC_ID = re.compile(r"^[0-9a-f]{%d}$" % TAMANHO_DOC_ID)

MOTIVOS_SEM_ID = {
    "sem_parser": "o formato não é lido por esta versão — nada foi aberto, então não há hash",
    "travado": "o arquivo estava em uso ou sem permissão quando a passada tentou abri-lo",
    "so_censo": "está no disco e fora do índice: o censo enumera sem abrir, e hash exige abrir",
    "vazio": "nenhum texto foi extraído do arquivo",
}
MOTIVO_SEM_ID_PADRAO = "este documento não tem hash de conteúdo no registro"


def doc_id_de(sha256: str) -> str | None:
    """`sha256` → id público. `None` quando o registro não tem hash.

    Devolver `None` em vez de `""` é deliberado: o chamador que esquecer de
    tratar recebe um erro de tipo, não um id vazio que viaja até o cliente
    parecendo um id.
    """
    sha = (sha256 or "").strip().lower()
    if len(sha) < TAMANHO_DOC_ID or not _HEX.match(sha):
        return None
    return sha[:TAMANHO_DOC_ID]


def motivo_sem_id(status: str) -> str:
    """Por que este documento não tem id, em português e para o cliente ler."""
    return MOTIVOS_SEM_ID.get((status or "").strip(), MOTIVO_SEM_ID_PADRAO)


def parece_doc_id(texto: str) -> bool:
    return bool(_DOC_ID.match((texto or "").strip().lower()))


def faixa_de_prefixo(doc_id: str) -> tuple[str, str]:
    """`doc_id` → faixa `[inicio, fim)` para a consulta usar o índice.

    O limite superior é o prefixo com `"g"` no fim, e não o prefixo incrementado:
    todo caractere que pode seguir num `sha256` está em `[0-9a-f]`, e todos são
    menores que `"g"`. Sem caso especial para o prefixo `"ffffffffffff"`.

    Faixa em vez de `LIKE 'prefixo%'` porque a otimização de prefixo do `LIKE` no
    SQLite depende de `PRAGMA case_sensitive_like`; faixa não depende de PRAGMA
    nenhum, e uma varredura de tabela aqui é o N+1 deste repositório com outro
    nome.
    """
    prefixo = (doc_id or "").strip().lower()
    return prefixo, prefixo + "g"


def preferido(caminhos: Sequence[str], mtimes: Mapping[str, float]) -> str:
    """Qual dos N caminhos com o mesmo conteúdo é *o* documento.

    Delega a `familias.por_vigencia` de propósito: duas noções de "o principal"
    no mesmo produto é como um agente recebe uma resposta na segunda-feira e
    outra na terça sem nada ter mudado.
    """
    if not caminhos:
        return ""
    return por_vigencia(sorted(caminhos), mtimes)[0]


@dataclass(frozen=True)
class Referencia:
    """O que o cliente pediu, já separado em id, caminho e base."""

    doc_id: str = ""
    caminho: str = ""
    base: str = ""
    root_id: str = ""
    erro: str = ""

    @property
    def valida(self) -> bool:
        return not self.erro and bool(self.doc_id or self.caminho)


def montar_uri(base: str, doc_id: str) -> str:
    return f"{ESQUEMA_URI}://{base}/{doc_id}"


def interpretar(texto: str, root_id: str = "") -> Referencia:
    """Aceita `sc://<base>/<doc_id>`, um `doc_id` nu, ou um caminho relativo.

    A ambiguidade é declarada em vez de adivinhada: um texto de exatamente 12
    caracteres hex é id, e qualquer outra coisa é caminho. Um arquivo chamado
    `deadbeefcafe` sem extensão seria lido como id — é o preço de o id ser curto,
    e o cliente que precise desse caminho passa `./deadbeefcafe`.
    """
    bruto = (texto or "").strip()
    if not bruto:
        return Referencia(erro="referência vazia")

    if bruto.lower().startswith(f"{ESQUEMA_URI}://"):
        resto = bruto[len(ESQUEMA_URI) + 3 :]
        partes = resto.split("/", 1)
        if len(partes) != 2 or not partes[0] or not partes[1]:
            return Referencia(
                erro=f"URI malformada: esperado {ESQUEMA_URI}://<base>/<doc_id>, veio {bruto!r}"
            )
        base, alvo = partes[0], partes[1].strip().lower()
        if not parece_doc_id(alvo):
            return Referencia(
                erro=f"a URI não termina em doc_id de {TAMANHO_DOC_ID} hex: {bruto!r}"
            )
        return Referencia(doc_id=alvo, base=base)

    if parece_doc_id(bruto):
        return Referencia(doc_id=bruto.lower())
    return Referencia(caminho=bruto, root_id=(root_id or "").strip())


def conferir_base(referencia: Referencia, base_do_processo: str) -> str:
    """`""` quando pode seguir; a mensagem de erro quando não pode.

    Invariante 7: isolamento entre bases é **físico** — um diretório de índice e
    um processo por base. Uma tool que aceitasse `<base>` como seletor traria
    "base como filtro de metadado" pela porta dos fundos, e um booleano errado
    vazaria uma base na outra. Aqui o nome só **confere**.
    """
    if not referencia.base:
        return ""
    if not base_do_processo:
        # Achado em revisão: o servidor sobe sem `config.toml` (três valores
        # soltos, `--indice`), e aí não há nome para conferir contra. Aceitar
        # qualquer `<base>` em silêncio é a garantia faltando **exatamente** onde
        # o cliente não sabe em que base está — pior que recusar, porque ele
        # recebe conteúdo de outro acervo achando que pediu certo.
        return (
            f"esta referência nomeia a base '{referencia.base}', e este servidor subiu "
            "sem base declarada — não há nome para conferir contra. Use o caminho do "
            "arquivo ou o doc_id sozinho, ou suba o servidor com --base."
        )
    if referencia.base == base_do_processo:
        return ""
    return (
        f"esta referência é da base '{referencia.base}' e este servidor serve "
        f"'{base_do_processo}'. Cada base é um processo e um índice próprios — "
        "conecte o cliente à base certa; nenhuma tool cruza a fronteira."
    )
