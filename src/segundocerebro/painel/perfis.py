"""Perfis de recuperação — configurações nomeadas, não números soltos.

O mais amigável não é três controles deslizantes: é escolher entre configurações
que alguém já mediu. Estes quatro cobrem as formas de acervo que a varredura de
13/08/2026 separou (`docs/varredura-pesos-f1.md`).

**Nenhum perfil carrega número medido aqui.** A referência que existe foi medida
noutro acervo, e exibi-la como se fosse desta base seria a mentira mais fácil
desta tela — o usuário decidiria olhando um número que não é dele. O painel mede
o perfil na base do usuário e só então mostra; antes disso, mostra que não sabe.

O que os cartões podem dizer sem quebrar isso é a **forma** do compromisso —
"ganha na média, perde no caso difícil" — porque essa é propriedade do mecanismo
e não do acervo: um ranqueador a menos é um ranqueador a menos em qualquer
instalação. Onde os dígitos moram é
[`docs/ablacao-f2.md`](../../../docs/ablacao-f2.md), com a procedência do acervo
em que foram tirados.

Sobre o `significado` em particular: ele é o candidato a padrão que a ablação da
F2 levantou e a regra de elegibilidade recusou — melhor em toda média, e abaixo
da porta de casos-armadilha que foi declarada antes de medir. Fica aqui como
escolha do usuário, e é por isso que o cartão diz "escolha por média ou por caso
difícil" em vez de esconder o que ele perde.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Pesos


@dataclass(frozen=True)
class Perfil:
    id: str
    nome: str
    pesos: Pesos
    para_quem: str
    custo: str
    """O que este perfil **perde**. Cartão que só mostra ganho é propaganda."""


PERFIS: tuple[Perfil, ...] = (
    Perfil(
        id="equilibrado",
        nome="Equilibrado",
        pesos=Pesos(denso=1.0, lexical=0.25, nome=0.5),
        para_quem="Padrão. Escolhido pela regra da varredura, com os três sinais votando.",
        custo="Nenhum conhecido — é a referência contra a qual os outros são comparados.",
    ),
    Perfil(
        id="codigo",
        nome="Código e contrato",
        pesos=Pesos(denso=1.0, lexical=1.0, nome=0.5),
        para_quem="Acervo cheio de sigla, número de processo e código de contrato, "
        "onde o casamento exato do termo vale mais que a semelhança de sentido.",
        custo="O bm25 com voz plena afoga o denso nas perguntas escritas em "
        "linguagem natural — na medição de 13/08 as configurações com lexical = 1 "
        "se agruparam no fundo da tabela por MRR.",
    ),
    Perfil(
        id="significado",
        nome="Significado",
        pesos=Pesos(denso=1.0, lexical=0.0, nome=0.5),
        para_quem="Perguntas em linguagem natural, escritas de memória e não "
        "copiadas do nome do arquivo. É o perfil mais rápido dos quatro, porque "
        "dispensa um dos ranqueadores, e no acervo de referência ele lidera todas "
        "as médias de qualidade — inclusive contra o Equilibrado.",
        custo="Lidera as médias e perde nos casos difíceis: sem o casamento exato "
        "do termo, sigla e código de contrato deixam de ser encontráveis, e é "
        "exatamente aí que documentos quase idênticos se distinguem. No acervo de "
        "referência resolve menos casos-armadilha que o Equilibrado. Escolha este "
        "por média, o Equilibrado por caso difícil.",
    ),
    Perfil(
        id="nome",
        nome="Nome de arquivo",
        pesos=Pesos(denso=1.0, lexical=0.25, nome=1.0),
        para_quem="Acervo muito bem organizado, com nomes descritivos e pastas "
        "que já codificam projeto, ano e tipo.",
        custo="Peso demais no nome derruba os casos em que o nome mente — versões "
        "antigas com número maior, e nomes com letra trocada.",
    ),
)

POR_ID = {p.id: p for p in PERFIS}


def como_json() -> list[dict]:
    return [
        {
            "id": p.id,
            "nome": p.nome,
            "pesos": dict(p.pesos.__dict__),
            "para_quem": p.para_quem,
            "custo": p.custo,
        }
        for p in PERFIS
    ]
