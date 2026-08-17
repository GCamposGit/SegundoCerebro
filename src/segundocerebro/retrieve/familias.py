"""Version families: collapse near-duplicates and surface the current one.

O acervo real guarda a mesma coisa muitas vezes. Só a pasta `Política de IA` tem
sete parentes: `_v6`, `_v6_Comentado`, `_revisadaTI`, `_revisadaTI_GC`,
`PL-ACME-007_v0`, `PO-ACME-007_v7`, `_v8`. Sem tratamento acontecem duas coisas,
e as duas foram medidas na condição C (`docs/portas-f1-condicao-c.md`):

1. **O top-10 vira cópias do mesmo documento**, gastando posições que outros
   assuntos ocupariam.
2. **A versão vigente perde para uma antiga.** O caso `g010`: o vigente é o
   `_revisadaTI_GC`, de 11/08/2026, **sem `_vN` no nome**, enquanto o `_v6` — o
   maior número de versão — é de janeiro. Ordenar por número no nome dá a
   resposta errada; ordenar por conteúdo não dá resposta nenhuma, porque os
   arquivos dizem quase a mesma coisa.

Daí o mecanismo: agrupar por família e deixar a **data de modificação** decidir
quem representa. É a informação que separa os irmãos, e ela é metadado — nenhum
peso de fusão a alcança, e é por isso que isto é F2 e não ajuste de F1.

Duas escolhas conservadoras, porque agrupar demais **perde** documento:

- **Família não atravessa pasta.** Dois arquivos de mesmo nome em pastas
  diferentes costumam ser coisas diferentes neste acervo (modelo e preenchido,
  por exemplo).
- **O representante sai de quem foi recuperado**, nunca do índice inteiro.
  Promover um documento que o ranqueador não pontuou seria inventar relevância a
  partir de metadado.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .nomes import normalizar

MARCADORES = [
    # Versão: _v6, v12.3, -V2
    re.compile(r"[ _\-]*v\d+(?:[._]\d+)*\b", re.IGNORECASE),
    # Cópia do Windows/Office: "(1)", " - Copia", "Cópia de "
    re.compile(r"\s*\(\d+\)"),
    re.compile(r"[ _\-]*c[oó]pia(?:\s+de)?", re.IGNORECASE),
    re.compile(r"[ _\-]*copy(?:\s+of)?", re.IGNORECASE),
    # Backup: _bkp3, _bkp12.3
    re.compile(r"[ _\-]*bkp\d*(?:[._]\d+)*", re.IGNORECASE),
    # Rótulos de estado que o acervo usa como sufixo
    re.compile(
        r"[ _\-]*(?:final|finalizado|atualizado|comentado|revisado|revisada|"
        r"apresentado|antigo|old|rev\d*)\b",
        re.IGNORECASE,
    ),
]

INICIAIS = re.compile(r"[ _\-][A-Z]{2,3}$")
"""Sufixo de iniciais de quem revisou — `_GC`, `_TI`.

