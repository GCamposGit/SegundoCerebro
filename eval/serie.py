"""`F4-D.2`: congela quais perguntas compõem a série histórica.

`dourado-v1` era **frase, não mecanismo**. O `ROADMAP.md` e o `CLAUDE.md` dizem
que a linha de base do acervo corporativo é n=59 sobre um conjunto "congelado
como `dourado-v1`", e até 30/08/2026 nada congelava nada: o conjunto vive em
`eval/golden/perguntas.jsonl`, que é **gitignorado** porque cada pergunta cita
nome de arquivo do acervo real. Uma pergunta editada — um typo corrigido, uma
fonte trocada — move a série histórica **sem deixar diff em lugar nenhum**.

O modo de falha é o pior deste repositório: a comparação continua parecendo
válida. Duas tabelas do mesmo `recall@1` medidas com dois conjuntos diferentes
são dois números plausíveis e incomparáveis, e nada na tela avisa.

**O que este módulo congela, e o que ele não guarda.** O manifesto
(`eval/golden/dourado-v1.toml`, versionado) tem o `id` de cada pergunta e uma
**impressão digital** de 16 hex do que move a métrica: o texto da pergunta, o
tipo e as fontes esperadas. Não guarda o texto, não guarda o nome de arquivo
nenhum — impressão é de mão única, e o repositório é público. `notas`, `autoria`
e `validada` ficam de fora de propósito: editá-los não muda número nenhum, e um
manifesto que reprova por causa de uma nota reescrita seria abandonado na
primeira semana.

    py -m eval.serie --base padrao              # confere, e diz o que mudou
    py -m eval.serie --base padrao --congelar   # grava a série nova

Congelar é um ato deliberado, com diff para revisar. É essa a diferença entre
mecanismo e frase.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .harness import GOLDEN, Pergunta, carregar_perguntas, resolver_dourado

SERIE_PADRAO = "dourado-v1"
PASTA = Path(__file__).resolve().parent / "golden"
TAMANHO_DA_IMPRESSAO = 16
"""64 bits. O que se defende aqui é edição acidental, não adversário."""


def caminho_da_serie(serie: str = SERIE_PADRAO) -> Path:
    return PASTA / f"{serie}.toml"


def impressao_de(p: Pergunta) -> str:
    """O que move a métrica desta pergunta, e só isso.

    Espaço em branco é normalizado porque quebra de linha reeditada não muda o
    que a pergunta pergunta; o separador de caminho é normalizado para `/` pela
    mesma razão que o harness normaliza — o dourado é escrito no Windows e lido
    onde for.
    """
    canonico = "\n".join(
        [
            p.id,
            p.tipo,
            " ".join(p.pergunta.split()),
            *sorted(f.replace("\\", "/") for f in p.fontes),
        ]
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:TAMANHO_DA_IMPRESSAO]


def impressoes_de(perguntas: Iterable[Pergunta]) -> dict[str, str]:
    return {p.id: impressao_de(p) for p in sorted(perguntas, key=lambda p: p.id)}


@dataclass(frozen=True)
class Divergencia:
    """O que separa o dourado desta máquina da série congelada."""

    sumiram: tuple[str, ...] = ()
    entraram: tuple[str, ...] = ()
    mudaram: tuple[str, ...] = ()

    @property
    def limpa(self) -> bool:
        return not (self.sumiram or self.entraram or self.mudaram)

    def relatar(self, serie: str) -> str:
        if self.limpa:
            return f"{serie}: o conjunto desta máquina é o congelado."
        linhas = [f"{serie}: o conjunto desta máquina NÃO é o congelado."]
        if self.mudaram:
            linhas.append(
                f"  {len(self.mudaram)} pergunta(s) editada(s): {', '.join(self.mudaram)}"
            )
        if self.sumiram:
            linhas.append(
                f"  {len(self.sumiram)} pergunta(s) da série ausente(s) aqui: "
                f"{', '.join(self.sumiram)}"
            )
        if self.entraram:
            linhas.append(
                f"  {len(self.entraram)} pergunta(s) nova(s), fora da série: "
                f"{', '.join(self.entraram)}"
            )
        linhas.append(
            "  Número medido agora não é comparável com a série histórica. "
            "Ou reverta a edição, ou congele uma série nova com --congelar "
            "(e diga no relatório que a linha de base mudou)."
        )
        return "\n".join(linhas)


def conferir(perguntas: Iterable[Pergunta], congeladas: dict[str, str]) -> Divergencia:
    agora = impressoes_de(perguntas)
    return Divergencia(
        sumiram=tuple(sorted(set(congeladas) - set(agora))),
        entraram=tuple(sorted(set(agora) - set(congeladas))),
        mudaram=tuple(
            sorted(i for i in set(agora) & set(congeladas) if agora[i] != congeladas[i])
        ),
    )


CABECALHO = """\
# {serie} — a série histórica, congelada.
#
# Gerado por `py -m eval.serie --congelar`. **Não editar à mão.**
#
# Cada linha é o `id` de uma pergunta do conjunto dourado e a impressão digital
# do que move a métrica dela: o texto, o tipo e as fontes esperadas. O conjunto
# em si é gitignorado — ele cita nome de arquivo do acervo real —, e é por isso
# que este arquivo existe: sem ele uma pergunta editada muda a linha de base
# histórica sem deixar diff em lugar nenhum, e as duas tabelas continuam
# parecendo comparáveis.
#
# Mudar a série é ato deliberado: rode com `--congelar`, revise o diff, e diga
# no relatório que a linha de base mudou.

