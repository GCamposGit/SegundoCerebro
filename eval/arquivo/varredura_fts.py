"""Varredura dos pesos de coluna do bm25 — `C3.a`, a primeira coisa da onda 2.

    py -m eval.arquivo.varredura_fts --base padrao --out docs/metricas-c3a-pesos-fts.md

**A pergunta.** Hoje o nome do arquivo pontua **duas vezes**: dentro do bm25,
pela coluna `caminho` do FTS5 com peso 1,0, e de novo na fusão, pelo
`RanqueadorDeNome` com peso 0,5. O mesmo sinal vota em dois ranqueadores que a
arquitetura trata como independentes — e a lição que se repetiu três vezes neste
acervo é que o valor da fusão está no **consenso de sinais de natureza
diferente** (`docs/ablacao-f2.md`). Dois votos do mesmo sinal não são consenso.

`C3.a` descreve esse mecanismo; `docs/dourado-cobertura.md` mediu o **efeito**:
nas perguntas de reunião, desligar o ranqueador de nome sobe o MRR 60%, e no
conjunto inteiro ele continua se pagando. Os dois documentos foram escritos sem
saber um do outro, e é a mesma coisa vista dos dois lados.

Daí a ordem da onda 2, registrada no `ROADMAP.md`: **se a dupla contagem explica
o efeito, a correção é mais barata e mais geral que um peso por tipo de fonte.**
Mais barata porque é um número na consulta e não uma classificação de documento
no caminho de ranking; mais geral porque acervo de nomes ruins (`IMG_2034.pdf`)
ganha do mesmo jeito, sem precisar saber o que é uma transcrição.

**O que esta varredura não é.** Não é a decisão de `F4-P`. É a medição que diz
se `F4-P` ainda precisa de peso por tipo de fonte. Com `n = 11` no grupo de
reunião, o resultado é hipótese — a mesma disciplina do item 4 de
`eval/varredura.py`, e pelo mesmo motivo.

**Custo.** Pesos de coluna do bm25 são de **consulta**: varrer não reindexa nada.
O reranking fica desligado na varredura inteira — 18 braços com cross-encoder
seriam horas por 3,4 pontos que não mudam de braço para braço.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import BuscaHibrida

from ..fonte import ESCRITORIO, REUNIAO
from ..idioma import CROSS_LINGUAL, MESMA_LINGUA
from ..harness import (
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
from ..memo import MemoDeBusca

log = get_logger("eval.varredura_fts")

REPO = Path(__file__).resolve().parent.parent

PESO_TEXTO = 1.0
"""A coluna `texto` fica fixa, e isso não perde ponto da grade.

`bm25()` do SQLite é **linear** nos pesos de coluna, e a fusão RRF ordena por
posição, não por score: multiplicar os três pesos por uma constante dá as mesmas
posições e a mesma fusão. Então basta um representante por razão distinta, que é
o mesmo argumento de canonização da grade de `eval/varredura.py`.

A única classe que fica fora é `texto = 0` — ignorar o corpo do documento e
ranquear só por nome e trilha. Isso não é afinação de busca lexical, é trocá-la
pelo baseline por nome, que já está medido desde a F0."""

PESOS_CAMINHO = (0.0, 0.3, 1.0)
"""Grade do complemento `C3.a`, sem invenção: zero, pouco e o padrão de hoje."""

PESOS_TRILHA = (0.5, 1.0)
"""Também do `C3.a`. A trilha (seção, aba, slide) é conteúdo, não nome — está na
grade para não confundir "baixar `caminho`" com "baixar tudo que não é `texto`"."""

PESOS_NOME = (0.0, 0.25, 0.5)
"""O peso do `RanqueadorDeNome` na fusão, que é metade da pergunta.

Varrer `caminho` sem varrer `nome` mediria uma perna da dupla contagem por vez e
não veria a interação — e a interação **é** a hipótese: se os dois votos são o
mesmo sinal, abaixar um deve poder ser compensado pelo outro. `0,5` é o padrão de
hoje, `0` é o braço que `docs/dourado-cobertura.md` já mediu no agregado, e
`0,25` existe para a superfície não ter só as pontas."""

REFERENCIA = (1.0, 1.0, 0.5)
"""`(trilha, caminho, nome)` da configuração que está no ar hoje.