Só com maiúsculas de verdade, antes de normalizar: minúsculas atingiriam palavra
comum ('_de', '_ia') e fundiriam documentos distintos."""

SEPARADORES = re.compile(r"[ _\-.]+")

VERSAO = re.compile(r"[ _\-]v(\d+(?:[._]\d+)*)\b", re.IGNORECASE)
"""Número de versão explícito no nome, para desempatar dentro da família."""


def versao_de(rel: str) -> tuple[int, ...] | None:
    """`_v12.3` → (12, 3). `None` quando o nome não declara versão."""
    nome = rel.replace("\\", "/").split("/")[-1]
    tronco = nome.rsplit(".", 1)[0] if "." in nome else nome
    achados = VERSAO.findall(tronco)
    if not achados:
        return None
    return tuple(int(p) for p in re.split(r"[._]", achados[-1]))


def chave_de_familia(rel: str) -> str:
    """Pasta + extensão + nome sem marcadores de versão.

    **A extensão entra na chave**, e isso foi medido: sem ela,
    `Apresentação IA RDE Dec-2025.pdf` e `.pptx` — o mesmo conteúdo exportado
    duas vezes, mesma data — viravam uma família só, e o desempate escolhia um
    formato ao acaso. A pergunta `g045` caiu do 1º lugar para fora do ranking por
    isso. Duplicata entre formatos é outro problema, com outra resposta certa:
    quem pede o deck quer o deck, não o PDF dele.
    """
    partes = rel.replace("\\", "/").split("/")
    pasta, nome = "/".join(partes[:-1]), partes[-1]
    tronco, extensao = (nome.rsplit(".", 1) + [""])[:2] if "." in nome else (nome, "")

    anterior = None
    while anterior != tronco:  # marcadores empilham: `_v6_Comentado`
        anterior = tronco
        tronco = INICIAIS.sub("", tronco)
        for marcador in MARCADORES:
            tronco = marcador.sub("", tronco)

    tronco = SEPARADORES.sub(" ", normalizar(tronco)).strip()
    return f"{normalizar(pasta)}::{normalizar(extensao)}::{tronco or normalizar(nome)}"


@dataclass(frozen=True)
class Familia:
    chave: str
    vigente: str
    """O mais recente entre os recuperados — o que a busca devolve."""
    anteriores: tuple[str, ...]
    """Os outros, em ordem de data. Vão no retorno como procedência, não somem."""
    posicao: int
    """Melhor posição que a família ocupava antes do colapso."""


def colapsar(
    ranking: Sequence[str], mtimes: Mapping[str, float]
) -> tuple[list[str], dict[str, Familia]]:
    """Collapse a ranked list of paths, one slot per family.

    A família herda a **melhor posição** de qualquer membro e é representada pelo
    **mais recente** deles. É a combinação que resolve o `g010`: se o irmão
    antigo ranqueou melhor, a família fica com a posição dele e devolve o vigente.

    Ordem estável: quem não tem irmão no ranking passa intacto.
    """
    familias: dict[str, list[str]] = {}
    posicoes: dict[str, int] = {}
    for posicao, path in enumerate(ranking):
        chave = chave_de_familia(path)
        familias.setdefault(chave, []).append(path)
        posicoes.setdefault(chave, posicao)

    resultado: dict[str, Familia] = {}
    for chave, membros in familias.items():
        ordenados = _por_vigencia(membros, mtimes)
        resultado[chave] = Familia(
            chave=chave,
            vigente=ordenados[0],
            anteriores=tuple(ordenados[1:]),
            posicao=posicoes[chave],
        )

    ordenadas = sorted(resultado.values(), key=lambda f: f.posicao)
    return [f.vigente for f in ordenadas], {f.vigente: f for f in ordenadas}


def _por_vigencia(membros: Sequence[str], mtimes: Mapping[str, float]) -> list[str]:
    """Ordena da versão vigente para a mais antiga.

    **Número declarado vence; data desempata.** Os dois sinais existem no acervo e
    medi os dois discordando, em direções opostas:

    - `g010`: `_revisadaTI_GC` (11/08/2026) contra `_revisadaTI` (mais antigo).
      Nenhum declara versão, então a data decide — e acerta.
    - `g045`: `_v0.xlsx` é de **janeiro de 2026** e `_v1.xlsx` de **setembro de
      2025**. A data diz o contrário do número, porque um arquivo copiado ou
      reaberto ganha `mtime` novo sem virar versão nova. Aqui o número decide — e
      acerta.

    Por isso a regra não é "o mais recente": é "quem declara versão é comparado
    por ela; quem não declara, por data". Uma regra só erraria uma das duas.
    """
    versoes = {p: versao_de(p) for p in membros}
    declaradas = {v for v in versoes.values() if v is not None}

    if len(declaradas) > 1:
        # Sem versão declarada num acervo onde os irmãos declaram: vai ao fim,
        # porque `Documento.docx` ao lado de `Documento_v3.docx` costuma ser o
        # rascunho de onde a série saiu.
        return sorted(membros, key=lambda p: (versoes[p] or (), -mtimes.get(p, 0.0), p), reverse=True)
    return sorted(membros, key=lambda p: (-mtimes.get(p, 0.0), p))


def familias_de(paths: Iterable[str]) -> dict[str, list[str]]:
    """Agrupamento puro, para inspeção e para o censo de duplicatas."""
    saida: dict[str, list[str]] = {}
    for p in paths:
        saida.setdefault(chave_de_familia(p), []).append(p)
    return saida
