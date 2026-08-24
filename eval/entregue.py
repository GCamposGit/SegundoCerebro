"""O caminho que o cliente MCP recebe, medido — `buscar_chunks`, não `search`.

    py -m eval.rodar --retriever hibrido --entregue --out docs/metricas-entregue.md

**O que isto existe para consertar.** A ferramenta `search` do servidor MCP chama
`BuscaHibrida.buscar_chunks` (`mcp/server.py:191`), que funde **denso e lexical**
no nível de trecho. O harness sempre mediu `BuscaHibrida.search`, que funde no
nível de **documento** e é o único lugar onde o `RanqueadorDeNome` participa —
ele pontua documentos, e não há posição de chunk honesta para dar a ele.

A consequência, verificada no índice real em 24/08/2026 com três consultas: mudar
`peso_nome` de 0,5 para 0 **não altera nada** em `buscar_chunks`, e altera a ordem
em `search` em todas. Ou seja, **em produção o peso do nome é inerte**, diga o que
disser a configuração — e todo número que o projeto tem sobre esse peso (a
varredura de 13/08 que escolheu 0,5, `docs/dourado-cobertura.md`, a varredura do
`C3.a`) descreve um caminho de código que o cliente não executa.

O projeto já tinha declarado o princípio contrário, para famílias de versão, em
`docs/ablacao-familias.md`: *"ligado em `search` **e** em `buscar_chunks`, para o
que se mede ser o que se entrega — ligar só no primeiro seria medir uma coisa e
entregar outra."* Para o ranqueador de nome isso não foi feito, e ninguém reparou
porque os dois caminhos medem **parecido**.

**Aditivo, nunca substituto.** `search` continua sendo a série histórica: toda a
comparação F0 → F4 foi feita nele, e trocar o recuperador canônico do harness
apagaria a comparabilidade entre fases, que é a razão de este harness existir
antes de qualquer otimização. Este módulo acrescenta uma segunda coluna; não
reescreve a primeira.

**O que este recuperador não é.** Não é uma proposta de mudança de produto. Ele
só torna mensurável o que já é entregue. Se depois se decidir levar o sinal de
nome para o caminho de trecho, é `F4-P` quem decide, com número dos dois lados.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .harness import Hit

FATOR_DE_CHUNKS = 20
"""Quantos trechos pedir por documento desejado.

`buscar_chunks` devolve trechos, e vários deles são do mesmo arquivo — então
pedir `k` trechos rende **menos** de `k` documentos. Medido no dourado
corporativo, pedindo `k = 20` documentos:

| trechos pedidos | documentos distintos | perguntas com menos de 20 |
|---|---|---|
| `k × 6` = 120 | mínimo 1, mediana 33 | **14 de 59** |
| `k × 20` = 400 | mínimo 16, mediana 108 | 1 de 59 |

Com 6 o adaptador estrangulava a cauda e o relatório diria "o caminho entregue
recupera menos", quando o que faltava era o adaptador ter pedido o bastante.
Medir com os dois deu **as mesmas cinco métricas até a terceira casa** — porque
o que a fome cortava entrava depois da 10ª posição —, mas isso é sorte deste
acervo e não desenho. O fator fica em 20 e a medição que o justifica está aqui,
para ninguém baixá-lo por parecer caro.

Custo: nenhum extra na busca. O poço já tem no máximo `candidatos` por
ranqueador; pedir mais só evita truncar o que já foi recuperado."""


@dataclass
class CaminhoEntregue:
    """`buscar_chunks` visto como ranking de documentos — o que o cliente recebe.

    O colapso trecho → documento é o **mesmo** que `search` faz por dentro: o
    documento fica com a posição do seu melhor trecho. É o que torna as duas
    colunas comparáveis; qualquer outra regra de colapso mediria a regra, não o
    recuperador.
    """

    interno: object
    """`BuscaHibrida`, ou qualquer coisa com `buscar_chunks`. Tipado solto de
    propósito, como `ComSaltoNoGrafo` — o harness não precisa importar o núcleo."""

    fator: int = FATOR_DE_CHUNKS
    _avisou: bool = field(default=False, repr=False)

    @property
    def nome(self) -> str:
        interno = getattr(self.interno, "nome", type(self.interno).__name__)
        # O rótulo diz qual caminho foi medido, porque é a coisa que o relatório
        # inteiro existe para distinguir. Um relatório que diga só "híbrido" é
        # indistinguível do que mediu o outro caminho.
        return f"{interno} · caminho entregue (buscar_chunks)"

    def search(self, consulta: str, k: int) -> list[Hit]:
        vistos: dict[str, tuple[float, str]] = {}
        for acerto in self.interno.buscar_chunks(consulta, k * self.fator):
            if acerto.path not in vistos:
                vistos[acerto.path] = (acerto.score, acerto.texto[:300])
        return [Hit(path=p, score=s, trecho=t) for p, (s, t) in list(vistos.items())[:k]]
