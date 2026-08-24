"""Weight sweep over the RRF fusion, with the decision rule fixed in advance.

    py -m eval.varredura --indice index --out docs/varredura-pesos-f1.md

Com 45 perguntas e 16 configurações, a melhor por acaso ganha alguns pontos. E
os 6 casos-armadilha estão **dentro** dos 39 rascunhos, então não existe divisão
limpa entre conjunto de ajuste e conjunto retido: eles são o alvo da otimização
e não podem ser a validação ao mesmo tempo.

O que substitui a divisão que não existe:

1. A grade é declarada aqui, no código, antes de rodar.
2. `REGRA` também — escolher olhando a tabela pronta é escolher o ruído.
3. A grade inteira vai para o relatório, não só o vencedor, porque uma
   superfície plana e uma com pico levam a conclusões diferentes e a média
   sozinha não distingue as duas.
4. O resultado vale como **hipótese**, confirmada depois no corpus completo, que
   é medição independente.

A hipótese que motivou a varredura está em `docs/ablacao-f1.md`: o ranqueador de
nome derruba os casos-armadilha de 5 para 3 de 6 enquanto sobe a média geral.
Por isso a regra não maximiza a média sozinha — otimizar a média escolheria hoje
a configuração que mais erra onde a fase promete acertar.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import BuscaHibrida

from .harness import (
    GOLDEN,
    K_MRR,
    Resultado,
    avaliar,
    carregar_perguntas,
    conferir_base,
    entregar,
    resolver_dourado,
    verificar_escopo,
)

log = get_logger("eval.varredura")

REPO = Path(__file__).resolve().parent.parent

PESOS = (0.0, 0.25, 0.5, 1.0)
"""Valores testados para cada um dos três ranqueadores.

A versão anterior fixava o lexical em 1,0, argumentando que só a razão entre os
pesos importa. A razão está certa e a conclusão estava errada: fixar em 1,0 não
normaliza a escala, **impede o lexical de ser zero**. O braço `denso + nome` sem
bm25 ficou fora da grade — e mediu o maior MRR de todos (0,755 contra 0,742 do
escolhido) e o melhor multi-hop (4 de 5 contra 3). A regra o teria rejeitado
por outro motivo, mas isso foi sorte, não desenho.

A normalização correta usa a mesma equivalência de escala sem perder ponto:
`rrf` é linear nos pesos, então `(2, 2, 1)` e `(1, 1, 0,5)` produzem a mesma
ordenação. Basta manter os triplos cujo **máximo é 1,0** — um representante por
classe de equivalência. São 37 pontos em vez de 64, cobrindo o mesmo espaço."""


def grade() -> list[tuple[float, float, float]]:
    """Triplos (denso, lexical, nome) canônicos: um por razão distinta."""
    return [
        (d, l, n)
        for d in PESOS
        for l in PESOS  # noqa: E741
        for n in PESOS
        if max(d, l, n) == 1.0
    ]

MINIMO_ARMADILHAS = 4
"""De 6. O baseline por nome faz 3 e o bm25 puro faz 5 (`docs/ablacao-f1.md`).

