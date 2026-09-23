"""Qual idioma um texto está — e o recorte cross-lingual que sai daí.

O acervo corporativo é bilíngue e ninguém tinha medido quanto: **275 dos 1.900
documentos com conteúdo estão em inglês**, e 23 dos 78 pares pergunta→fonte do
conjunto dourado cruzam idioma. Até 24/08/2026 esse terço do dourado era
invisível — uma regressão que só quebrasse a ponte PT→EN passaria com a média
agregada intacta.

O detector é de contagem de palavra funcional, sem dependência nova. Não é um
classificador de idioma de verdade e não precisa ser: as duas línguas deste
acervo são conhecidas e o que se pede dele é separar duas listas fechadas, não
identificar uma entre cem.

**Três resultados, não dois.** `indefinido` existe porque a alternativa é pior:
uma consulta de três palavras com duas siglas não tem evidência de idioma
nenhuma, e chutar `pt` porque o acervo é majoritariamente PT colocaria a
pergunta na fatia errada em silêncio. Sem evidência, o par não entra em fatia
alguma — aparece na coluna `não declarado`, com o n à vista.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PT = "pt"
EN = "en"
MISTO = "misto"
INDEFINIDO = "indefinido"

MESMA_LINGUA = "mesma-língua"
CROSS_LINGUAL = "cross-lingual"
NAO_DECLARADO = "não declarado"

FATIAS = (MESMA_LINGUA, CROSS_LINGUAL, NAO_DECLARADO)
"""Ordem de exibição no relatório. `não declarado` por último: é o resto."""

# Palavra funcional é o sinal certo aqui porque é o que **não** se traduz por
# empréstimo. Substantivo técnico viaja entre os dois idiomas ("compliance",
# "template", "budget" aparecem em documento PT); artigo, preposição e
# conjunção, não.
FUNCIONAIS_PT = frozenset("""
    a o as os um uma uns umas de do da dos das em no na nos nas
    por pelo pela pelos pelas para com sem sob sobre entre ate desde
    e ou mas porem porque pois que se quando onde como qual quais
    quanto quanta quantos quantas cujos cujas
    algum alguma alguns algumas nenhum nenhuma nenhuns nenhumas
    quem cujo cuja nao sim ja tambem apenas somente muito mais menos
    este esta estes estas esse essa esses essas aquele aquela isso isto
    seu sua seus suas nosso nossa dele dela deles delas
    ser sao foi eram era sera serao ter tem tinha havia haver deve devem
    podem pode fazer feito sido estao estava mesmo mesma cada todos so
    toda todas qualquer conforme segundo atraves durante apos antes
""".split())

FUNCIONAIS_EN = frozenset("""
    a an the of in on at to for from by with without within into onto
    and or but so if because while when where how what which who whom whose
    that this these those there their they them its it is are was were be been
    being have has had having do does did done not no yes also only just
    more most less least such than then thus shall should would could may might
    must can will each all any some other another between during after before as
    through upon per about above below over under
""".split())

AMBIGUAS = FUNCIONAIS_PT & FUNCIONAIS_EN
"""`a`, `do`, `no`, `as`, `so` — contam para ninguém.

Descontar as duas listas uma da outra é mais barato e mais honesto que dar peso:
uma palavra que existe nos dois idiomas não é evidência de nenhum, e mantê-la
com peso baixo só adiciona ruído proporcional ao tamanho do texto.

Duas entradas estão aqui por causa da **normalização**, não do vocabulário, e as
duas foram achadas por teste: `as` é tão inglês quanto português e faltava na
lista EN, o que fazia texto inglês longo pontuar PT; e `só` perde o acento em
`_palavras` e vira `so`, que é palavra funcional inglesa. Sem o desconto, o
português pontuaria para o inglês toda vez que dissesse "só"."""

MARCAS_PT = frozenset(FUNCIONAIS_PT - AMBIGUAS)
MARCAS_EN = frozenset(FUNCIONAIS_EN - AMBIGUAS)

# Grafemas que só o português usa entre os dois. Valem para o caso curto — uma
# pergunta de seis palavras pode não ter nenhuma funcional exclusiva e ainda
# assim ser inequivocamente PT por causa de um `ç` ou de um `ção`.
GRAFEMAS_PT = ("ç", "ã", "õ", "á", "â", "é", "ê", "í", "ó", "ô", "ú", "à")
SUFIXOS_PT = ("ção", "ções", "ável", "ível", "mente", "nh", "lh")

MINIMO_DE_EVIDENCIA = 2
"""Abaixo disto o texto é `indefinido`.

