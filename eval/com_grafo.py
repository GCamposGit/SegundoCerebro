"""Medição do salto pelo grafo: `search` e depois `neighbors`, uma vez.

    py -m eval.rodar --retriever hibrido --com-grafo --out docs/metricas-f4-hop.md

Existe para responder **com número** quanto o grafo derivado acrescenta de
alcance. Sem isto, o valor da F4 seria um traço qualitativo — "olha, achou a
norma" — e a regra do projeto é que otimização de recuperação passa pelo eval.

## Isto não é um orquestrador, e a distinção é a invariante 3

A invariante diz: *multi-hop é do cliente; não construir orquestrador de
retrieval*. Ela vale para a **superfície MCP**, que continua expondo só
primitivas — `search`, `read_note`, `neighbors` — sem nada que as componha.

O que este módulo faz é **simular** o que um cliente faz, dentro de `eval/`, para
poder medir. Medir a composição não é oferecê-la: nada aqui entra no caminho de
consulta, e `BuscaHibrida` continua sem saber que o grafo existe. Se algum dia
este código sair de `eval/` e entrar em `retrieve/`, aí sim a invariante estaria
sendo violada.

## Onde os vizinhos entram, e por que não no fim

Entram **imediatamente depois dos primeiros resultados** — os mesmos de que o
salto partiu —, empurrando o resto para baixo.

Anexar no fim seria a escolha óbvia e mediria **zero por construção**: o harness
pede `k_max` resultados e a busca já devolve `k_max`, então um vizinho na posição
21 nunca entra em recall@20. O primeiro rascunho deste módulo fazia isso, e o
número teria "provado" que o grafo não serve para nada.

A posição escolhida modela o cliente: ele examinou os primeiros, pediu os vizinhos
deles, e é isso que olha em seguida. O efeito sobre as métricas fica **exatamente
delimitado**, e é o que torna a leitura honesta:

- **recall@1 e recall@3 não podem mudar** — as três primeiras posições ficam
  intactas. Se mudarem, há defeito.
- **recall@5 em diante pode subir ou cair**: sobe pelo alcance novo, cai se um
  vizinho fraco deslocar um acerto que estava na posição 4.

As duas direções sendo mensuráveis é o ponto. Reordenar misturando peso de grafo
com peso de fusão daria um número melhor e uma conclusão pior — não haveria como
separar ganho de alcance de ganho de ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from segundocerebro.logger import get_logger
from segundocerebro.retrieve.grafo import MAX_DOCUMENTOS_POR_ID, vizinhos

from .harness import Hit

log = get_logger("eval.com_grafo")

EXPANDIR_OS_PRIMEIROS = 3
"""De quantos resultados o salto parte.

Um cliente não chama `neighbors` em cinquenta documentos — chama nos primeiros,
que é onde ele acredita estar a resposta. Três é o que um laço de agente
tipicamente examina antes de decidir, e manter baixo também mantém a medição
comparável ao uso real.
"""

VIZINHOS_POR_DOCUMENTO = 5


@dataclass
class ComSaltoNoGrafo:
    """Envolve um recuperador e acrescenta um salto pelo grafo. Só medição."""

    interno: object
    store: object
    expandir: int = EXPANDIR_OS_PRIMEIROS
    por_documento: int = VIZINHOS_POR_DOCUMENTO
    max_documentos_por_id: int = MAX_DOCUMENTOS_POR_ID

    @property
    def nome(self) -> str:
        return f"{self.interno.nome} + salto no grafo"

    def search(self, consulta: str, k: int) -> list[Hit]:
        achados = self.interno.search(consulta, k)
        vistos = {h.path for h in achados}
        acrescentados: list[Hit] = []

        for origem in achados[: self.expandir]:
            for vizinho in vizinhos(
                self.store,
                origem.path,
                limite=self.por_documento,
                max_documentos_por_id=self.max_documentos_por_id,
            ):
                if vizinho.path in vistos:
                    continue
                vistos.add(vizinho.path)
                ligacao = vizinho.ligacoes[0]
                acrescentados.append(
                    Hit(
                        path=vizinho.path,
                        score=vizinho.peso,
                        # A procedência da aresta vai no trecho: um relatório que
                        # dissesse só "veio do grafo" não permitiria conferir por
                        # que, e conferir é o que separa medição de fé.
                        trecho=(
                            f"[grafo] via {ligacao.tipo} {ligacao.valor} "
                            f"({ligacao.documentos} docs), a partir de {origem.path}"
                        ),
                    )
                )

        if not acrescentados:
            return achados
        # Depois dos que originaram o salto, e não no fim: no fim, um vizinho cai
        # na posição 21 de uma lista de 20 e nenhuma métrica o conta.
        corte = min(self.expandir, len(achados))
        return (achados[:corte] + acrescentados + achados[corte:])[:k]
