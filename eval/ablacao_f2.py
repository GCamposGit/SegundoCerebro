"""Consolidated ablation table for F2, all arms in one pass.

    py -m eval.ablacao_f2 --out docs/ablacao-f2-tabela.md

A saída da F2 pede **uma tabela** com nDCG@5 por configuração, e até aqui cada
braço era um relatório separado montado à mão numa tabela final — foi assim que
a `ablacao-f1.md` nasceu. Montar à mão custa duas coisas: o encoder recarrega por
braço, e a tabela pode discordar dos relatórios sem que nada acuse.

Aqui os braços são declarados em `BRACOS`, o encoder abre **uma vez** e a tabela
sai do mesmo objeto `Resultado` que os relatórios usam. Cada braço difere do
anterior por um fator só — é o que permite atribuir a diferença àquele fator.

A saída é **evidência regenerável**, e por isso vai para um arquivo separado da
leitura: `docs/ablacao-f2-tabela.md` é gerado e pode ser reescrito a qualquer
momento; `docs/ablacao-f2.md` é escrito à mão e é onde mora a conclusão. Misturar
os dois faria uma regeneração apagar em silêncio o raciocínio.

O tempo por consulta entra na tabela porque na F2 ele é resultado, não nota de
rodapé: o reranking compra precisão a 6,8× no custo, e uma tabela que só mostra
qualidade esconde a decisão que importa.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import BuscaHibrida

from .harness import KS_NDCG, Resultado, avaliar, carregar_perguntas, conferir_base, entregar, verificar_escopo
from .idioma import CROSS_LINGUAL, MESMA_LINGUA

log = get_logger("eval.ablacao_f2")

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"

PESO_RERANK = 0.25
"""O pico da grade de `docs/ablacao-rerank.md`. Repetido aqui de propósito: este
módulo tem que poder ser lido sozinho para saber o que foi medido."""


@dataclass(frozen=True)
class Braco:
    """Um ponto da tabela. `fator` é o que ele acrescenta ao braço anterior."""

    rotulo: str
    fator: str
    montar: Callable[..., BuscaHibrida]


def _hibrido(**extra):  # noqa: ANN003, ANN202
    """Fecha sobre os pesos da base, para o número medido ser o que o servidor roda."""

    def montar(store, embedder, base, threads):  # noqa: ANN001, ANN202
        pesos = base.pesos
        argumentos = {
            "candidatos": base.busca.candidatos,
            "k_rrf": base.busca.k_rrf,
            "usar_denso": True,
            "usar_lexical": True,
            "usar_nome": bool(pesos.nome),
            "peso_denso": pesos.denso,
            "peso_lexical": pesos.lexical,
            "peso_nome": pesos.nome,
            "reranker": None,
        }
        argumentos.update(extra)
        if argumentos.pop("com_rerank", False):
            from segundocerebro.retrieve.rerank import Reranker

            argumentos["reranker"] = Reranker(
                candidatos=base.busca.rerank_candidatos, peso=PESO_RERANK, threads=threads
            )
        return BuscaHibrida(store, embedder, **argumentos)

    return montar


BRACOS = (
    Braco(
        "bm25 puro",
        "só casamento exato",
        _hibrido(usar_denso=False, usar_nome=False, agrupar_familias=False),
    ),
    Braco(
        "denso puro",
        "só significado",
        _hibrido(usar_lexical=False, usar_nome=False, agrupar_familias=False),
    ),
    Braco(
        "denso + bm25",
        "+ o segundo ranqueador",
        _hibrido(usar_nome=False, agrupar_familias=False),
    ),
    Braco(
        "bm25 + nome",
        "nome sobre o lexical",
        _hibrido(usar_denso=False, agrupar_familias=False),
    ),
    Braco(
        "denso + nome",
        "nome sobre o denso, sem bm25",
        _hibrido(usar_lexical=False, agrupar_familias=False),
    ),
    Braco(
        "os três, sem famílias",
        "+ o terceiro ranqueador",
        _hibrido(agrupar_familias=False),
    ),
    Braco(
        "os três + famílias de versão",
        "+ metadado de versão",
        _hibrido(agrupar_familias=True),
    ),
    Braco(
        "denso + nome + famílias",
        "o mesmo, sem bm25",
        _hibrido(usar_lexical=False, agrupar_familias=True),
    ),
    Braco(
        f"os três + famílias + rerank {PESO_RERANK:g}".replace(".", ","),
        "+ o cross-encoder como 4º ranqueador",
        _hibrido(agrupar_familias=True, com_rerank=True),
    ),
)
"""Declarados antes de rodar, e em ordem de acréscimo: cada linha difere da
anterior por um fator só. As três primeiras são os ranqueadores isolados, as duas
seguintes isolam o que o nome faz sobre cada sinal, e as últimas são a escada da
F2 — o critério de saída pede exatamente `denso-só vs. híbrido vs.
híbrido+rerank`.

