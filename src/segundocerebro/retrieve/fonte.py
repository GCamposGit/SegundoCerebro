"""Grupo de fonte: em que **tipo de documento** um caminho é.

    from .fonte import ESCRITORIO, REUNIAO, grupo_de_fonte

Regra de caminho pura: não abre índice, não lê arquivo, não custa nada por
consulta. Serve a dois consumidores que **têm de concordar**, e é essa a razão de
o módulo morar aqui e não em `eval/`:

- o **recuperador**, que usa o grupo do documento candidato para decidir quanto
  o ranqueador de nome vale para ele (`F4-P.1`);
- o **harness**, que usa o grupo da fonte esperada para recortar todo relatório
  por grupo (`eval/fonte.py`, que importa daqui).

Enquanto isto viveu só em `eval/`, nada impedia o produto de classificar de um
jeito e o relatório de outro — e a divergência não apareceria em teste nenhum,
porque cada lado estaria certo sozinho. Uma definição, dois consumidores.

**O que este módulo não faz: decidir peso.** Ele responde "que tipo de documento
é este". Quem transforma isso em ranking é `retrieve/hybrid.py`, com número antes
e depois (invariante 4).
"""

from __future__ import annotations

import re

REUNIAO = "reunião"
EMAIL = "email"
ESCRITORIO = "escritório"
MISTO = "misto"

GRUPOS = (ESCRITORIO, REUNIAO, EMAIL, MISTO)
"""Ordem de exibição. `escritório` primeiro porque é o grupo majoritário e a
referência contra a qual os outros se leem; `misto` por último, é o resto.

`misto` **não** é produzido por `grupo_de_fonte`: um caminho só tem um tipo. Ele
existe para a pergunta com fontes de grupos diferentes, que é de `eval/fonte.py`.
"""

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
    """Grupo de um caminho só — o do documento candidato, em tempo de consulta.

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