Todo braço se lê contra este, e não contra o melhor da tabela: a pergunta é
"mudar compensa?", não "qual é o máximo?". O padrão de fábrica do FTS5 é 1/1/1 e
o `PESO_NOME` da fusão é 0,5."""

MINIMO_ARMADILHAS = 5
"""De 6, e é a porta 3 da F1 — não um critério novo inventado aqui.

`eval/varredura.py` exigia 4 porque varria antes de a porta fechar. Ela fechou
com 5 em 17/08/2026 (`docs/fechamento-f1.md`) e famílias de versão a mantiveram
em 5 (`docs/ablacao-familias.md`). Um braço que entregue 4 é regressão de porta
declarada, independente do que faça com a média."""


def grade() -> list[tuple[float, float, float]]:
    """Triplos `(trilha, caminho, nome)`. 18 braços, declarados antes de rodar."""
    return [(t, c, n) for c in PESOS_CAMINHO for t in PESOS_TRILHA for n in PESOS_NOME]


def margem(n: int) -> float:
    """Quanto de MRR vale **um caso** que sai do 3º para o 1º lugar, num grupo de `n`.

    A varredura escolhe olhando um grupo de ~11 perguntas, onde 0,02 de MRR é
    arredondamento e não achado. Em vez de um limiar redondo escolhido no
    abstrato — o erro que o teto de 25 documentos por identificador cometeu na
    `F4` — a margem é derivada do que se quer poder afirmar: *pelo menos uma
    pergunta mudou de lugar de verdade*.
    """
    return (1.0 - 1.0 / 3.0) / n if n else 0.0


@dataclass(frozen=True)
class Ponto:
    peso_trilha: float
    peso_caminho: float
    peso_nome: float
    resultado: Resultado

    @property
    def triplo(self) -> tuple[float, float, float]:
        return (self.peso_trilha, self.peso_caminho, self.peso_nome)

    @property
    def e_referencia(self) -> bool:
        return self.triplo == REFERENCIA

    @property
    def armadilhas(self) -> int:
        """Casos-armadilha resolvidos por inteiro no top-10 — contagem, como a porta."""
        return sum(1 for i in self.resultado.subgrupo(armadilha=True) if i.recall[10] == 1.0)

    @property
    def elegivel(self) -> bool:
        return self.armadilhas >= MINIMO_ARMADILHAS

    def mrr_do_grupo(self, grupo: str) -> float:
        return Resultado.mrr_de(self.resultado.subgrupo(grupo_de_fonte=grupo))

    def n_do_grupo(self, grupo: str) -> int:
        return len(self.resultado.subgrupo(grupo_de_fonte=grupo))

    def mrr_da_fatia(self, fatia: str) -> float:
        return Resultado.mrr_de(self.resultado.subgrupo(fatia=fatia))

    def n_da_fatia(self, fatia: str) -> int:
        return len(self.resultado.subgrupo(fatia=fatia))

    def recall5_da_fatia(self, fatia: str) -> float:
        return Resultado.recall_de(self.resultado.subgrupo(fatia=fatia), 5)

    @property
    def razao_cross_lingual(self) -> float:
        """recall@5 cross-lingual / mesma-língua — o critério de aceite de `C4.5`.

        Zero quando falta uma das duas fatias: sem as duas povoadas não há razão a
        calcular, e devolver 1,0 nesse caso faria a porta passar por ausência de
        medição, que é o modo de falha que `C4.5` existe para fechar.

        **Razão sobe também quando o denominador cai**, e aí não é melhora. Por
        isso o relatório imprime os dois recall@5 ao lado dela: uma razão que
        melhorou porque a fatia mesma-língua piorou é regressão disfarçada de
        avanço, e nenhuma coluna de razão sozinha distingue as duas."""
        mesma = self.recall5_da_fatia(MESMA_LINGUA)
        cross = self.recall5_da_fatia(CROSS_LINGUAL)
        return cross / mesma if mesma else 0.0


@dataclass(frozen=True)
class Veredito:
    """O que a varredura concluiu, incluindo a conclusão negativa."""

    escolhido: Ponto | None
    referencia: Ponto
    motivo: str


def REGRA(pontos: list[Ponto]) -> Veredito:  # noqa: N802 — é uma constante de decisão
    """Declarada antes de rodar, com a conclusão negativa declarada junto.

    Elegível é o braço que mantém a porta 3 (>= 5 de 6 armadilhas) **e** não
    perde MRR agregado contra a referência. Entre os elegíveis, ganha o maior MRR
    no grupo de reunião, e só se ganhar por mais de uma pergunta de verdade
    (`margem`). Empate decide pelo menor `caminho` e depois pelo menor `nome` —
    entre duas configurações que medem igual, a que depende menos da forma de
    superfície do nome é a que generaliza para o acervo de nomes ruins, que é o
    caso que `R6.1` vai encontrar.

    **Guarda cross-lingual, acrescentada em 24/08/2026 depois da primeira corrida.**
    Um braço não pode subir a média piorando a fatia `cross-lingual`. Dois dos três
    votos da fusão — bm25 e nome — são cegos a idioma por construção, então mexer no
    peso deles é exatamente o tipo de mudança que pode quebrar **só** a ponte PT↔EN;
    e a fatia mesma-língua é quatro vezes maior, então a média a esconderia. É a
    lacuna que `C4.5` fechou no harness, e não usá-la aqui seria ter construído a
    régua da onda 1 e medido sem ela. Vale como critério de elegibilidade, não como
    desempate: piorar a ponte desqualifica, não perde no critério de desempate.

    **Terceiro desempate, acrescentado em 24/08/2026 depois de a grade produzir um
    empate que a regra não sabia desfazer:** `trilha` mais perto da referência.
    A regra como declarada desempatava por `caminho` e `nome`, que são as duas
    pernas da dupla contagem — e ficou cega ao eixo que não faz parte da pergunta.
    Com `caminho` e `nome` iguais, dois braços de `trilha` 0,5 e 1,0 mediram o
    mesmo e a escolha caiu na ordem da grade, que não mede nada. Mexer num peso
    que mediu plano é mudança sem número, então o desempate passa a preferir **não
    mexer**. Isto não pode inverter conclusão nenhuma: só age entre braços já
    empatados no que a regra otimiza.

    **Se nada passa, a hipótese de `C3.a` está refutada neste acervo** e `F4-P`
    segue para o peso por tipo de fonte com um braço a menos para testar. Isso é
    resultado, não falha da varredura: declarar o que conta como "não" antes de
    ver a tabela é o que impede a tabela de escolher sozinha.
    """
    referencia = next(p for p in pontos if p.e_referencia)
    alvo = referencia.mrr_do_grupo(REUNIAO)
    limite = alvo + margem(referencia.n_do_grupo(REUNIAO))

    # Peneira em etapas, e não uma compreensão só, porque o relatório tem de dizer
    # **qual** critério eliminou os candidatos. A primeira versão listava dois
    # critérios numa mensagem fixa e passou a mentir no dia em que a guarda
    # cross-lingual entrou como terceiro: o veredito dizia "não mantém a porta 3 e
    # o agregado" sobre braços que mantinham os dois e perdiam a ponte PT↔EN.
    outros = [p for p in pontos if not p.e_referencia]
    passam_porta = [p for p in outros if p.elegivel]
    passam_agregado = [p for p in passam_porta if p.resultado.mrr() >= referencia.resultado.mrr()]
    elegiveis = [
        p
        for p in passam_agregado
        if p.mrr_da_fatia(CROSS_LINGUAL) >= referencia.mrr_da_fatia(CROSS_LINGUAL)
    ]
    candidatos = [p for p in elegiveis if p.mrr_do_grupo(REUNIAO) >= limite]
    if not candidatos:
        if not passam_porta:
            motivo = f"nenhum braço mantém a porta 3 ({MINIMO_ARMADILHAS} de 6 armadilhas)"
        elif not passam_agregado:
            motivo = (
                f"{len(passam_porta)} braços mantêm a porta 3 e nenhum deles mantém o MRR "
                f"agregado da referência ({referencia.resultado.mrr():.3f})"
            )
        elif not elegiveis:
            motivo = (
                f"{len(passam_agregado)} braços mantêm a porta 3 e o MRR agregado, e **todos "
                f"pioram a fatia cross-lingual** (referência {referencia.mrr_da_fatia(CROSS_LINGUAL):.3f})"
            )
        else:
            motivo = (
                f"{len(elegiveis)} braços passam os três critérios, e nenhum sobe o MRR de "
                f"reunião além da margem de uma pergunta ({limite - alvo:.3f})"
            )
        return Veredito(None, referencia, motivo)

    melhor = max(
        candidatos,
        key=lambda p: (
            p.mrr_do_grupo(REUNIAO),
            -p.peso_caminho,
            -p.peso_nome,
            -abs(p.peso_trilha - REFERENCIA[0]),
        ),
    )
    return Veredito(
        melhor,
        referencia,
        f"sobe o MRR de reunião de {alvo:.3f} para {melhor.mrr_do_grupo(REUNIAO):.3f} "
        f"sem perder o agregado",
    )


def varrer(store, embedder, perguntas, candidatos: int, glossario=None) -> list[Ponto]:  # noqa: ANN001
    pontos: list[Ponto] = []
    triplos = grade()
    for i, (peso_trilha, peso_caminho, peso_nome) in enumerate(triplos, start=1):
        colunas = (PESO_TEXTO, peso_trilha, peso_caminho)
        retriever = BuscaHibrida(
            store,
            embedder,
            candidatos=candidatos,
            usar_nome=bool(peso_nome),
            peso_nome=peso_nome,
            # O glossário vem junto de propósito: ele expande a consulta **para o
            # bm25 e para o nome** (o denso não recebe expansão), então varrer
            # peso de coluna sem ele mediria um ranqueador lexical que ninguém
            # roda, e sairia incomparável com F2 e F4.
            glossario=glossario,
            # `None` no braço de referência: é o `bm25(chunks_fts)` sem argumento,
            # o SQL que mediu F1 a F4. Passar (1,1,1) daria o mesmo número por um
            # caminho de código que ninguém mediu.
            pesos_fts=None if colunas == (1.0, 1.0, 1.0) else colunas,
        )
        resultado = avaliar(retriever, perguntas).restrito_ao_escopo()
        ponto = Ponto(peso_trilha, peso_caminho, peso_nome, resultado)
        pontos.append(ponto)
        log.info(
            "%2d/%d trilha=%.2f caminho=%.2f nome=%.2f | r@1 %.3f MRR %.3f "
            "MRR-reunião %.3f armadilhas %d/6",
            i,
            len(triplos),
            peso_trilha,
            peso_caminho,
            peso_nome,
            resultado.recall(1),
            resultado.mrr(),
            ponto.mrr_do_grupo(REUNIAO),
            ponto.armadilhas,
        )
    return pontos


def render(pontos: list[Ponto], veredito: Veredito, contexto: str) -> str:
    ref = veredito.referencia
    n_reuniao = ref.n_do_grupo(REUNIAO)
    n_escritorio = ref.n_do_grupo(ESCRITORIO)
    linhas = [
        "# Pesos de coluna do bm25 — `C3.a`, onda 2",
        "",
        contexto,
        "",
        "Grade, referência, porta e regra de escolha declaradas em `eval/varredura_fts.py`",
        "**antes** de rodar, com a conclusão negativa declarada junto: se nada passa, a",
        "hipótese está refutada neste acervo e `F4-P` segue para o peso por tipo de fonte.",
        "",
        "A pergunta é a dupla contagem do nome do arquivo: ele pontua dentro do bm25 pela",
        "coluna `caminho` **e** de novo na fusão pelo `RanqueadorDeNome`. Dois votos do",
        "mesmo sinal não são o consenso de sinais diferentes em que esta arquitetura aposta.",
        "",
        f"**Referência:** trilha {REFERENCIA[0]:g}, caminho {REFERENCIA[1]:g}, "
        f"nome {REFERENCIA[2]:g} — o que está no ar hoje. Todo braço se lê contra ela.",
        "",
        f"**Porta:** >= {MINIMO_ARMADILHAS} de 6 casos-armadilha no top-10 (a porta 3 da F1,",
        "não um critério novo). **Margem:** o ganho no grupo de reunião tem de valer ao",
        f"menos uma pergunta saindo do 3º para o 1º lugar — {margem(n_reuniao):.3f} de MRR",
        f"com n = {n_reuniao}.",
        "",
        "## A grade inteira",
        "",
        "Toda ela, não só o vencedor: superfície plana e superfície com pico levam a",
        "conclusões diferentes, e a média sozinha não distingue as duas.",
        "",
        "| trilha | caminho | nome | recall@1 | recall@5 | recall@10 | MRR@10 | nDCG@5 "
        f"| MRR reunião (n={n_reuniao}) | MRR escritório (n={n_escritorio}) "
        f"| MRR cross-lingual (n={ref.n_da_fatia(CROSS_LINGUAL)}) "
        f"| r@5 cross | r@5 mesma (n={ref.n_da_fatia(MESMA_LINGUA)}) | razão C4.5 "
        "| armadilhas | |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|",
    ]
    for p in sorted(pontos, key=lambda x: (-x.mrr_do_grupo(REUNIAO), x.peso_caminho)):
        marcas = []
        if p.e_referencia:
            marcas.append("**referência**")
        if veredito.escolhido is not None and p is veredito.escolhido:
            marcas.append("**←**")
        if not p.elegivel:
            marcas.append("porta")
        linhas.append(
            f"| {p.peso_trilha:g} | {p.peso_caminho:g} | {p.peso_nome:g} "
            f"| {p.resultado.recall(1):.3f} | {p.resultado.recall(5):.3f} "
            f"| {p.resultado.recall(10):.3f} "
            f"| {p.resultado.mrr():.3f} | {p.resultado.ndcg(k=5):.3f} "
            f"| {p.mrr_do_grupo(REUNIAO):.3f} | {p.mrr_do_grupo(ESCRITORIO):.3f} "
            f"| {p.mrr_da_fatia(CROSS_LINGUAL):.3f} "
            f"| {p.recall5_da_fatia(CROSS_LINGUAL):.3f} | {p.recall5_da_fatia(MESMA_LINGUA):.3f} "
            f"| {p.razao_cross_lingual:.2f} "
            f"| {p.armadilhas} de 6 | {' '.join(marcas)} |"
        )
    linhas += [
        "",
        "## Veredito",
        "",
    ]
    if veredito.escolhido is None:
        linhas += [
            f"**Nada passa.** {veredito.motivo}.",
            "",
            "Pela regra declarada, a hipótese de `C3.a` está refutada **neste acervo**: a",
            "dupla contagem existe no mecanismo e mexer nela não paga o preço aqui.",
            "",
            "Isto não absolve a dupla contagem num acervo de nomes ruins — só diz que este",
            "acervo, de nome informativo, não a sente. É a diferença que `R9.1` mede quando",
            "os perfis sintéticos existirem, e o motivo de o peso ficar na configuração em",
            "vez de virar constante.",
        ]
        if "cross-lingual" in veredito.motivo:
            linhas += [
                "",
                "**E o critério que eliminou os candidatos não é o da hipótese.** Braços que",
                "mantêm a porta 3 e sobem o MRR agregado existem, e todos pioram a ponte",
                "PT↔EN. Isso é achado próprio, não detalhe de regra: o ranqueador de nome é",
                "um sinal **agnóstico a idioma** — identificador, código, data e nome próprio",
                "no nome do arquivo casam igual nos dois idiomas, enquanto o bm25 não casa",
                "`contrato` com `agreement`. Baixar o peso do nome tira uma das poucas pontes",
                "que existem, e a fatia mesma-língua, quatro vezes maior, esconde a conta na",
                "média. `F4-P` herda uma troca de três lados, não de dois.",
            ]
    else:
        e = veredito.escolhido
        linhas += [
            f"**trilha {e.peso_trilha:g}, caminho {e.peso_caminho:g}, nome {e.peso_nome:g}** — "
            f"{veredito.motivo}.",
            "",
            "| | referência | escolhido | Δ |",
            "|---|---:|---:|---:|",
            f"| recall@1 | {ref.resultado.recall(1):.3f} | {e.resultado.recall(1):.3f} "
            f"| {e.resultado.recall(1) - ref.resultado.recall(1):+.3f} |",
            f"| MRR@{K_MRR} | {ref.resultado.mrr():.3f} | {e.resultado.mrr():.3f} "
            f"| {e.resultado.mrr() - ref.resultado.mrr():+.3f} |",
            f"| nDCG@5 | {ref.resultado.ndcg(k=5):.3f} | {e.resultado.ndcg(k=5):.3f} "
            f"| {e.resultado.ndcg(k=5) - ref.resultado.ndcg(k=5):+.3f} |",
            f"| MRR reunião | {ref.mrr_do_grupo(REUNIAO):.3f} | {e.mrr_do_grupo(REUNIAO):.3f} "
            f"| {e.mrr_do_grupo(REUNIAO) - ref.mrr_do_grupo(REUNIAO):+.3f} |",
            f"| MRR escritório | {ref.mrr_do_grupo(ESCRITORIO):.3f} "
            f"| {e.mrr_do_grupo(ESCRITORIO):.3f} "
            f"| {e.mrr_do_grupo(ESCRITORIO) - ref.mrr_do_grupo(ESCRITORIO):+.3f} |",
            f"| MRR cross-lingual | {ref.mrr_da_fatia(CROSS_LINGUAL):.3f} "
            f"| {e.mrr_da_fatia(CROSS_LINGUAL):.3f} "
            f"| {e.mrr_da_fatia(CROSS_LINGUAL) - ref.mrr_da_fatia(CROSS_LINGUAL):+.3f} |",
            f"| razão C4.5 (recall@5 cross / mesma) | {ref.razao_cross_lingual:.2f} "
            f"| {e.razao_cross_lingual:.2f} "
            f"| {e.razao_cross_lingual - ref.razao_cross_lingual:+.2f} |",
            f"| armadilhas | {ref.armadilhas} de 6 | {e.armadilhas} de 6 | |",
            "",
            "Como aplicar, sem tocar em `[padrao]` (que é compartilhado com o desktop):",
            "",
            "```toml",
            "[base.pesos]",
            f"nome = {e.peso_nome:g}",
            f"fts_trilha = {e.peso_trilha:g}",
            f"fts_caminho = {e.peso_caminho:g}",
            "```",
            "",
            "É peso de **consulta**: não reindexa nada.",
        ]
    linhas += [
        "",
        "## O que este número não decide",
        "",
        f"O grupo de reunião tem n = {n_reuniao}. Isso é sinal, não decisão — a mesma",
        "ressalva do item 4 de `eval/varredura.py`. A escolha vale como **hipótese** para",
        "`F4-P`, que a confirma medindo o conjunto inteiro por grupo de fonte, e para",
        "`R6.1`, onde estes dois pesos entram na grade do autotune em vez de virarem",
        "constante nova.",
        "",
    ]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="id da base em config.toml")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", help="sobrepõe o modelo da base")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--candidatos", type=int, help="sobrepõe os candidatos da base")
    parser.add_argument(
        "--glossario",
        type=Path,
        help="dicionário de siglas; sem ele a varredura não é comparável com F2 e F4",
    )
    parser.add_argument(
        "--sem-memo",
        action="store_true",
        help="desliga o memo de busca (auditoria: 18 braços contra o índice de verdade)",
    )
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

    indice = args.indice or base.indice
    candidatos = args.candidatos if args.candidatos is not None else base.busca.candidatos

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

    from segundocerebro.retrieve.glossario import Glossario

    caminho_glossario = args.glossario or base.glossario
    glossario = Glossario.de_arquivo(caminho_glossario) if caminho_glossario else Glossario.vazio()
    if caminho_glossario is None:
        log.warning(
            "sem glossário: a tabela não é comparável com as medições de F2 e F4, "
            "que rodaram com --glossario"
        )

    memo = None if args.sem_memo else MemoDeBusca(store, embedder)
    try:
        if memo is None:
            pontos = varrer(store, embedder, perguntas, candidatos, glossario)
        else:
            pontos = varrer(memo.store, memo.embedder, perguntas, candidatos, glossario)
            log.info("%s", memo.resumo())
    finally:
        store.fechar()

    veredito = REGRA(pontos)
    contexto = (
        f"{len(pontos[0].resultado.itens)} perguntas no escopo, "
        f"{estat['documentos']} documentos, {estat['chunks']} chunks, "
        f"modelo `{embedder.model_id}`, {candidatos} candidatos por ranking, "
        f"glossário {'`' + Path(caminho_glossario).name + '`' if caminho_glossario else '**ausente**'}, "
        "reranking desligado nos 18 braços."
    )
    relatorio = render(pontos, veredito, contexto)

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
