"""Perfis de recuperação — configurações nomeadas, não números soltos.

O mais amigável não é três controles deslizantes: é escolher entre configurações
que alguém já mediu. Estes quatro cobrem as formas de acervo que a varredura de
13/08/2026 separou (`docs/varredura-pesos-f1.md`).

**Nenhum perfil carrega número medido aqui.** A referência que existe foi medida
noutro acervo. O painel mede na base do usuário e só então mostra.
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
        para_quem="Padrão. Os três sinais votam juntos.",
        custo="Nenhum conhecido. É a referência.",
    ),
    Perfil(
        id="codigo",
        nome="Código e contrato",
        pesos=Pesos(denso=1.0, lexical=1.0, nome=0.5),
        para_quem="Sigla, número de processo, código de contrato.",
        custo="Perguntas em linguagem natural perdem um pouco.",
    ),
    Perfil(
        id="significado",
        nome="Significado",
        pesos=Pesos(denso=1.0, lexical=0.0, nome=0.5),
        para_quem="Perguntas escritas de memória, sem copiar o nome do arquivo.",
        custo="Sigla e código de contrato ficam mais difíceis de achar.",
    ),
    Perfil(
        id="nome",
        nome="Nome de arquivo",
        pesos=Pesos(denso=1.0, lexical=0.25, nome=1.0),
        para_quem="Pastas e nomes já descrevem o acervo.",
        custo="Nome enganoso (versão antiga) sobe demais.",
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
