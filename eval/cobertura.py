"""Quanto do índice o conjunto dourado consegue alcançar — e o que ele nunca vê.

Um relatório de recuperação diz `recall@1 0,551` e o tamanho do índice. Quem lê
entende "é a precisão do sistema neste acervo". Não é: é a precisão sobre o
pedaço do acervo que as perguntas tocam, e sobre esse pedaço só. O resto do
índice entra na medição **como distrator e nunca como resposta**.

A consequência é assimétrica e silenciosa, e este repositório já a pagou: em
24/08/2026 as 51 perguntas de então apontavam para uma pasta de trinta, 18,2% dos
documentos, e quando `Meetings/` entrou no índice o recall@5 caiu 0,039 sem que
nada tivesse ficado pior (`docs/dourado-cobertura.md`). **Crescer o corpus só
podia piorar a métrica.**

Aquele número foi medido à mão e envelheceu duas vezes em quatro dias — o
`ROADMAP.md` guarda 18,2%, o `docs/dourado-cobertura.md` guarda 25%, e nenhum dos
dois é o de hoje. Cobertura escrita à mão em documento é a mesma classe de
defeito que `docs/duas-falhas-silenciosas.md` descreve: o silêncio parece
sucesso. Por isso ela passa a ser **calculada a cada passada e impressa no
relatório**, ao lado da métrica que ela qualifica.

## Dois números, porque a verdade está entre eles

- **Alcance por pasta** — a fração dos documentos que mora numa pasta de topo com
  ao menos uma pergunta. É **teto generoso**: uma pasta de 491 documentos com uma
  pergunta conta inteira.
- **Fontes** — a fração dos documentos que é, de fato, resposta esperada de alguma
  pergunta. É **piso exato**.

Nenhum dos dois sozinho é honesto. O primeiro sugere cobertura que não existe; o
segundo sugere que só o documento-fonte importa, quando a vizinhança dele é o que
torna a pergunta difícil. O relatório mostra os dois e diz que a leitura fica no
meio.

## O que isto não é

Não é porta e não reprova nada. Cobertura baixa é **limitação declarada**, não
erro: no começo de qualquer base ela é baixa por construção, e um instrumento que
reprovasse a primeira medição de todo mundo seria desligado no primeiro dia. O
que ele impede é o número sair sem a limitação junto.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

RAIZ = "(raiz)"
"""Rótulo do documento solto na raiz da árvore — ele não tem pasta de topo."""

ALVO = 0.5
"""A saída declarada da `F4-D` no `ROADMAP.md`: cobertura acima de metade do índice.

Serve para marcar o relatório, não para reprovar a passada. O limite é arbitrário
de propósito, como o de `test_maioria_das_perguntas_continua_no_escopo`: existe
para forçar uma conversa quando alguém for ler o número, não para validar o que
já está lá."""

MAX_PASTAS_LISTADAS = 8
"""Quantas pastas descobertas o relatório nomeia, da maior para a menor.

