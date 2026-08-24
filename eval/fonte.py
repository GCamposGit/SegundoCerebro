"""Grupo de fonte: em que **tipo de documento** a resposta de uma pergunta mora.

    from .fonte import GRUPOS, grupo_de_pergunta

Existe por causa do achado de [`docs/dourado-cobertura.md`](../docs/dourado-cobertura.md):
nas 11 perguntas de reunião, **desligar o ranqueador de nome sobe o MRR 60%**
(0,287 → 0,459), enquanto no conjunto inteiro ele continua se pagando. O peso
certo do nome provavelmente não é um número só — e para decidir isso é preciso
uma coluna que separe os grupos em todo relatório, não uma medição avulsa.

Sem essa coluna a média esconde a troca, que é o mesmo modo de falha que `C4.5`
fechou para idioma. A diferença de projeto entre os dois recortes é deliberada:

- `idioma_fonte` **não** é derivável sem abrir o índice, então é anotação
  estática no dourado (ver `eval.idioma`);
- **grupo de fonte é derivável do próprio caminho**, que o dourado já carrega.
  Derivar é melhor que anotar aqui, porque anotação envelhece e esta não precisa
  envelhecer: `fontes` é o campo que define a pergunta.

O que este módulo **não** faz: decidir peso. Ele é régua. Quem usa a régua para
mudar ranking é `F4-P`, e com número antes e depois.

Nada aqui abre o índice, pela mesma razão de `eval.idioma`: o baseline por nome
tem de aparecer nas duas colunas, e ele não abre base nenhuma.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

REUNIAO = "reunião"
EMAIL = "email"
ESCRITORIO = "escritório"
MISTO = "misto"

GRUPOS = (ESCRITORIO, REUNIAO, EMAIL, MISTO)
"""Ordem de exibição. `escritório` primeiro porque é o grupo majoritário e a
referência contra a qual os outros se leem; `misto` por último, é o resto."""

EXTENSOES_DE_EMAIL = frozenset({".msg", ".eml"})
"""Formato basta: um `.msg` é email onde estiver."""

EXTENSOES_DE_TRANSCRICAO = frozenset({".vtt", ".srt", ".sbv"})
"""Legenda com marca de tempo é transcrição por construção, sem olhar a pasta."""

PREFIXO_DE_ORDENACAO = r"(?:\d+[\s.)\-_]+)?"
"""`09. `, `01 - `, `260722_` — numeração que o usuário põe para a pasta ordenar.

Medido no dourado corporativo em 24/08/2026: **14 dos 36 segmentos de pasta
distintos** têm um prefixo desses, entre numeração sequencial (`00.` a `10 -`) e
data (`260707_`). Não é peculiaridade de um acervo, é como pasta de trabalho é
nomeada — e sem tolerar o prefixo a regra erra 39% dos segmentos.

Foi o que aconteceu na primeira versão deste arquivo: ela exigia a palavra no
**começo** do segmento, e uma pergunta de reunião ficou de fora porque a pasta
dela começa com número. O recorte mediu 10 onde `docs/dourado-cobertura.md` já
tinha medido 11 — e o número menor era plausível, então passaria. Mesma classe
dos cinco defeitos do grafo da F4: o mesmo nome escrito de outra forma não liga,
e cada grafia produz o seu próprio resultado plausível."""

PASTAS_DE_REUNIAO = re.compile(
    r"(?:^|[\\/])" + PREFIXO_DE_ORDENACAO + r"(?:meeting|reuni|transcri|atas?\b|calls?\b)",
    re.IGNORECASE,
)
"""Pasta que denuncia reunião, em português e inglês.

Vocabulário genérico de propósito: nome de pasta de acervo real não entra em
código público (a regra do `.gitignore` e do `tests/test_saneamento.py`), e um
padrão genérico ainda serve ao próximo acervo, que é o que `R6.1` vai exigir.

Casa no **começo de um segmento** de caminho, tolerando `PREFIXO_DE_ORDENACAO`,
para `Documentos/09. Meeting Notes/` entrar e `.../Remeeting.pdf` não.

`meeting`, `reuni` e `transcri` valem como prefixo porque toda flexão serve:
`Meetings 2026`, `Reunião`, `Reuniões`, `Transcrições`. E `reuni` **precisa** ser
prefixo em vez de `reuni[oõ]`: em `Reunião` o que vem depois de `reuni` é `ã`, e
a primeira versão deste padrão passou no teste só porque o teste usava
`Reuniões`.

`ata` e `call` são a exceção e pedem `\\b`: como prefixo casariam `Atacado`,
`Atalhos` e `Callback`, que não são reunião nenhuma."""


def grupo_de_fonte(caminho: str) -> str:
    """Grupo de uma fonte só, a partir do caminho relativo do dourado.

    A ordem das três perguntas é o que decide os casos ambíguos, e é deliberada:
    o formato ganha da pasta. Um `.msg` dentro de `Meetings/` é o convite da
    reunião, não a transcrição dela — e foi exatamente esse arquivo que tirou a
    `g045` do primeiro lugar quando o `.msg` entrou no índice
    (`docs/ablacao-f4-email.md`). Chamá-lo de "reunião" apagaria o achado.
    """
    normalizado = caminho.replace("\\", "/")
    ponto = normalizado.rfind(".")
    extensao = normalizado[ponto:].lower() if ponto > normalizado.rfind("/") else ""
    if extensao in EXTENSOES_DE_EMAIL:
        return EMAIL
    if extensao in EXTENSOES_DE_TRANSCRICAO:
        return REUNIAO
    if PASTAS_DE_REUNIAO.search(normalizado):
        return REUNIAO
    return ESCRITORIO


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