Um marcador só decide idioma por acidente: `the` numa citação dentro de um
documento PT, `de` num nome próprio dentro de um documento EN. Dois já exigem
que o acidente se repita."""

RAZAO_DE_DOMINIO = 1.5
"""Quanto um lado precisa superar o outro para o texto ser dele, e não `misto`.

1,5 e não 2,0 porque documento corporativo real cita o outro idioma o tempo
todo — anexo, cláusula de contrato, nome de norma. Exigir o dobro classificaria
como `misto` documento que qualquer leitor humano chamaria de português."""

TRECHO_MAXIMO = 6_000
"""Caracteres lidos por documento. O idioma não muda na página 40, e ler o
documento inteiro multiplicaria o custo da anotação por nada."""


def _palavras(texto: str) -> list[str]:
    """Minúsculas e sem acento — o acento é contado à parte, em `_grafemas`."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", sem_acento)


def _grafemas(texto: str) -> int:
    baixo = texto.lower()
    return sum(baixo.count(g) for g in GRAFEMAS_PT) + sum(baixo.count(s) for s in SUFIXOS_PT)


@dataclass(frozen=True)
class Deteccao:
    """O veredito e os dois números que o produziram.

    Os números ficam à vista de propósito: quando uma pergunta cai em
    `indefinido`, a dúvida seguinte é sempre "por pouco ou por muito", e um
    veredito sozinho não responde.
    """

    idioma: str
    pt: int
    en: int

    @property
    def evidencia(self) -> int:
        return self.pt + self.en


