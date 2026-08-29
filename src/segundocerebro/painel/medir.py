"""Medição real para o painel: roda o conjunto dourado da base.

Separado de `app.py` de propósito. A aplicação não importa o encoder nem o
índice — quem faz isso é este módulo, injetado como `medidor`. Assim o teste da
API não paga 80 s de carga de modelo para verificar uma regra de negócio, e a
fronteira da invariante 6 fica visível no import: `app.py` não sabe recuperar.

O encoder é aberto uma vez e reaproveitado entre medições. Sem isso, arrastar um
controle e apertar "Medir" custaria 80 s de carga a cada vez, e ninguém ajustaria
nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Busca, Pesos
from ..index.embeddings import Embedder
from ..index.store import Store
from ..logger import get_logger
from ..repositorio import em_checkout
from ..repositorio import raiz as raiz_do_repositorio
from ..retrieve.hybrid import BuscaHibrida
from .erros import MedicaoIndisponivel

log = get_logger("painel.medir")

GOLDEN_PADRAO = raiz_do_repositorio() / "eval" / "golden" / "perguntas.jsonl"


@dataclass
class Medidor:
    """Guarda encoder e índice abertos, por base."""

    golden_padrao: Path = GOLDEN_PADRAO
    _abertos: dict[str, tuple[Embedder, Store]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._abertos = {}

    def _recursos(self, base) -> tuple[Embedder, Store]:  # noqa: ANN001
        if base.id not in self._abertos:
            log.info("abrindo %s para a base '%s' (uma vez só)", base.modelo, base.id)
            embedder = Embedder(base.modelo)
            self._abertos[base.id] = (embedder, Store(base.indice, embedder.dim))
        return self._abertos[base.id]

    def __call__(self, base, pesos: Pesos, busca: Busca) -> dict[str, Any]:  # noqa: ANN001
        # A única dependência do produto sobre `eval/`, e ela é declarada:
        # `tests/test_pacote.py` varre `src/` atrás de qualquer outra e reprova
        # se aparecer, e exige que esta esteja guardada.
        try:
            from eval.harness import avaliar, carregar_perguntas, conferir_base, resolver_dourado
        except ModuleNotFoundError as erro:
            raise MedicaoIndisponivel(
                "esta instalação não traz o harness de avaliação: `eval/` fica fora do "
                "pacote porque carrega o conjunto dourado. Para medir, rode o painel a "
                f"partir de um clone do repositório (aqui: {'sim' if em_checkout() else 'não'})."
            ) from erro

        # Explícito mesmo quando cai no padrão: o painel não mede o exemplo
        # sintético contra o índice de outra base.
        alvo, _ = resolver_dourado(base.dourado or self.golden_padrao, implicito=False)
        perguntas = carregar_perguntas(alvo)
        conferir_base(perguntas, base.id)
        return resumir(avaliar(self._busca(base, pesos, busca), perguntas).restrito_ao_escopo())

    def _busca(self, base, pesos: Pesos, busca: Busca) -> BuscaHibrida:  # noqa: ANN001
        embedder, store = self._recursos(base)
        return BuscaHibrida(
            store,
            embedder,
            candidatos=busca.candidatos,
            k_rrf=busca.k_rrf,
            usar_denso=bool(pesos.denso),
            usar_lexical=bool(pesos.lexical),
            usar_nome=bool(pesos.nome),
            peso_denso=pesos.denso,
            peso_lexical=pesos.lexical,
            peso_nome=pesos.nome,
        )

    def diagnosticar(self, base, pesos: Pesos, busca: Busca, consulta: str) -> dict[str, Any]:  # noqa: ANN001
        """Quem achou o quê, para a pergunta "por que este veio em primeiro".

        Devolve procedência e qual ranqueador encontrou cada trecho — nada de
        texto gerado, que seria a invariante 2 pela porta dos fundos.
        """
        acertos = self._busca(base, pesos, busca).buscar_chunks(consulta, busca.k)
        return {
            "trechos": [
                {
                    "arquivo": a.path,
                    "secao": a.trilha,
                    "onde": a.locator,
                    "texto": a.texto,
                    "achado_por": a.origem or "nome",
                    "score": round(a.score, 5),
                }
                for a in acertos
            ]
        }

    def fechar(self) -> None:
        for _, store in self._abertos.values():
            store.fechar()
        self._abertos.clear()


def resumir(resultado) -> dict[str, Any]:  # noqa: ANN001 — eval.harness.Resultado
    """Métricas agregadas **e** o movimento por pergunta.

    Por pergunta porque a porta 5 do ROADMAP é orçamento de regressão, e duas
    médias não dizem *quais* perguntas se moveram. É esse detalhe que a tela
    mostra no antes/depois; sem ele, "melhorou" é uma afirmação sobre a média
    que pode esconder três regressões.

    As contagens de armadilha e multi-hop são por caso, não por média: com 6 e 5
    perguntas cada uma vale 16,7 e 20 pontos, e a taxa não estima nada.
    """
    itens = resultado.itens
    return {
        "n": len(itens),
        "recall@1": round(resultado.recall(1), 4),
        "recall@10": round(resultado.recall(10), 4),
        "mrr@10": round(resultado.mrr(), 4),
        "ndcg@10": round(resultado.ndcg(), 4),
        "armadilhas": sum(
            1 for i in resultado.subgrupo(armadilha=True) if i.recall[10] == 1.0
        ),
        "armadilhas_total": len(list(resultado.subgrupo(armadilha=True))),
        "multihop": sum(
            1 for i in itens if i.pergunta.tipo == "multihop" and i.recall[10] == 1.0
        ),
        "multihop_total": sum(1 for i in itens if i.pergunta.tipo == "multihop"),
        "perguntas": [
            {
                "id": i.pergunta.id,
                "pergunta": i.pergunta.pergunta,
                "tipo": i.pergunta.tipo,
                "armadilha": i.pergunta.armadilha,
                "posicao": i.posicao_primeiro_acerto,
                "no_top10": i.recall[10] == 1.0,
            }
            for i in itens
        ],
    }
