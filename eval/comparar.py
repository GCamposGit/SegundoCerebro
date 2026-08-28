"""Compara duas configurações pergunta a pergunta — a porta 5 da F1.

    py -m eval.comparar --antes baseline --depois hibrido --out docs/regressao-f1.md

A porta 5 do ROADMAP é **orçamento de regressão**, não regressão zero: "nenhuma
regressão em caso crítico, no máximo 3 perguntas caindo do 1º lugar, e cada uma
inspecionada individualmente". Isso não é avaliável a partir de duas médias — é
preciso saber *quais* perguntas se moveram e para onde.

O motivo de a porta ser assim, e não "zero regressão": uma mudança que melhora
trinta perguntas e piora uma seria reprovada, o que é o trade-off errado. Mas o
oposto — olhar só a média — deixa passar a mudança que sobe 0,02 no agregado
escondendo que a pergunta mais difícil do conjunto deixou de ser respondida.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.config import ErroDeConfig, carregar
from segundocerebro.index.embeddings import MODELO_PADRAO
from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import CANDIDATOS
from segundocerebro.retrieve.rerank import CANDIDATOS_PARA_RERANK

from .estatistica import EMPATE, GANHA, N_MINIMO, PERDE, alinhar, ic_do_delta
from .harness import (
    K_MRR,
    Resultado,
    ResultadoPergunta,
    avaliar,
    carregar_perguntas,
    conferir_base,
    entregar,
    resolver_dourado,
)

log = get_logger("eval.comparar")

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"

MAX_QUEDAS_DO_PRIMEIRO = 3
"""Orçamento da porta 5. Acima disso a mudança não entra sem justificativa caso a caso."""


@dataclass(frozen=True)
class Movimento:
    id: str
    tipo: str
    pergunta: str
    armadilha: bool
    autoria: str
    antes: int | None
    """Posição do primeiro acerto, ou None se não achou em nenhuma posição."""
    depois: int | None

    @property
    def delta(self) -> str:
        def rot(p: int | None) -> str:
            return str(p) if p else "—"

        return f"{rot(self.antes)} → {rot(self.depois)}"

    @property
    def melhorou(self) -> bool:
        return _rank(self.depois) < _rank(self.antes)

    @property
    def piorou(self) -> bool:
        return _rank(self.depois) > _rank(self.antes)

    @property
    def caiu_do_primeiro(self) -> bool:
        return self.antes == 1 and self.depois != 1

    @property
    def perdeu_de_vez(self) -> bool:
        """Estava em alguma posição e sumiu do ranking inteiro."""
        return self.antes is not None and self.depois is None


def _rank(posicao: int | None) -> float:
    """Sem acerto vale infinito, para comparar sem tratar None caso a caso."""
    return float("inf") if posicao is None else float(posicao)


def comparar(antes: Resultado, depois: Resultado) -> list[Movimento]:
    por_id: dict[str, ResultadoPergunta] = {i.pergunta.id: i for i in antes.itens}
    movimentos: list[Movimento] = []
    for d in depois.itens:
        a = por_id.get(d.pergunta.id)
        if a is None:
            continue
        movimentos.append(
            Movimento(
                id=d.pergunta.id,
                tipo=d.pergunta.tipo,
                pergunta=d.pergunta.pergunta,
                armadilha=d.pergunta.armadilha,
                autoria=d.pergunta.autoria,
                antes=a.posicao_primeiro_acerto,
                depois=d.posicao_primeiro_acerto,
            )
        )
    return movimentos


def _recortes(depois: Resultado) -> list[tuple[str, list[str]]]:
    """Os recortes em que o Δ é medido, e os ids de cada um.

    Os ids saem do braço `depois` porque é ele que está sendo julgado; o
    pareamento por id em `alinhar()` descarta quem não estiver nos dois lados.
    """
    def ids(itens: Sequence[ResultadoPergunta]) -> list[str]:
        return [i.pergunta.id for i in itens]

    no_escopo = depois.restrito_ao_escopo()
    recortes: list[tuple[str, list[str]]] = [("**conjunto no escopo**", ids(no_escopo.itens))]
    recortes += [(f"idioma · {rot}", ids(itens)) for rot, itens in no_escopo.por_fatia()]
    recortes += [(f"fonte · {rot}", ids(itens)) for rot, itens in no_escopo.por_grupo_de_fonte()]
    # A interseção dos dois eixos, e não só as margens: um pacote pode subir o
    # grupo e derrubar dentro dele a fatia que dependia do sinal mexido. Ver
    # `Resultado.por_grupo_e_fatia`.
    recortes += [(f"fonte ∩ idioma · {rot}", ids(itens)) for rot, itens in no_escopo.por_grupo_e_fatia()]
    return recortes


def _insensivel(antes: Resultado, depois: Resultado, ids: Sequence[str]) -> bool:
    """Os dois braços devolveram o **mesmo ranking** em toda pergunta deste recorte?

    Δ zero tem duas causas que a tabela não distinguia, e elas pedem decisões
    opostas:

    - **empate** — a mudança agiu e o efeito não se separa do ruído. A regra de
      encerramento se aplica: não adota, encerra o pacote;
    - **insensibilidade** — a variável manipulada não toca nenhum documento
      desta fatia, então o Δ é zero **por construção**. Aqui a regra de
      encerramento não se aplica: não houve medição, e fechar como "hipótese
      refutada" registra uma conclusão que o dado não sustenta.

    Medido na `F4-P.1` em 27/08/2026: a fatia `reunião` da camada 2 tem n=100, e
    o ranqueador de nome **não pontua um único documento de reunião** naquele
    corpus — os nomes gerados (`Ata reuniao ATA-000.txt`, `Gravacao_<data>.vtt`)
    não casam com as consultas. Zerar o peso do nome ali não tinha em que agir. A
    tabela dizia `➖ empate` em todas as células, e a regra declarada mandaria
    fechar o pacote como refutado.

    Compara o **ranking recuperado**, e não a métrica: dois braços podem trocar
    documentos fora do alcance da fonte esperada e mover métrica nenhuma. Ranking
    igual em todas as perguntas é a única evidência de que não houve manipulação.
    """
    alvo = set(ids)
    a = {i.pergunta.id: tuple(i.recuperados) for i in antes.itens if i.pergunta.id in alvo}
    d = {i.pergunta.id: tuple(i.recuperados) for i in depois.itens if i.pergunta.id in alvo}
    comuns = a.keys() & d.keys()
    return bool(comuns) and all(a[i] == d[i] for i in comuns)


def _tabela_de_delta(antes: Resultado, depois: Resultado) -> list[str]:
    """Δ pareado com IC95, por recorte — o pacote `E5`.

    É esta tabela, e não a de posições acima, que a regra de adoção consulta.
    As duas medem coisas diferentes de propósito: a de posições responde "quais
    perguntas se moveram e para onde", que é a porta 5; esta responde "o
    movimento agregado é distinguível de sorte", que é `E5.2`. Uma mudança pode
    passar na porta 5 e empatar aqui — e nesse caso não entra, porque empate
    resolve por simplicidade.
    """
    linhas = [
        "## Δ pareado com IC95 — a regra de adoção",
        "",
        "Bootstrap **pareado** (`eval/estatistica.py`): as duas configurações respondem as",
        "mesmas perguntas, então a reamostragem sorteia **perguntas**, não medições soltas,",
        "e o intervalo aproveita a correlação entre os braços. É por isso que ele é bem mais",
        "estreito que os intervalos de braço isolado do relatório de `eval.rodar` — e é por",
        "isso que comparar aqueles dois intervalos para concluir empate estaria errado.",
        "",
        "**A regra (`E5.2`):** a mudança ganha na fatia que ela mira se o IC95 do Δ **exclui",
        "zero**. Empate estatístico resolve por simplicidade — não adotar. Fatia com",
        f"n < {N_MINIMO} vai marcada com `⚠`: o intervalo dela é honesto e larguíssimo, e uma",
        "decisão tomada só ali é uma decisão tomada no ruído.",
        "",
        f"| Recorte | n | Δ recall@1 | | Δ MRR@{K_MRR} | | Δ nDCG@5 | |",
        "|---|---:|:---:|:--:|:---:|:--:|:---:|:--:|",
    ]
    marca = {GANHA: "✅", PERDE: "❌", EMPATE: "➖"}
    insensiveis: list[str] = []
    for rotulo, ids_do_recorte in _recortes(depois):
        if not ids_do_recorte:
            linhas.append(f"| {rotulo} | 0 | — | | — | | — | |")
            continue
        alvo = set(ids_do_recorte)
        cego = _insensivel(antes, depois, ids_do_recorte)
        if cego:
            insensiveis.append(rotulo)
        celulas = []
        n = 0
        for metrica, k in (("recall", 1), ("mrr", K_MRR), ("ndcg", 5)):
            a_serie = {i: v for i, v in antes.serie(metrica, k).items() if i in alvo}
            d_serie = {i: v for i, v in depois.serie(metrica, k).items() if i in alvo}
            a, d, comuns = alinhar(a_serie, d_serie)
            delta = ic_do_delta(a, d)
            n = len(comuns)
            # `∅` e não `➖`: nesta fatia os dois braços são o mesmo ranking, então
            # não houve o que empatar. Ver `_insensivel`.
            celulas.append(f"{delta} | {'∅' if cego else marca[delta.veredito]}")
        aviso = " ⚠" if n < N_MINIMO else ""
        linhas.append(f"| {rotulo}{aviso} | {n} | " + " | ".join(celulas) + " |")
    linhas.append("")

    if insensiveis:
        todas = len(insensiveis) == len([r for r, ids in _recortes(depois) if ids])
        linhas.append(
            "**`∅` — fatia insensível, e isto não é empate.** Nestas os dois braços "
            "devolveram **exatamente o mesmo ranking em todas as perguntas**: a variável "
            "manipulada não toca nenhum documento da fatia, e o Δ é zero por construção. "
            "A regra de encerramento (`empate encerra o pacote com \"hipótese refutada\"`) "
            "**não se aplica** aqui — não houve medição do efeito, e registrar refutação "
            "seria concluir do que o dado não diz. O que falta é instrumento, não veredito: "
            + ", ".join(f"`{r}`" for r in insensiveis[:8])
            + ("…" if len(insensiveis) > 8 else "")
            + "."
        )
        if todas:
            linhas.append("")
            linhas.append(
                "> **Nenhum recorte foi sensível: esta comparação não mediu nada.** Os dois "
                "braços produziram rankings idênticos em todo o conjunto. Antes de reportar "
                "qualquer veredito, conferir que a bandeira do braço chega ao recuperador **e** "
                "que a variável manipulada age sobre os documentos desta base."
            )
        linhas.append("")

    geral_a = antes.restrito_ao_escopo()
    geral_d = depois.restrito_ao_escopo()
    a, d, _ = alinhar(geral_a.serie("mrr", K_MRR), geral_d.serie("mrr", K_MRR))
    delta = ic_do_delta(a, d)
    linhas.append(
        f"No conjunto inteiro o Δ de MRR é **{delta}** com n={delta.n}, veredito "
        f"**{delta.veredito}**."
    )
    if not delta.exclui_zero:
        linhas.append("")
        linhas.append(
            "O intervalo cruza zero: pela regra declarada esta mudança **não é adotada pelo "
            "agregado**. Se ela existe para uma fatia específica, é o veredito daquela fatia "
            "que decide — e ele tem de estar declarado **antes** de olhar a tabela, senão a "
            "escolha da fatia vira a própria conclusão."
        )
    linhas.append("")
    return linhas


def render(
    movimentos: list[Movimento],
    nome_antes: str,
    nome_depois: str,
    contexto: str,
    antes: Resultado | None = None,
    depois: Resultado | None = None,
) -> str:
    """A porta 5 pergunta a pergunta, e — quando os dois `Resultado` vierem — o Δ do `E5`.

    Os dois últimos são opcionais para não quebrar quem já chamava com quatro
    argumentos, e porque a tabela de posições continua legível sozinha. Quando
    vêm, a tabela de Δ entra logo depois do veredito da porta."""
    pioraram = [m for m in movimentos if m.piorou]
    melhoraram = [m for m in movimentos if m.melhorou]
    quedas = [m for m in movimentos if m.caiu_do_primeiro]
    perdidas = [m for m in movimentos if m.perdeu_de_vez]
    criticas = [m for m in pioraram if m.armadilha]

    passou = not criticas and len(quedas) <= MAX_QUEDAS_DO_PRIMEIRO

    linhas = [
        "# Regressão pergunta a pergunta — porta 5 da F1",
        "",
        contexto,
        "",
        f"- **antes:** {nome_antes}",
        f"- **depois:** {nome_depois}",
        f"- posição do primeiro acerto; `—` significa não achado em nenhuma posição",
        "",
        "## Veredito",
        "",
        f"| Critério | Limite | Medido | |",
        "|---|---:|---:|:--:|",
        f"| regressão em caso-armadilha | 0 | {len(criticas)} | {'✅' if not criticas else '❌'} |",
        f"| perguntas caindo do 1º lugar | {MAX_QUEDAS_DO_PRIMEIRO} | {len(quedas)} "
        f"| {'✅' if len(quedas) <= MAX_QUEDAS_DO_PRIMEIRO else '❌'} |",
        f"| perguntas que sumiram do ranking | — | {len(perdidas)} | |",
        "",
        f"**Porta 5: {'passa' if passou else 'não passa'}.** "
        f"{len(melhoraram)} perguntas melhoraram, {len(pioraram)} pioraram, "
        f"{len(movimentos) - len(melhoraram) - len(pioraram)} ficaram iguais.",
        "",
    ]

    if antes is not None and depois is not None:
        linhas += _tabela_de_delta(antes, depois)

    for titulo, grupo, vazio in (
        ("Pioraram", sorted(pioraram, key=lambda m: (-_rank(m.depois), m.id)), "Nenhuma."),
        ("Melhoraram", sorted(melhoraram, key=lambda m: (_rank(m.depois), m.id)), "Nenhuma."),
    ):
        linhas.append(f"## {titulo} — {len(grupo)}")
        linhas.append("")
        if not grupo:
            linhas.append(vazio)
            linhas.append("")
            continue
        linhas.append("| id | tipo | posição | marcas | pergunta |")
        linhas.append("|---|---|---:|---|---|")
        for m in grupo:
            marcas = " ".join(
                x
                for x in (
                    "**armadilha**" if m.armadilha else "",
                    "usuário" if m.autoria == "usuario" else "",
                    "sumiu" if m.perdeu_de_vez else "",
                )
                if x
            )
            linhas.append(f"| {m.id} | {m.tipo} | {m.delta} | {marcas} | {m.pergunta} |")
        linhas.append("")

    return "\n".join(linhas)


def _montar(nome: str, args, cfg, papel: str = "depois"):  # noqa: ANN001
    """Um recuperador a partir do nome curto usado na linha de comando.

    O arremedo de `Args` tem de carregar **todos** os campos que `rodar._montar`
    lê, e essa lista cresceu com as fases. Em 24/08/2026 faltavam quatro
    (`base_cfg`, `glossario`, `rerank`, `sem_rerank`) e `eval.comparar` levantava
    `AttributeError` em qualquer recuperador que não fosse o baseline — a
    ferramenta da **porta 5** não rodava desde o bloco A da F3.5. Nenhum teste
    pegou porque todos montam `Resultado` à mão e nunca passam por aqui.

    Daí o `_CAMPOS_DE_MONTAGEM` logo abaixo, e o teste que confere a lista contra
    o que `rodar._montar` de fato usa: a próxima fase que acrescentar um campo
    quebra o teste em vez de quebrar a porta."""
    from .rodar import _montar as montar_rodar

    # `--rerank-depois` é o que dá o braço **assimétrico**, e sem ele o pacote
    # não consegue medir a ablação mais óbvia que existe: "esta feature vale a
    # pena?". `--rerank` liga nos dois braços e serve ao caso oposto — segurar o
    # reranking constante enquanto se compara outra coisa.
    rerank = args.rerank
    if args.rerank_depois is not None:
        rerank = args.rerank_depois if papel == "depois" else None
    sem_rerank = args.sem_rerank or (args.rerank_depois is not None and papel == "antes")

    class Args:
        retriever = nome
        base_cfg = args.base_cfg
        prefixo = args.prefixo
        indice = args.indice
        modelo = args.modelo
        threads = args.threads
        candidatos = args.candidatos
        sem_nome = False
        peso_denso = args.peso_denso
        peso_nome = args.peso_nome
        glossario = args.glossario

    # `--peso-nome-depois` é a irmã de `--rerank-depois`, e existe pela mesma
    # razão: a ablação mais óbvia que existe é "este sinal vale a pena?", e ela
    # precisa de **um** braço mudado. A `F4-P` é o caso que a pediu — o sinal de
    # nome não existia em `buscar_chunks`, então o braço "antes" é `peso_nome = 0`
    # no mesmo código, e não uma versão anterior do código.
    if args.peso_nome_depois is not None:
        Args.peso_nome = args.peso_nome_depois if papel == "depois" else 0.0
        Args.sem_nome = papel == "antes"

    Args.rerank = rerank
    Args.sem_rerank = sem_rerank
    montado = montar_rodar(Args(), cfg)

    # `--entregue` tem de existir aqui, e não só em `eval.rodar`, pelo motivo que
    # criou o `F4-P.0`: a ferramenta que decide adoção precisa medir o caminho que
    # o cliente executa. Sem isto a porta 5 e o Δ do `E5` mediriam `search`
    # enquanto a `F4-P` muda `buscar_chunks` — mesma classe de erro, um nível
    # acima. Envolve **os dois braços**: comparar caminho entregue contra `search`
    # misturaria a mudança com a diferença entre os caminhos.
    if getattr(args, "entregue", False):
        from .entregue import CaminhoEntregue

        retriever, titulo, contexto, store, universo = montado
        return CaminhoEntregue(interno=retriever), titulo, contexto, store, universo
    return montado


_CAMPOS_DE_MONTAGEM = frozenset(
    {
        "retriever", "base_cfg", "prefixo", "indice", "modelo", "threads",
        "candidatos", "sem_nome", "peso_denso", "peso_nome", "glossario",
        "rerank", "sem_rerank",
    }
)
"""O contrato entre `_montar` daqui e `rodar._montar`, conferido em teste."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.comparar", description="Compara duas configurações")
    parser.add_argument("--antes", default="baseline", choices=("baseline", "hibrido", "denso", "bm25"))
    parser.add_argument("--depois", default="hibrido", choices=("baseline", "hibrido", "denso", "bm25"))
    parser.add_argument("--base", help="qual base comparar (ver config.toml)")
    parser.add_argument("--config", type=Path, default=REPO / "census.toml")
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--indice", type=Path, default=None)
    parser.add_argument("--glossario", type=Path, help="dicionário de siglas, nos dois braços")
    parser.add_argument(
        "--rerank",
        nargs="?",
        const=CANDIDATOS_PARA_RERANK,
        type=int,
        help="liga o reranking nos dois braços, com N candidatos",
    )
    parser.add_argument(
        "--rerank-depois",
        nargs="?",
        const=CANDIDATOS_PARA_RERANK,
        type=int,
        help="liga o reranking **só no braço `depois`** — é a forma de medir a própria "
        "feature, e o que `--rerank` (que liga nos dois) não consegue expressar",
    )
    parser.add_argument(
        "--sem-rerank",
        action="store_true",
        help="desliga o reranking nos dois braços mesmo que a base o configure",
    )
    parser.add_argument(
        "--entregue",
        action="store_true",
        help="mede `buscar_chunks` (o que o cliente MCP recebe) nos dois braços, "
        "em vez do `search` de nível de documento — ver `eval/entregue.py`",
    )
    parser.add_argument("--modelo", default=MODELO_PADRAO)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--candidatos", type=int, default=CANDIDATOS)
    parser.add_argument("--peso-denso", type=float, default=None)
    parser.add_argument("--peso-nome", type=float, default=None)
    parser.add_argument(
        "--peso-nome-depois",
        type=float,
        default=None,
        help="braço assimétrico: `antes` fica sem ranqueador de nome e `depois` com "
        "este peso — a ablação do sinal de nome, sem trocar mais nada",
    )
    parser.add_argument(
        "--prefixo",
        help="recorta o baseline para a mesma subárvore do índice — obrigatório para "
        "comparar contra baseline sem misturar escala com qualidade",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    # `None` significa "o que a base configura", exatamente como em `eval.rodar`.
    # Até 24/08/2026 este ponto substituía `None` pelas constantes do módulo, e o
    # efeito era o defeito que `rodar._montar:88` já documenta com outro nome: a
    # porta 5 mediria pesos de fábrica contra uma base que configura outros. Com
    # os `fts_*` do `C3.a` e o que a `F4-P` vai mexer, isso mediria a configuração
    # errada exatamente quando mais importa.

    try:
        conf = carregar(args.config, raiz=REPO)
        args.base_cfg = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    cfg = args.base_cfg.censo()
    implicito = args.golden is None and args.base_cfg.dourado is None
    try:
        dourado, aviso = resolver_dourado(args.golden or args.base_cfg.dourado or GOLDEN, implicito=implicito)
    except FileNotFoundError as erro:
        log.error("%s", erro)
        return 2
    if aviso:
        log.warning("%s", aviso)
    todas = carregar_perguntas(dourado)
    try:
        conferir_base(todas, args.base_cfg.id)
    except ValueError as erro:
        log.error("%s", erro)
        return 2
    perguntas = [p for p in todas if p.no_escopo]
    log.info("%d perguntas no escopo", len(perguntas))

    resultados = {}
    contexto_partes = []
    for papel, nome in (("antes", args.antes), ("depois", args.depois)):
        retriever, _, contexto, store, _ = _montar(nome, args, cfg, papel)
        try:
            resultados[papel] = avaliar(retriever, perguntas)
        finally:
            if store is not None:
                store.fechar()
        log.info("%s: %s", papel, retriever.nome)
        contexto_partes.append(f"**{papel}** — {contexto.splitlines()[0]}")

    movimentos = comparar(resultados["antes"], resultados["depois"])
    relatorio = render(
        movimentos,
        resultados["antes"].retriever,
        resultados["depois"].retriever,
        f"{len(perguntas)} perguntas no escopo.\n\n" + "\n\n".join(contexto_partes),
        antes=resultados["antes"],
        depois=resultados["depois"],
    )

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
