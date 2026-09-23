"""Guarda de qualidade do índice vetorial aproximado — R4.1.

ANN só é uma otimização se preservar a resposta que a varredura exata daria.
Este instrumento codifica a porta do dossiê: para os mesmos vetores de consulta,
compara IVF-PQ com ``bypass_vector_index`` e exige recall@20 médio de pelo menos
0,95. A menor quantidade de sondas que passa vira candidata ao padrão do produto.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .latencia import REPO, percentil

K = 20
RECALL_MINIMO = 0.95
NPROBES_CANDIDATOS = (16, 32, 64, 128, 256)
REFINE_CANDIDATOS = (0, 5, 25, 100)


@dataclass(frozen=True)
class ResultadoANN:
    nprobes: int
    refine_factor: int
    recalls: tuple[float, ...]
    ms: tuple[float, ...]

    @property
    def recall_medio(self) -> float:
        return statistics.fmean(self.recalls) if self.recalls else 0.0

    @property
    def recall_minimo(self) -> float:
        return min(self.recalls) if self.recalls else 0.0

    @property
    def p95_ms(self) -> float:
        return percentil(self.ms, 0.95)


def recall_do_flat(referencia, aproximado) -> float:
    """Fração dos ids do top-k exato recuperada pelo ANN."""
    esperados = {acerto.id for acerto in referencia}
    if not esperados:
        return 1.0
    encontrados = {acerto.id for acerto in aproximado}
    return len(esperados & encontrados) / len(esperados)


def medir(
    store,
    vetores: list[np.ndarray],
    model_id: str,
    *,
    k: int = K,
    nprobes: tuple[int, ...] = NPROBES_CANDIDATOS,
    refine_factors: tuple[int, ...] = (0,),
) -> tuple[ResultadoANN, ...]:
    """Mede candidatos contra uma única referência flat por consulta."""
    referencias = [
        store.buscar_denso(vetor, k, model_id=model_id, usar_ann=False)
        for vetor in vetores
    ]
    resultados: list[ResultadoANN] = []
    for refine_factor in refine_factors:
        for sondas in nprobes:
            recalls: list[float] = []
            tempos: list[float] = []
            for vetor, referencia in zip(vetores, referencias, strict=True):
                inicio = time.perf_counter()
                aproximado = store.buscar_denso(
                    vetor,
                    k,
                    model_id=model_id,
                    usar_ann=True,
                    nprobes=sondas,
                    refine_factor=refine_factor,
                )
                tempos.append((time.perf_counter() - inicio) * 1_000)
                recalls.append(recall_do_flat(referencia, aproximado))
            resultados.append(
                ResultadoANN(sondas, refine_factor, tuple(recalls), tuple(tempos))
            )
    return tuple(resultados)


def escolher_nprobes(
    resultados: tuple[ResultadoANN, ...],
    *,
    recall_minimo: float = RECALL_MINIMO,
) -> int | None:
    """Menor candidato que satisfaz a porta de recall médio."""
    aprovados = [r.nprobes for r in resultados if r.recall_medio >= recall_minimo]
    return min(aprovados, default=None)


def escolher_configuracao(
    resultados: tuple[ResultadoANN, ...],
    *,
    recall_minimo: float = RECALL_MINIMO,
) -> ResultadoANN | None:
    """Configuração aprovada com menor p95 medido nesta mesma passada."""
    aprovados = [r for r in resultados if r.recall_medio >= recall_minimo]
    return min(aprovados, key=lambda r: (r.p95_ms, r.nprobes), default=None)


def parse_nprobes(valor: str) -> tuple[int, ...]:
    try:
        sondas = tuple(sorted({int(item.strip()) for item in valor.split(",") if item.strip()}))
    except ValueError as erro:
        raise ValueError("nprobes deve ser uma lista de inteiros positivos") from erro
    if not sondas or any(item < 1 for item in sondas):
        raise ValueError("nprobes deve ser uma lista de inteiros positivos")
    return sondas


def parse_refine(valor: str) -> tuple[int, ...]:
    itens: list[int] = []
    for bruto in valor.split(","):
        item = bruto.strip().lower()
        if not item:
            continue
        if item in {"none", "sem", "0"}:
            itens.append(0)
            continue
        try:
            numero = int(item)
        except ValueError as erro:
            raise ValueError("refine deve ser uma lista de inteiros positivos ou 'sem'") from erro
        if numero < 1:
            raise ValueError("refine deve ser uma lista de inteiros positivos ou 'sem'")
        itens.append(numero)
    if not itens:
        raise ValueError("refine deve ser uma lista de inteiros positivos ou 'sem'")
    return tuple(dict.fromkeys(itens))


def render(
    resultados: tuple[ResultadoANN, ...],
    *,
    consultas: int,
    chunks: int,
    modelo: str,
    k: int = K,
    recall_minimo: float = RECALL_MINIMO,
) -> str:
    escolhido = escolher_configuracao(resultados, recall_minimo=recall_minimo)
    linhas = [
        "# ANN — recall contra varredura exata (R4.1)",
        "",
        f"Índice de **{chunks:,} trechos**, modelo `{modelo}`, {consultas} consultas e `k={k}`.".replace(",", " "),
        "",
        "Cada linha usa os mesmos vetores de consulta e compara IVF-PQ com a busca",
        "exata (`bypass_vector_index`). A porta é o recall@20 médio, não a latência.",
        "",
        "| nprobes | refine | recall médio | pior consulta | p95 ANN | porta |",
        "|---:|---:|---:|---:|---:|:---:|",
    ]
    for resultado in resultados:
        passou = resultado.recall_medio >= recall_minimo
        linhas.append(
            f"| {resultado.nprobes} | {resultado.refine_factor or '—'} "
            f"| **{resultado.recall_medio:.3f}** "
            f"| {resultado.recall_minimo:.3f} | {resultado.p95_ms:.1f} ms "
            f"| {'✅' if passou else '❌'} |"
        )
    linhas += ["", f"Porta: recall@{k} médio ≥ **{recall_minimo:.2f}**.", ""]
    if escolhido is None:
        linhas.append("**Nenhum candidato passou; o ANN não pode virar padrão.**")
    else:
        linhas.append(
            "Configuração aprovada de menor p95 nesta passada: "
            f"**`nprobes={escolhido.nprobes}`, `refine={escolhido.refine_factor}`**."
        )
    linhas += [
        "",
        "A latência desta tabela é informativa: a referência flat aquece o cache antes",
        "do ANN. A porta de latência continua sendo medida separadamente por `eval.latencia`.",
    ]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from segundocerebro.config import ErroDeConfig, carregar
    from segundocerebro.index.ann import tem_ann
    from segundocerebro.index.embeddings import Embedder
    from segundocerebro.index.store import IndiceEmEscrita, Store, recusar_se_indexando
    from segundocerebro.logger import get_logger

    from .harness import GOLDEN, carregar_perguntas, entregar, resolver_dourado

    log = get_logger("eval.ann")
    parser = argparse.ArgumentParser(
        prog="eval.ann", description="Compara recall@20 do IVF-PQ com a busca vetorial exata"
    )
    parser.add_argument("--base", help="qual base medir")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--golden", type=Path)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--k", type=int, default=K)
    parser.add_argument(
        "--nprobes",
        default=",".join(str(n) for n in NPROBES_CANDIDATOS),
        help="candidatos separados por vírgula",
    )
    parser.add_argument(
        "--refine",
        default="sem",
        help="fatores de reordenação exata separados por vírgula; aceite 'sem'",
    )
    parser.add_argument(
        "--construir",
        action="store_true",
        help="cria o IVF-PQ pela política R4.1 quando ainda não existe",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        sondas = parse_nprobes(args.nprobes)
        refinos = parse_refine(args.refine)
    except ValueError as erro:
        parser.error(str(erro))

    try:
        conf = carregar(args.config, raiz=REPO)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    implicito = args.golden is None and base.dourado is None
    try:
        dourado, aviso = resolver_dourado(
            args.golden or base.dourado or GOLDEN,
            implicito=implicito,
        )
        perguntas = [p.pergunta for p in carregar_perguntas(dourado) if p.no_escopo]
        recusar_se_indexando(Path(base.indice))
    except (FileNotFoundError, IndiceEmEscrita) as erro:
        log.error("%s", erro)
        return 4
    if aviso:
        log.warning("%s", aviso)

    embedder = Embedder(base.modelo, threads=args.threads)
    store = Store(Path(base.indice), embedder.dim)
    try:
        if args.construir and not tem_ann(store.tabela):
            plano = store.garantir_ann()
            if not plano.criar:
                log.error("ANN não criado: %s", plano.motivo)
                return 4
            log.info(
                "ANN criado: %d vetores · %d partições · %d subvetores",
                plano.n_vetores,
                plano.particoes,
                plano.subvetores,
            )
        if not tem_ann(store.tabela):
            log.error("índice ANN ausente em %s; rode a manutenção R4.1 primeiro", base.indice)
            return 4
        vetores = [embedder.embed_consulta(pergunta) for pergunta in perguntas]
        resultados = medir(
            store,
            vetores,
            embedder.model_id,
            k=args.k,
            nprobes=sondas,
            refine_factors=refinos,
        )
        chunks = int(store.estatisticas()["chunks"])
    finally:
        store.fechar()

    relatorio = render(
        resultados,
        consultas=len(perguntas),
        chunks=chunks,
        modelo=embedder.model_id,
        k=args.k,
    )
    entregar(relatorio, args.out)
    escolhido = escolher_configuracao(resultados)
    if escolhido is None:
        log.error("nenhum nprobes passou recall@%d >= %.2f", args.k, RECALL_MINIMO)
        return 1
    log.info(
        "guarda aprovada com nprobes=%d e refine=%d",
        escolhido.nprobes,
        escolhido.refine_factor,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