Trinta linhas de pasta viram ruído que se aprende a pular — junto com a linha que
importava. As demais entram somadas."""


@dataclass(frozen=True)
class Pasta:
    """Uma pasta de topo do universo medido."""

    nome: str
    documentos: int
    fontes: int

    @property
    def coberta(self) -> bool:
        return self.fontes > 0


@dataclass(frozen=True)
class Cobertura:
    """O alcance de um conjunto dourado sobre um universo de documentos."""

    universo: int
    """Documentos que o recuperador consegue devolver."""

    pastas: tuple[Pasta, ...]
    """Ordenadas da maior para a menor, por número de documentos."""

    fontes: int
    """Fontes distintas citadas pelas perguntas — dentro **ou** fora do universo."""

    fontes_no_universo: int

    perguntas: int

    de_conteudo: bool
    """`True` quando o universo é "documento com trecho indexado"; `False` quando é
    "arquivo que existe em disco", que é o universo do baseline por nome.

    A distinção não é cosmética: existir não é ser legível, e uma cobertura de
    disco lida como cobertura de índice diria que um PDF digitalizado está
    coberto."""

    @property
    def documentos_cobertos(self) -> int:
        return sum(p.documentos for p in self.pastas if p.coberta)

    @property
    def pastas_cobertas(self) -> int:
        return sum(1 for p in self.pastas if p.coberta)

    @property
    def alcance(self) -> float:
        """Teto generoso: fração do universo em pasta com ao menos uma pergunta."""
        return self.documentos_cobertos / self.universo if self.universo else 0.0

    @property
    def fracao_de_fontes(self) -> float:
        """Piso exato: fração do universo que é resposta esperada de alguma pergunta."""
        return self.fontes_no_universo / self.universo if self.universo else 0.0

    @property
    def fontes_fora(self) -> int:
        """Fontes citadas que o universo não tem — pergunta que mede zero por falta de dado.

        `eval.harness.verificar_escopo` já grita cada uma no log. Aqui elas entram
        porque log rola e relatório fica: quem lê o número seis meses depois não
        tem o log."""
        return self.fontes - self.fontes_no_universo

    @property
    def documentos_so_distrator(self) -> int:
        return self.universo - self.documentos_cobertos


def _topo(path: str) -> str:
    cabeca, sep, _ = path.replace("\\", "/").partition("/")
    return cabeca if sep else RAIZ


def medir(universo: Iterable[str], perguntas: Sequence, *, de_conteudo: bool = True) -> Cobertura:
    """Cobertura de um conjunto dourado sobre um universo de documentos.

    `perguntas` é qualquer sequência de objetos com `.fontes` — as `Pergunta` do
    harness. Não filtra por escopo de propósito: uma pergunta excluída da métrica
    continua declarando qual pedaço do acervo alguém já quis medir, e escondê-la
    aqui faria a cobertura parecer menor do que o conjunto pretende.
    """
    docs = set(universo)
    fontes = {f for p in perguntas for f in p.fontes}

    por_pasta: dict[str, int] = {}
    for d in docs:
        pasta = _topo(d)
        por_pasta[pasta] = por_pasta.get(pasta, 0) + 1

    fontes_por_pasta: dict[str, int] = {}
    for f in fontes:
        pasta = _topo(f)
        fontes_por_pasta[pasta] = fontes_por_pasta.get(pasta, 0) + 1

    # Maior primeiro, e a raiz por último entre as de mesmo tamanho: ela não é
    # uma pasta do acervo, é o resto que não caiu em nenhuma.
    pastas = tuple(
        sorted(
            (Pasta(nome, n, fontes_por_pasta.get(nome, 0)) for nome, n in por_pasta.items()),
            key=lambda p: (-p.documentos, p.nome == RAIZ, p.nome),
        )
    )
    return Cobertura(
        universo=len(docs),
        pastas=pastas,
        fontes=len(fontes),
        fontes_no_universo=len(fontes & docs),
        perguntas=len(perguntas),
        de_conteudo=de_conteudo,
    )


def bloco(cobertura: Cobertura | None) -> list[str]:
    """A seção de cobertura do relatório. `None` diz isso em voz alta.

    Devolver texto que confessa a ausência, em vez de nada, é o que impede a
    omissão silenciosa: um relatório sem a seção seria indistinguível de um
    relatório de conjunto que cobre o acervo inteiro.
    """
    linhas = ["## Cobertura do conjunto dourado", ""]
    if cobertura is None:
        linhas += [
            "**Não medida.** Este relatório não sabe que fração do acervo as perguntas",
            "alcançam, e a métrica acima **não** pode ser lida como precisão sobre o acervo",
            "inteiro. `py -m eval.cobertura --base <id>` mede.",
            "",
        ]
        return linhas

    c = cobertura
    universo = "documentos com trecho indexado" if c.de_conteudo else "arquivos enumerados em disco"
    marca = "" if c.alcance >= ALVO else f" ⚠ abaixo do alvo de {ALVO:.0%}"

    linhas += [
        f"{c.perguntas} perguntas apontam {c.fontes} fontes distintas sobre um universo de",
        f"**{c.universo} {universo}**, em {len(c.pastas)} pastas de topo. O que elas não",
        "alcançam não é erro; é limitação, e ela muda como a métrica acima se lê.",
        "",
        "| | | |",
        "|---|---:|---:|",
        f"| Alcance por pasta — teto generoso | {c.documentos_cobertos} de {c.universo} "
        f"| **{c.alcance:.1%}**{marca} |",
        f"| Fontes esperadas — piso exato | {c.fontes_no_universo} de {c.universo} "
        f"| {c.fracao_de_fontes:.1%} |",
        f"| Pastas de topo com ao menos uma pergunta | {c.pastas_cobertas} de {len(c.pastas)} | |",
        f"| Documentos que só podem competir como distrator | {c.documentos_so_distrator} | |",
        "",
        "O teto conta inteira a pasta que tem uma pergunta só; o piso conta apenas o",
        "documento que é resposta esperada. A leitura honesta fica entre os dois.",
        "",
    ]

    if c.fontes_fora:
        linhas += [
            f"**{c.fontes_fora} fonte(s) citada(s) não estão no universo.** A pergunta que",
            "depende delas mede zero por falta de dado, não por falha de ranqueamento, e some",
            "no meio da média. `eval.harness.verificar_escopo` nomeia cada uma no log.",
            "",
        ]

    descobertas = [p for p in c.pastas if not p.coberta]
    if descobertas:
        linhas += [
            f"### As {len(descobertas)} pastas sem pergunta nenhuma",
            "",
            "Cada documento aqui só pode piorar a métrica: entra na disputa como distrator e",
            "nunca como resposta. É por isso que crescer o corpus, com o dourado parado,",
            "**baixa** o número sem que nada tenha ficado pior.",
            "",
            "| Pasta | documentos | % do universo |",
            "|---|---:|---:|",
        ]
        for p in descobertas[:MAX_PASTAS_LISTADAS]:
            linhas.append(f"| `{p.nome}` | {p.documentos} | {p.documentos / c.universo:.1%} |")
        resto = descobertas[MAX_PASTAS_LISTADAS:]
        if resto:
            somados = sum(p.documentos for p in resto)
            linhas.append(f"| _outras {len(resto)} pastas_ | {somados} | {somados / c.universo:.1%} |")
        linhas.append("")

    return linhas


def main(argv: list[str] | None = None) -> int:
    """Cobertura do conjunto dourado de uma base, sem rodar busca nenhuma.

        py -m eval.cobertura --base padrao

    Não abre o modelo e não consulta o índice vetorial: lê o registro e o conjunto
    dourado. Custa segundos, e é o comando para quem acabou de escrever as dez
    primeiras perguntas do próprio acervo.
    """
    import argparse
    from pathlib import Path

    from segundocerebro.config import ErroDeConfig, carregar
    from segundocerebro.logger import get_logger

    from .harness import GOLDEN, carregar_perguntas, conferir_base, entregar, resolver_dourado

    log = get_logger("eval.cobertura")
    repo = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        prog="eval.cobertura",
        description="Que fração do índice o conjunto dourado consegue alcançar",
    )
    parser.add_argument("--base", help="qual base ler (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--out", type=Path, help="grava o bloco markdown em vez de imprimir")
    args = parser.parse_args(argv)

    try:
        conf = carregar(args.config, raiz=repo)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    implicito = args.golden is None and base.dourado is None
    try:
        caminho, aviso = resolver_dourado(args.golden or base.dourado or GOLDEN, implicito=implicito)
    except FileNotFoundError as erro:
        log.error("%s", erro)
        return 2
    if aviso:
        log.warning("%s", aviso)
    perguntas = carregar_perguntas(caminho)
    try:
        conferir_base(perguntas, base.id)
    except ValueError as erro:
        log.error("%s", erro)
        return 2

    from segundocerebro.index.embeddings import Embedder
    from segundocerebro.index.store import IndiceEmEscrita, Store, recusar_se_indexando

    try:
        recusar_se_indexando(Path(base.indice))
    except IndiceEmEscrita as erro:
        log.error("%s", erro)
        return 4
    # `lazy=True` pelo mesmo motivo de `eval.idioma`: a dimensão vem do catálogo e
    # este comando não embedda nada.
    store = Store(Path(base.indice), Embedder(base.modelo, lazy=True).dim)
    try:
        cobertura = medir(store.paths_com_chunks(), perguntas)
    finally:
        store.fechar()

    # `entregar` e não `print`: o bloco tem `⚠`, e o console do Windows nasce em
    # cp1252. A lição é de 24/08/2026 — `eval.latencia --porta` mediu por minutos
    # e morreu ao imprimir uma seta.
    entregar("\n".join(bloco(cobertura)), args.out)
    if args.out:
        log.info("cobertura gravada em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