def detalhar(texto: str, *, trecho_maximo: int = TRECHO_MAXIMO) -> Deteccao:
    recorte = (texto or "")[:trecho_maximo]
    palavras = _palavras(recorte)
    pt = sum(1 for p in palavras if p in MARCAS_PT)
    en = sum(1 for p in palavras if p in MARCAS_EN)
    # Grafema exclusivo é evidência de PT, mas com teto: um documento longo tem
    # milhares de `ç`, e sem o teto o grafema sozinho decidiria todo texto longo,
    # inclusive um EN que cite dois nomes próprios portugueses.
    pt += min(_grafemas(recorte), max(2, len(palavras) // 20))
    if pt + en < MINIMO_DE_EVIDENCIA:
        idioma = INDEFINIDO
    elif pt >= en * RAZAO_DE_DOMINIO:
        idioma = PT
    elif en >= pt * RAZAO_DE_DOMINIO:
        idioma = EN
    else:
        idioma = MISTO
    return Deteccao(idioma=idioma, pt=pt, en=en)


def detectar(texto: str, *, trecho_maximo: int = TRECHO_MAXIMO) -> str:
    return detalhar(texto, trecho_maximo=trecho_maximo).idioma


def decidido(idioma: str) -> bool:
    """`pt` e `en` decidem fatia; `misto` e `indefinido` não.

    `misto` fica de fora porque não responde à pergunta que a fatia faz: um
    documento metade PT metade EN atende consulta nos dois idiomas, e contá-lo
    como acerto cross-lingual inflaria justamente a métrica que existe para
    achar a fraqueza da ponte."""
    return idioma in (PT, EN)


def fatia(idioma_pergunta: str, idioma_fonte: str) -> str:
    """Em que recorte um par pergunta→fonte entra."""
    if not decidido(idioma_pergunta) or not decidido(idioma_fonte):
        return NAO_DECLARADO
    return MESMA_LINGUA if idioma_pergunta == idioma_fonte else CROSS_LINGUAL


# --- anotação a partir do índice -------------------------------------------
#
# Esta metade lê o índice; a de cima não. A separação é o que deixa o harness e
# o baseline por nome usarem a fatia sem abrir base nenhuma.


def idioma_de_documento(store, path: str, *, trecho_maximo: int = TRECHO_MAXIMO) -> str:
    """Idioma de um documento indexado, pelos primeiros trechos.

    Documento sem chunk é `indefinido` e não erro: é o estado normal de um PDF
    digitalizado, e a fatia tem que saber conviver com ele — não com uma exceção.
    """
    texto: list[str] = []
    total = 0
    for c in store.chunks_de(path):
        texto.append(c.texto)
        total += len(c.texto)
        if total >= trecho_maximo:
            break
    return detectar(" ".join(texto), trecho_maximo=trecho_maximo)


def idiomas_das_fontes(store, perguntas) -> dict[str, str]:
    """Um idioma por caminho citado no conjunto dourado."""
    caminhos = {f for p in perguntas for f in p.fontes}
    return {c: idioma_de_documento(store, c) for c in sorted(caminhos)}


def idioma_do_conjunto(fontes, idiomas: dict[str, str]) -> str:
    """O idioma de um par pergunta→fontes, quando ela tem mais de uma.

    Fontes que discordam viram `misto`, e `misto` não entra em fatia. Escolher a
    primeira, ou a maioria, produziria um par cross-lingual a partir de um caso
    em que o recuperador tinha alternativa no idioma da pergunta — mediria o
    contrário do que a fatia quer medir.
    """
    vistos = {idiomas.get(f, INDEFINIDO) for f in fontes}
    if not vistos or not all(decidido(v) for v in vistos):
        return INDEFINIDO
    return vistos.pop() if len(vistos) == 1 else MISTO


@dataclass(frozen=True)
class DivergenciaDeIdioma:
    """Uma discordância entre a anotação do dourado e o índice de agora."""

    id: str
    especie: str
    """`sem_anotacao` (dá para anotar e ninguém anotou) ou `divergente` (anotado
    diferente do que o índice mostra)."""
    detalhe: str


def conferir(perguntas, idiomas: dict[str, str]) -> list[DivergenciaDeIdioma]:
    """Anotação estática contra o índice de agora — o par de `verificar_escopo`.

    A anotação ser estática é o que dá comparabilidade entre fases; o preço é
    que ela envelhece calada quando o documento é substituído por uma tradução
    ou quando um parser passa a extrair texto onde não extraía. Este confronto é
    o que transforma esse envelhecimento em linha de log.

    As duas espécies têm gravidade diferente e por isso são distinguidas:
    `sem_anotacao` é cobertura que falta — barulhento e inofensivo, some com um
    `--escrever`. `divergente` é a anotação **mentindo** sobre o documento, e
    esse é o caso que move a fatia sem mover a média.
    """
    divergencias: list[DivergenciaDeIdioma] = []
    for p in perguntas:
        medido = idioma_do_conjunto(p.fontes, idiomas)
        anotado = p.idioma_fonte
        if not anotado and decidido(medido):
            divergencias.append(
                DivergenciaDeIdioma(p.id, "sem_anotacao", f"índice diz `{medido}` — a pergunta fica fora da fatia")
            )
        elif anotado and medido != anotado:
            divergencias.append(
                DivergenciaDeIdioma(p.id, "divergente", f"anotado `{anotado}`, índice diz `{medido}`")
            )
    return divergencias


def _atualizar_linha(linha: str, idioma: str, idioma_fonte: str) -> str:
    """Grava os dois campos preservando ordem e campos desconhecidos.

    Reescrever o registro com uma ordem canônica seria mais limpo e produziria
    um diff de 62 linhas onde a mudança real é de duas — num arquivo que não vai
    para o Git e cuja única revisão possível é o `git diff` local de quem o tem.
    """
    import json as _json

    d = _json.loads(linha)
    if idioma:
        d["idioma"] = idioma
    if idioma_fonte:
        d["idioma_fonte"] = idioma_fonte
    return _json.dumps(d, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """Anota `idioma_fonte` no conjunto dourado a partir do índice da base.

        py -m eval.idioma --base padrao              # só relata
        py -m eval.idioma --base padrao --escrever   # grava a anotação
    """
    import argparse
    import os
    import sys
    from pathlib import Path

    from segundocerebro.config import ErroDeConfig, carregar
    from segundocerebro.logger import get_logger

    from .harness import GOLDEN, carregar_perguntas, resolver_dourado

    log = get_logger("eval.idioma")
    repo = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        prog="eval.idioma",
        description="Detecta o idioma das fontes do conjunto dourado e anota a fatia cross-lingual",
    )
    parser.add_argument("--base", help="qual base ler (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument(
        "--escrever",
        action="store_true",
        help="grava `idioma` e `idioma_fonte` no conjunto dourado; sem a flag, só relata",
    )
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

    from segundocerebro.index.embeddings import Embedder
    from segundocerebro.index.store import IndiceEmEscrita, Store, recusar_se_indexando

    try:
        recusar_se_indexando(Path(base.indice))
    except IndiceEmEscrita as erro:
        log.error("%s", erro)
        return 4
    # `lazy=True`: a dimensão vem do catálogo, e este comando não embedda nada.
    # Carregar o e5-large para ler texto que já está em SQLite custaria ~20 s por nada.
    store = Store(Path(base.indice), Embedder(base.modelo, lazy=True).dim)
    try:
        idiomas = idiomas_das_fontes(store, perguntas)
    finally:
        store.fechar()

    propostas: dict[str, tuple[str, str]] = {}
    for p in perguntas:
        do_texto = p.idioma or detectar(p.pergunta)
        das_fontes = idioma_do_conjunto(p.fontes, idiomas)
        propostas[p.id] = (do_texto, das_fontes)

    resumo: dict[str, int] = {}
    for pid, (q, f) in propostas.items():
        resumo[fatia(q, f)] = resumo.get(fatia(q, f), 0) + 1
    log.info(
        "%d perguntas | %s",
        len(perguntas),
        " · ".join(f"{k}: {resumo.get(k, 0)}" for k in FATIAS),
    )
    for d in conferir(perguntas, idiomas):
        log.warning("idioma/%s: %s — %s", d.especie, d.id, d.detalhe)

    if not args.escrever:
        for p in perguntas:
            q, f = propostas[p.id]
            log.info("%-6s pergunta=%-11s fonte=%-11s → %s", p.id, q, f, fatia(q, f))
        log.info("nada gravado — repita com --escrever")
        return 0

    linhas = caminho.read_text(encoding="utf-8").splitlines()
    saida: list[str] = []
    gravadas = 0
    for linha in linhas:
        if not linha.strip():
            saida.append(linha)
            continue
        import json as _json

        pid = _json.loads(linha)["id"]
        q, f = propostas.get(pid, ("", ""))
        # Assimetria proposital entre os dois campos.
        #
        # `idioma_fonte` grava `indefinido` e `misto`, porque ali eles são dado:
        # o campo não tem detecção de reserva, e vazio seria indistinguível de
        # "ninguém rodou o comando". Uma anotação que envelhece é pega por
        # `conferir()`, que a confronta com o índice a cada `eval.rodar`.
        #
        # `idioma` **não** grava indeciso. Ele tem detecção de reserva, e gravar
        # `indefinido` congelaria a pergunta contra o detector: melhorar as
        # listas deixaria de alcançá-la, sem nada avisando — não há `conferir()`
        # do lado da pergunta, porque o texto dela está sempre à mão. Vazio faz o
        # detector ser reconsultado toda vez, e deixa o campo livre para quem
        # souber a resposta escrevê-la à mão.
        nova = _atualizar_linha(linha, q if decidido(q) else "", f)
        gravadas += nova != linha
        saida.append(nova)

    # Escrita atômica, como `config.gravar()`: o conjunto dourado é a régua de
    # tudo, e um arquivo pela metade depois de uma queda de energia não tem
    # backup em lugar nenhum — ele não vai para o Git.
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text("\n".join(saida) + "\n", encoding="utf-8")
    os.replace(temporario, caminho)
    log.info("%d de %d linhas atualizadas em %s", gravadas, len(perguntas), caminho)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
