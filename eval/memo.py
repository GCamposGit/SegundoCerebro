"""Memo de busca para varredura de muitos braços — sem trocar o caminho medido.

    memo = MemoDeBusca(store, embedder)
    retriever = BuscaHibrida(memo.store, memo.embedder, ...)

**O problema.** Uma grade de 18 braços sobre 60 perguntas são 1.080 consultas, e
`search` custa 1,8 a 2,9 s de p95 neste notebook (`docs/porta-de-latencia.md`).
São horas — e a maior parte é trabalho repetido: o braço denso **não** depende dos
pesos de coluna do bm25 nem do peso de nome, e a busca lexical só muda quando os
pesos de coluna mudam.

**Por que não reimplementar a fusão offline.** Seria mais rápido ainda: buscar
uma vez, fundir 18 vezes em aritmética pura. E seria a repetição de um defeito
que este projeto já pagou três vezes — `docs/porta-de-latencia.md` mediu
`recursos.busca`, que herda o reranker da base, e chamou aquilo de "sem rerank";
o `Busca.rerank` documenta "medir o componente não é medir o caminho". Uma fusão
paralela à de produção é um caminho de código que ninguém mede, e o número que
ela dá é plausível — então passaria.

**O que este módulo faz em vez disso.** Guarda memória na **fronteira do
`Store`**, embaixo de tudo. `BuscaHibrida` roda inteira, de verdade, 18 vezes:
a expansão de glossário, a fusão RRF, o colapso de famílias, o ranqueador de
nome. O que não roda duas vezes é a mesma consulta ao mesmo índice com os mesmos
argumentos — que por definição devolveria o mesmo.

A prova disso não é este texto, é `eval/test_memo.py`: a mesma grade com e sem
memo tem de dar métricas idênticas, ou o memo está errado.

**Escopo.** Serve varredura, e só. Não entra no caminho do servidor MCP nem do
`eval.rodar` de uma passada: ali cada consulta é uma, e um dicionário que cresce
sem teto seria vazamento de memória sem ganho nenhum. Nada aqui invalida
`docs/porta-de-latencia.md` — medição de latência não passa por memo, pelo mesmo
motivo de sempre.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from segundocerebro.logger import get_logger

log = get_logger("eval.memo")


class _StoreComMemo:
    """Proxy de `Store` que lembra as duas buscas. O resto passa direto.

    `__getattr__` delega tudo que não é busca — `paths_com_chunks`, `mtimes`,
    `chunk`, `estatisticas`, `fechar`. Delegar em vez de listar é o que impede
    este proxy de envelhecer quando o `Store` ganhar método novo.
    """

    def __init__(self, store: Any) -> None:  # noqa: ANN401 — é o Store, sem importar
        self._store = store
        self._denso: dict[tuple, list] = {}
        self._lexical: dict[tuple, list] = {}
        self.acertos = 0
        self.buscas = 0

    def __getattr__(self, nome: str) -> Any:  # noqa: ANN401
        return getattr(self._store, nome)

    def buscar_denso(
        self,
        vetor: np.ndarray,
        k: int,
        filtro: str | None = None,
        model_id: str | None = None,
        *,
        usar_ann: bool | None = None,
        nprobes: int | None = None,
        refine_factor: int | None = None,
    ) -> list:
        # Chave pelos bytes do vetor, não pela identidade do objeto: o embedder
        # com memo devolve o mesmo objeto, mas o sem memo não, e a chave tem de
        # ser a mesma nos dois casos para o teste de equivalência valer algo.
        chave = (vetor.tobytes(), k, filtro, model_id, usar_ann, nprobes, refine_factor)
        return self._lembrar(
            self._denso,
            chave,
            lambda: self._store.buscar_denso(
                vetor,
                k,
                filtro,
                model_id,
                usar_ann=usar_ann,
                nprobes=nprobes,
                refine_factor=refine_factor,
            ),
        )

    def buscar_lexical(
        self,
        texto: str,
        k: int,
        pesos_colunas: tuple[float, float, float] | None = None,
        *,
        podar_ubiquos: bool = True,
    ) -> list:
        chave = (texto, k, pesos_colunas, podar_ubiquos)
        return self._lembrar(
            self._lexical,
            chave,
            lambda: self._store.buscar_lexical(
                texto, k, pesos_colunas, podar_ubiquos=podar_ubiquos
            ),
        )

    def _lembrar(self, cache: dict, chave: tuple, calcular) -> list:  # noqa: ANN001
        self.buscas += 1
        if chave in cache:
            self.acertos += 1
            # Cópia da lista, não a lista: quem chama concatena e ordena, e um
            # `Acerto` mutado por engano contaminaria os braços seguintes de um
            # jeito que a tabela não denuncia.
            return list(cache[chave])
        resultado = calcular()
        cache[chave] = resultado
        return list(resultado)


class _EmbedderComMemo:
    """Proxy de `Embedder` que lembra o vetor de cada consulta.

    Só `embed_consulta`. `embed_passagens` é da indexação e não passa por aqui —
    guardar passagem em dicionário seria guardar o acervo em memória.
    """

    def __init__(self, embedder: Any) -> None:  # noqa: ANN401
        self._embedder = embedder
        self._vetores: dict[str, np.ndarray] = {}
        self.acertos = 0
        self.chamadas = 0

    def __getattr__(self, nome: str) -> Any:  # noqa: ANN401
        return getattr(self._embedder, nome)

    def embed_consulta(self, texto: str) -> np.ndarray:
        self.chamadas += 1
        vetor = self._vetores.get(texto)
        if vetor is not None:
            self.acertos += 1
            return vetor
        vetor = self._embedder.embed_consulta(texto)
        self._vetores[texto] = vetor
        return vetor


class MemoDeBusca:
    """Par (store, embedder) com memo, e o resumo do que se economizou."""

    def __init__(self, store: Any, embedder: Any) -> None:  # noqa: ANN401
        self.store = _StoreComMemo(store)
        self.embedder = _EmbedderComMemo(embedder)

    def resumo(self) -> str:
        """Uma linha para o log. Taxa baixa é sinal de grade mal desenhada."""
        b, a = self.store.buscas, self.store.acertos
        taxa = a / b if b else 0.0
        return (
            f"memo: {a} de {b} buscas ao índice evitadas ({taxa:.0%}), "
            f"{self.embedder.acertos} de {self.embedder.chamadas} embeddings de consulta"
        )