Exigir 4 corta as configurações que compram média entregando o subconjunto que
a fase existe para resolver, sem exigir de saída o melhor já medido — a porta
do ROADMAP pede 5 de 6, e essa é a porta, não o critério de varredura."""


@dataclass(frozen=True)
class Ponto:
    peso_denso: float
    peso_lexical: float
    peso_nome: float
    resultado: Resultado

    @property
    def armadilhas(self) -> int:
        """Casos-armadilha resolvidos por inteiro no top-10.

        Contagem, não média: a porta do ROADMAP é por caso, e `recall == 1` já
        carrega o modo certo — multi-hop exige todas as fontes, o resto exige uma.
        """
        return sum(1 for i in self.resultado.subgrupo(armadilha=True) if i.recall[10] == 1.0)

    @property
    def multihop(self) -> int:
        """Multi-hop resolvidos por inteiro no top-10 — a porta 4 é por caso."""
        return sum(
            1 for i in self.resultado.itens if i.pergunta.tipo == "multihop" and i.recall[10] == 1.0
        )

    @property
    def usuario_mrr(self) -> float:
        return Resultado.mrr_de(self.resultado.subgrupo(autoria="usuario"))

    @property
    def elegivel(self) -> bool:
        return self.armadilhas >= MINIMO_ARMADILHAS


def REGRA(pontos: list[Ponto]) -> Ponto | None:  # noqa: N802 — é uma constante de decisão
    """Maior MRR@10 entre os pontos elegíveis; empate decide pelo modelo mais simples.

    Declarada antes de rodar. Desempate por recall@1 e, persistindo, por menor
    peso de nome — entre duas configurações que medem igual, a que depende menos
    do nome do arquivo é a que generaliza melhor para um acervo com nomes piores,
    que é o caso corporativo que a F5 vai encontrar.
    """
    elegiveis = [p for p in pontos if p.elegivel]
    if not elegiveis:
        return None
    return max(elegiveis, key=lambda p: (p.resultado.mrr(), p.resultado.recall(1), -p.peso_nome))


def varrer(store, embedder, perguntas, candidatos: int) -> list[Ponto]:  # noqa: ANN001
    pontos: list[Ponto] = []
    triplos = grade()
    for i, (peso_denso, peso_lexical, peso_nome) in enumerate(triplos, start=1):
        retriever = BuscaHibrida(
            store,
            embedder,
            candidatos=candidatos,
            usar_denso=bool(peso_denso),
            usar_lexical=bool(peso_lexical),
            usar_nome=bool(peso_nome),
            peso_denso=peso_denso,
            peso_lexical=peso_lexical,
            peso_nome=peso_nome,
        )
        resultado = avaliar(retriever, perguntas).restrito_ao_escopo()
        pontos.append(Ponto(peso_denso, peso_lexical, peso_nome, resultado))
        log.info(
            "%2d/%d denso=%.2f bm25=%.2f nome=%.2f | r@1 %.3f MRR %.3f armadilhas %d/6",
            i,
            len(triplos),
            peso_denso,
            peso_lexical,
            peso_nome,
            resultado.recall(1),
            resultado.mrr(),
            pontos[-1].armadilhas,
        )
    return pontos


def render(pontos: list[Ponto], escolhido: Ponto | None, contexto: str) -> str:
    linhas = [
        "# Varredura de pesos da fusão RRF — F1",
        "",
        contexto,
        "",
        "Grade e regra de escolha declaradas em `eval/varredura.py` **antes** de rodar.",
        f"São {len(pontos)} configurações sobre 45 perguntas, e escolher olhando a tabela",
        "pronta seria escolher o ruído; como os 6 casos-armadilha estão dentro dos 39",
        "rascunhos, não existe divisão limpa entre ajuste e validação. A grade inteira",
        "está aqui porque superfície plana e superfície com pico levam a conclusões",
        "diferentes.",
        "",
        "Os três pesos variam. A grade anterior fixava o lexical em 1,0 — o que não",
        "normaliza a escala, apenas **impede o lexical de ser zero** — e por isso não",
        "enxergava `denso + nome` sem bm25. Aqui os triplos são canônicos: como `rrf` é",
        "linear nos pesos, `(2, 2, 1)` ordena igual a `(1, 1, 0,5)`, então basta manter",
        "os de máximo 1,0. Um representante por razão distinta, sem perder ponto.",
        "",
        f"**Regra:** maior MRR@10 entre as configurações com pelo menos "
        f"{MINIMO_ARMADILHAS} de 6 casos-armadilha no top-10. Desempate por recall@1 e,",
        "persistindo, pelo menor peso de nome.",
        "",
        "## A grade",
        "",
        "| denso | bm25 | nome | recall@1 | recall@10 | MRR@10 | nDCG@10 | armadilhas | usuário MRR | multi-hop | elegível |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for p in sorted(pontos, key=lambda x: (-x.resultado.mrr(), x.peso_nome)):
        marca = " **←**" if escolhido is not None and p is escolhido else ""
        linhas.append(
            f"| {p.peso_denso:g} | {p.peso_lexical:g} | {p.peso_nome:g} "
            f"| {p.resultado.recall(1):.3f} "
            f"| {p.resultado.recall(10):.3f} | {p.resultado.mrr():.3f} | {p.resultado.ndcg():.3f} "
            f"| {p.armadilhas} de 6 | {p.usuario_mrr:.3f} | {p.multihop} de 5 "
            f"| {'sim' if p.elegivel else 'não'}{marca} |"
        )
    linhas.append("")

    linhas.append("## Escolhido pela regra")
    linhas.append("")
    if escolhido is None:
        linhas.append(
            f"**Nenhum.** Nenhuma configuração da grade alcança {MINIMO_ARMADILHAS} de 6 "
            "casos-armadilha. O conflito entre o sinal de nome e o de conteúdo não é de "
            "intensidade, e sim de forma — nenhum peso resolve. Ver a discussão sobre o "
            "nome como desempate em vez de ranqueador de voz plena."
        )
    else:
        linhas.append(
            f"`denso={escolhido.peso_denso:g}`, `lexical={escolhido.peso_lexical:g}`, "
            f"`nome={escolhido.peso_nome:g}` — MRR@{K_MRR} {escolhido.resultado.mrr():.3f}, "
            f"recall@1 {escolhido.resultado.recall(1):.3f}, "
            f"{escolhido.armadilhas} de 6 armadilhas, {escolhido.multihop} de 5 multi-hop."
        )
        linhas.append("")
        linhas.append(
            "Vale como **hipótese**, não como conclusão: foi escolhido nas mesmas 45 "
            "perguntas que servem de porta. A confirmação é a medição no corpus completo, "
            "que é amostra independente."
        )
    linhas.append("")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.varredura", description="Varre os pesos da fusão RRF")
    parser.add_argument("--base", help="qual base varrer (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", help="sobrepõe o modelo da base")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--candidatos", type=int, help="sobrepõe os candidatos da base")
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

    # A grade varre os três pesos; o resto da configuração vem da base, para que
    # o ponto escolhido seja reproduzível pelo servidor sem tradução.
    indice = args.indice or base.indice
    candidatos = args.candidatos if args.candidatos is not None else base.busca.candidatos
    args.candidatos = candidatos

    embedder = Embedder(args.modelo or base.modelo, threads=args.threads)
    store = Store(indice, embedder.dim)
    estat = store.estatisticas()
    if not estat["chunks"]:
        log.error("índice vazio em %s", indice)
        return 2

    implicito = args.golden is None and base.dourado is None
    try:
        dourado, aviso = resolver_dourado(args.golden or base.dourado or GOLDEN, implicito=implicito)
    except FileNotFoundError as erro:
        log.error("%s", erro)
        return 2
    if aviso:
        log.warning("%s", aviso)
    perguntas = carregar_perguntas(dourado)
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
        pontos = varrer(store, embedder, perguntas, args.candidatos)
    finally:
        store.fechar()

    escolhido = REGRA(pontos)
    contexto = (
        f"{len(pontos[0].resultado.itens)} perguntas no escopo, "
        f"{estat['documentos']} documentos, {estat['chunks']} chunks, "
        f"modelo `{embedder.model_id}`, {args.candidatos} candidatos por ranking."
    )
    relatorio = render(pontos, escolhido, contexto)

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