`denso + nome + famílias` existe porque a primeira rodada mediu `denso + nome`
com famílias desligadas e ele chegou a nDCG@5 0,769 — praticamente o do rerank,
a um sexto do custo — mas com 3 de 6 armadilhas. Como foram justamente as
famílias que levaram as armadilhas de 4 para 5, a tabela tinha um buraco exatamente
onde estava o melhor candidato: sem essa linha não se sabe se o bm25 ainda paga
o lugar dele na configuração padrão."""


@dataclass(frozen=True)
class Medida:
    braco: Braco
    resultado: Resultado
    segundos_por_consulta: float

    @property
    def armadilhas(self) -> int:
        """Contagem, não média: a porta 3 é por caso, e `recall == 1` já traz o modo."""
        return sum(1 for i in self.resultado.subgrupo(armadilha=True) if i.recall[10] == 1.0)

    @property
    def multihop(self) -> int:
        return sum(
            1 for i in self.resultado.itens if i.pergunta.tipo == "multihop" and i.recall[10] == 1.0
        )

    @property
    def usuario_mrr(self) -> float:
        """O subconjunto sem viés de construção — 39 das 45 vieram de nomes de arquivo."""
        return Resultado.mrr_de(self.resultado.subgrupo(autoria="usuario"))

    @property
    def cross_mrr(self) -> float | None:
        """MRR da fatia cross-lingual, ou `None` quando ela está vazia.

        `None` e não zero: braço cujo dourado não tem par cross-lingual não é um
        braço que falhou na ponte entre idiomas, e imprimir 0,000 nessa coluna
        diria que falhou. Uma tabela de ablação com um zero inventado é pior que
        uma com um travessão — o travessão faz perguntar, o zero não."""
        itens = self.resultado.subgrupo(fatia=CROSS_LINGUAL)
        return Resultado.mrr_de(itens) if itens else None

    @property
    def mesma_lingua_mrr(self) -> float | None:
        itens = self.resultado.subgrupo(fatia=MESMA_LINGUA)
        return Resultado.mrr_de(itens) if itens else None


def medir(store, embedder, base, perguntas, threads: int) -> list[Medida]:  # noqa: ANN001
    medidas: list[Medida] = []
    for i, braco in enumerate(BRACOS, start=1):
        retriever = braco.montar(store, embedder, base, threads)
        comecou = time.monotonic()
        completo = avaliar(retriever, perguntas)
        decorrido = time.monotonic() - comecou
        # Dividir pelas perguntas que o laço **rodou**, não pelas que entram na
        # média: `restrito_ao_escopo` corta 6 das 51, e usar 45 como divisor
        # superestimaria o custo em 13%.
        medida = Medida(
            braco, completo.restrito_ao_escopo(), decorrido / max(1, len(completo.itens))
        )
        medidas.append(medida)
        log.info(
            "%d/%d %-38s r@1 %.3f MRR %.3f nDCG@5 %.3f armadilhas %d/6 %.2f s/consulta",
            i,
            len(BRACOS),
            braco.rotulo,
            medida.resultado.recall(1),
            medida.resultado.mrr(),
            medida.resultado.ndcg(k=5),
            medida.armadilhas,
            medida.segundos_por_consulta,
        )
    return medidas


def num(valor: float, casas: int = 3) -> str:
    """Vírgula decimal: a documentação do projeto é em português, e uma tabela
    meio com ponto meio com vírgula lê como duas medições diferentes."""
    return f"{valor:.{casas}f}".replace(".", ",")


def render(medidas: list[Medida], contexto: str, referencia: str) -> str:
    ndcg_cols = " | ".join(f"nDCG@{k}" for k in KS_NDCG)
    linhas = [
        "# Ablação da F2 — tabela consolidada",
        "",
        contexto,
        "",
        "Os braços estão declarados em `eval/ablacao_f2.py`, **em ordem de acréscimo**:",
        "cada linha difere da anterior por um fator só, e é isso que permite atribuir",
        "a diferença àquele fator. Todos correram na mesma passada, com o encoder aberto",
        "uma única vez, sobre as mesmas perguntas e o mesmo índice.",
        "",
        "O critério de saída da fase pede `denso-só vs. híbrido vs. híbrido+rerank`.",
        "Essas são as linhas **denso puro**, **os três + famílias** e **+ rerank**; o",
        "resto da escada está aqui porque uma superfície plana e uma com pico levam a",
        "conclusões diferentes, e só o vencedor não distingue as duas.",
        "",
        "## A tabela",
        "",
        f"| Recuperador | o que acrescenta | recall@1 | recall@5 | recall@10 | MRR@10 | {ndcg_cols} "
        "| armadilhas | multi-hop | usuário MRR | MRR mesma-língua | MRR cross-lingual | s/consulta |",
        "|---|---|---:|---:|---:|---:|" + "---:|" * (len(KS_NDCG) + 6),
        referencia,
    ]
    melhor_ndcg5 = max(m.resultado.ndcg(k=5) for m in medidas)
    for m in medidas:
        r = m.resultado
        ndcgs = " | ".join(num(r.ndcg(k=k)) for k in KS_NDCG)
        destaque = "**" if r.ndcg(k=5) == melhor_ndcg5 else ""
        linhas.append(
            f"| {destaque}{m.braco.rotulo}{destaque} | {m.braco.fator} "
            f"| {num(r.recall(1))} | {num(r.recall(5))} | {num(r.recall(10))} | {num(r.mrr())} "
            f"| {ndcgs} | {m.armadilhas} de 6 | {m.multihop} de 5 | {num(m.usuario_mrr)} "
            f"| {num(m.mesma_lingua_mrr) if m.mesma_lingua_mrr is not None else '—'} "
            f"| {num(m.cross_mrr) if m.cross_mrr is not None else '—'} "
            f"| {num(m.segundos_por_consulta, 2)} |"
        )
    linhas += [
        "",
        "`armadilhas` e `multi-hop` são **contagem** de casos resolvidos por inteiro no",
        "top-10, não média — as portas 3 e 4 são por caso, e multi-hop exige todas as",
        "fontes. A coluna `usuário MRR` é o subconjunto das 6 perguntas escritas de",
        "memória: as outras 39 nasceram de nomes de arquivo e favorecem, por construção,",
        "quem lê nome.",
        "",
        "As duas últimas colunas de MRR são a fatia de idioma (`C4.5`). O acervo é",
        "bilíngue e a ponte PT↔EN mora num ranqueador só — o denso é multilíngue e",
        "alinhado, o bm25 é cego a idioma por construção. Um braço que troque modelo ou",
        "reranker pode subir na média e **cair** na coluna cross-lingual; sem as duas",
        "colunas lado a lado essa troca passaria como ganho limpo. `—` significa fatia",
        "vazia, não fatia zerada: o dourado desta base não tem par daquele lado.",
        "",
    ]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval.ablacao_f2", description="Tabela consolidada de ablação da F2"
    )
    parser.add_argument("--base", help="qual base medir")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--golden", type=Path)
    parser.add_argument("--indice", type=Path)
    parser.add_argument("--modelo")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    from segundocerebro.config import ErroDeConfig, carregar
    from segundocerebro.index.embeddings import Embedder
    from segundocerebro.index.store import Store

    try:
        base = carregar(args.config, raiz=REPO).base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    embedder = Embedder(args.modelo or base.modelo, threads=args.threads)
    store = Store(args.indice or base.indice, embedder.dim)
    estat = store.estatisticas()
    if not estat["chunks"]:
        log.error("índice vazio em %s", args.indice or base.indice)
        return 2

    perguntas = carregar_perguntas(args.golden or base.dourado or GOLDEN)
    try:
        conferir_base(perguntas, base.id)
    except ValueError as erro:
        log.error("%s", erro)
        return 2
    for d in verificar_escopo(perguntas, set(store.paths_com_chunks())):
        (log.error if d.especie == "silenciosa" else log.warning)(
            "escopo/%s: %s — %s", d.especie, d.id, d.detalhe
        )

    try:
        medidas = medir(store, embedder, base, perguntas, args.threads)
    finally:
        store.fechar()

    contexto = (
        f"> Medido na condição C: {estat['documentos']} documentos, {estat['chunks']} chunks, "
        f"{len(medidas[0].resultado.itens)} perguntas no escopo, modelo `{embedder.model_id}`, "
        f"{base.busca.candidatos} candidatos por ranking antes da fusão."
    )
    # O baseline não entra na passada: ele ranqueia a árvore de arquivos, não o
    # índice, e construí-lo aqui misturaria dois universos numa tabela só. Entra
    # como referência citada, com a origem à mostra.
    referencia = (
        "| _baseline por nome de arquivo_ | _referência da F0_ | _0,467_ | — | _0,800_ | _0,592_ "
        "| — | _0,643_ | _3 de 6_ | _3 de 5_ | _0,557_ | — |"
    )
    relatorio = render(medidas, contexto, referencia)

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
