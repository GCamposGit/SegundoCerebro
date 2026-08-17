"""Perfis de recuperação — configurações nomeadas, não números soltos.

O mais amigável não é três controles deslizantes: é escolher entre configurações
que alguém já mediu. Estes quatro cobrem as formas de acervo que a varredura de
13/08/2026 separou (`docs/varredura-pesos-f1.md`).

**Nenhum perfil carrega número medido aqui.** A referência que existe foi medida
noutro acervo, e exibi-la como se fosse desta base seria a mentira mais fácil
desta tela — o usuário decidiria olhando um número que não é dele. O painel mede
o perfil na base do usuário e só então mostra; antes disso, mostra que não sabe.
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
        para_quem="Perguntas em linguagem natural sobre acervo cujos nomes de "
        "arquivo dizem pouco.",
        custo="Sem o casamento exato, sigla e código de contrato deixam de ser "
        "encontráveis. Na medição de 13/08 isso subiu o MRR e derrubou os "
        "casos-armadilha de 4 para 3 de 6.",
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