serie = "{serie}"
congelado_em = "{quando}"
n = {n}

[impressoes]
"""


def como_toml(impressoes: dict[str, str], serie: str, quando: str) -> str:
    corpo = "".join(f'{i} = "{h}"\n' for i, h in sorted(impressoes.items()))
    return CABECALHO.format(serie=serie, quando=quando, n=len(impressoes)) + corpo


def ler(caminho: Path) -> dict[str, str]:
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    impressoes = dados.get("impressoes", {})
    declarado = int(dados.get("n", len(impressoes)))
    if declarado != len(impressoes):
        raise ValueError(
            f"{caminho.name} declara n = {declarado} e lista {len(impressoes)} impressões — "
            "o arquivo foi editado à mão"
        )
    return {str(i): str(h) for i, h in impressoes.items()}


def _hoje() -> str:
    """A data de congelamento, em UTC.

    UTC e não hora local porque a série é comparada entre dois setups em fusos
    que podem divergir, e uma data que muda conforme a máquina reabre a mesma
    pergunta que este módulo existe para fechar.
    """
    return datetime.now(timezone.utc).date().isoformat()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval.serie",
        description="Confere (ou congela) quais perguntas compõem a série histórica",
    )
    parser.add_argument("--base", help="qual base (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--serie", default=SERIE_PADRAO)
    parser.add_argument(
        "--congelar",
        action="store_true",
        help="grava a série com o conjunto desta máquina (ato deliberado, gera diff)",
    )
    args = parser.parse_args(argv)

    caminho = args.golden
    if caminho is None and (args.base or args.config):
        from segundocerebro.config import ErroDeConfig, carregar

        try:
            base = carregar(args.config).base(args.base)
        except ErroDeConfig as erro:
            print(f"config: {erro}", file=sys.stderr)
            return 2
        caminho = base.dourado
    dourado, aviso = resolver_dourado(caminho or GOLDEN, implicito=caminho is None)
    if aviso:
        print(aviso, file=sys.stderr)

    perguntas = carregar_perguntas(dourado)
    alvo = caminho_da_serie(args.serie)

    if args.congelar:
        alvo.write_text(
            como_toml(impressoes_de(perguntas), args.serie, _hoje()),
            encoding="utf-8",
        )
        print(f"{alvo.name}: {len(perguntas)} pergunta(s) congelada(s) de {dourado.name}.")
        return 0

    if not alvo.exists():
        print(
            f"{alvo.name} não existe — rode com --congelar para criar a série.",
            file=sys.stderr,
        )
        return 2

    divergencia = conferir(perguntas, ler(alvo))
    print(divergencia.relatar(args.serie))
    return 0 if divergencia.limpa else 1


if __name__ == "__main__":
    raise SystemExit(main())
