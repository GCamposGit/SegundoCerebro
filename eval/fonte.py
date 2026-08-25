"""Grupo de fonte no harness: em que **tipo de documento** a resposta mora.

    from .fonte import GRUPOS, grupo_de_pergunta

A regra de classificação **não mora aqui**. Ela é
`segundocerebro.retrieve.fonte`, e este módulo a importa. A razão é o `F4-P.1`:
desde 25/08/2026 o recuperador usa o grupo do documento candidato para decidir
quanto o ranqueador de nome vale para ele. Se a régua do relatório e a regra do
ranking fossem duas cópias, elas divergiriam em silêncio — cada uma certa
sozinha, e nenhum teste vermelho. `eval/test_fonte.py` recusa a cópia.

O que fica aqui é o que só o harness tem: a pergunta, que pode ter mais de uma
fonte.

Este recorte existe por causa do achado de
[`docs/dourado-cobertura.md`](../docs/dourado-cobertura.md): nas 11 perguntas de
reunião, **desligar o ranqueador de nome sobe o MRR 60%** (0,287 → 0,459),
enquanto no conjunto inteiro ele continua se pagando. O peso certo do nome não é
um número só — e para decidir isso é preciso uma coluna que separe os grupos em
todo relatório, não uma medição avulsa.

Sem essa coluna a média esconde a troca, que é o mesmo modo de falha que `C4.5`
fechou para idioma. A diferença de projeto entre os dois recortes é deliberada:

- `idioma_fonte` **não** é derivável sem abrir o índice, então é anotação
  estática no dourado (ver `eval.idioma`);
- **grupo de fonte é derivável do próprio caminho**, que o dourado já carrega.
  Derivar é melhor que anotar aqui, porque anotação envelhece e esta não precisa
  envelhecer: `fontes` é o campo que define a pergunta.

Nada aqui abre o índice, pela mesma razão de `eval.idioma`: o baseline por nome
tem de aparecer nas duas colunas, e ele não abre base nenhuma.
"""

from __future__ import annotations

from collections.abc import Sequence

from segundocerebro.retrieve.fonte import (
    EMAIL,
    ESCRITORIO,
    EXTENSOES_DE_EMAIL,
    EXTENSOES_DE_TRANSCRICAO,
    GRUPOS,
    MISTO,
    PASTAS_DE_REUNIAO,
    PREFIXO_DE_ORDENACAO,
    REUNIAO,
    grupo_de_fonte,
)

__all__ = [
    "EMAIL",
    "ESCRITORIO",
    "EXTENSOES_DE_EMAIL",
    "EXTENSOES_DE_TRANSCRICAO",
    "GRUPOS",
    "MISTO",
    "PASTAS_DE_REUNIAO",
    "PREFIXO_DE_ORDENACAO",
    "REUNIAO",
    "grupo_de_fonte",
    "grupo_de_pergunta",
]


def grupo_de_pergunta(fontes: Sequence[str]) -> str:
    """Grupo de uma pergunta, que pode ter mais de uma fonte.

    Fontes de grupos diferentes dão `misto`, e a pergunta **não** entra em
    nenhum dos três grupos puros. É o mesmo tratamento que `eval.idioma` dá ao
    par de idiomas indefinido, e pelo mesmo motivo: uma pergunta multi-hop entre
    a reunião e o documento que ela cita não mede "o nome ajuda na reunião" nem
    "o nome ajuda no documento" — mede a ponte entre os dois. Somá-la a um dos
    lados é o tipo de contaminação que faz a média mentir.

    Sem fonte nenhuma o grupo é `misto` pelo mesmo argumento: é o balde do que
    não se decidiu, e some da contagem dos grupos puros em vez de inflar um.
    """
    grupos = {grupo_de_fonte(f) for f in fontes}
    if len(grupos) == 1:
        return grupos.pop()
    return MISTO
