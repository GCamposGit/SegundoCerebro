"""A representação canônica de um documento — Markdown legível e blocos com offset.

`J.a`/`J.b2`. Um documento parseado hoje existe só em memória, como
`ParsedDoc` + `Block`, e morre no fim da passada: o que sobra no disco são os
chunks, que **se sobrepõem** em 200 caracteres e por isso não reconstroem o
texto. Medido em 30/08/2026: um bloco de 14.399 caracteres vira 9 chunks que
somam 15.999 — **+11,1%** de texto duplicado, em 8 emendas
(`docs/plano-pacote-j.md` §3.4).

Este módulo produz as duas faces da representação canônica **numa passada só**:

- o **Markdown**, que é o que humano e agente leem;
- os **blocos**, que são a estrutura, cada um com `inicio` e `fim` **no
  Markdown**.

Um deriva do outro por construção, e é isso que a especificação exige ao proibir
"manter os dois por caminhos independentes": duas funções que hoje concordam
divergem no primeiro parser corrigido, e a divergência é silenciosa — o offset
aponta para o meio de outra frase e a citação sai errada sem erro nenhum.

**O invariante que fecha a classe:** `markdown[b.inicio:b.fim] == b.texto` para
todo bloco, sempre. É property test, não inspeção.

**Determinismo.** Dado o mesmo `ParsedDoc`, a saída é byte-idêntica: não há
timestamp, não há caminho absoluto, não há ordenação dependente de dicionário —
o `meta` é serializado em ordem de chave. O que **não** é determinístico é o
`ParsedDoc` de três rotas do produto (LibreOffice, OCR, recálculo de planilha),
e isso é tratado na chave do store, não aqui.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .document import Block, ParsedDoc

NIVEL_MAXIMO = 6
"""Markdown não tem `#######`. Trilha mais profunda que isso repete o nível 6.

Acontece de verdade: planilha com aba, tabela e cabeçalho de coluna aninhados
passa de seis. Truncar o nível é preferível a emitir sintaxe que nenhum leitor
entende — e a trilha completa continua no bloco, que é a estrutura.
"""

SEPARADOR = "\n\n"
"""Entre blocos, e entre um heading e o que vem depois dele.

Dois caracteres, sempre os mesmos, porque o offset de todo bloco depende deste
comprimento. Mudar isto invalida o store inteiro — e é por isso que ele é parte
da chave, via `VERSAO_CANONICA`.
"""

VERSAO_CANONICA = "canonico:1"
"""A versão desta renderização. Entra na chave do store.

Sem ela, melhorar a renderização deixaria o cache servindo o Markdown velho para
sempre, com a mesma assinatura — que é o modo de falha que o `plano-pacote-j`
§3.6 nomeia como o mais caro do pacote, porque o sintoma é conteúdo desatualizado
servido com confiança.
"""


@dataclass(frozen=True)
class BlocoCanonico:
    """Um bloco, e onde ele está **no Markdown** — não no arquivo original."""

    trilha: tuple[str, ...]
    inicio: int
    fim: int
    kind: str = "texto"
    locator: str = ""
    """Página, slide ou aba de origem: `"p. 12"`, `"slide 4"`, `"Orçamento!A1:F40"`.

    Vive no bloco e **não** no Markdown de propósito: o Markdown é o que se lê, e
    "p. 12" no meio do texto é ruído para o leitor e para o embedding. Quem cita
    lê o bloco.
    """

    @property
    def chars(self) -> int:
        return self.fim - self.inicio


@dataclass(frozen=True)
class ParseCanonico:
    """O que todos os consumidores enxergam: um Markdown e a estrutura dele."""

    markdown: str
    blocos: tuple[BlocoCanonico, ...] = ()
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def chars(self) -> int:
        return len(self.markdown)

    def texto_de(self, bloco: BlocoCanonico) -> str:
        return self.markdown[bloco.inicio : bloco.fim]


def _comum(a: Sequence[str], b: Sequence[str]) -> int:
    """Quantos níveis de heading os dois blocos já compartilham."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def renderizar(doc: ParsedDoc) -> ParseCanonico:
    """`ParsedDoc` → Markdown + blocos com offset, numa passada e determinístico.

    Os headings são emitidos **por diferença**: só o que muda em relação ao bloco
    anterior. Reemitir a trilha inteira a cada bloco produziria um Markdown que
    ninguém lê e infla o artefato em documento com trilha profunda — planilha com
    aba e tabela chega a cinco níveis por bloco.
    """
    partes: list[str] = []
    blocos: list[BlocoCanonico] = []
    posicao = 0
    anterior: tuple[str, ...] = ()

    for bloco in doc.blocks:
        compartilhados = _comum(anterior, bloco.heading_path)
        for indice in range(compartilhados, len(bloco.heading_path)):
            nivel = min(indice + 1, NIVEL_MAXIMO)
            cabecalho = f"{'#' * nivel} {bloco.heading_path[indice]}{SEPARADOR}"
            partes.append(cabecalho)
            posicao += len(cabecalho)
        anterior = bloco.heading_path

        inicio = posicao
        partes.append(bloco.text)
        posicao += len(bloco.text)
        blocos.append(
            BlocoCanonico(
                trilha=bloco.heading_path,
                inicio=inicio,
                fim=posicao,
                kind=bloco.kind.value if hasattr(bloco.kind, "value") else str(bloco.kind),
                locator=bloco.locator,
            )
        )
        partes.append(SEPARADOR)
        posicao += len(SEPARADOR)

    return ParseCanonico(
        markdown="".join(partes),
        blocos=tuple(blocos),
        meta={str(k): str(v) for k, v in sorted(doc.meta.items())},
    )


def reconstruir(canonico: ParseCanonico) -> tuple[Block, ...]:
    """Volta dos offsets para os blocos de texto — a metade que prova a outra.

    Existe para o property test do `J.b2` poder afirmar sobre o produto em vez de
    reimplementar a renderização dentro do teste. Prova que copia a guarda prova
    a cópia: três provas desta base já tinham a **mesma cegueira** da guarda que
    conferiam, porque as duas saíram da mesma cabeça no mesmo dia.
    """
    from .document import BlockKind

    saida = []
    for b in canonico.blocos:
        try:
            kind = BlockKind(b.kind)
        except ValueError:
            kind = BlockKind.TEXT
        saida.append(
            Block(
                heading_path=tuple(b.trilha),
                text=canonico.texto_de(b),
                locator=b.locator,
                kind=kind,
            )
        )
    return tuple(saida)
