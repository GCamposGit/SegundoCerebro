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


def _tronco_sem_marcadores(rel: str) -> tuple[str, str, str]:
    """Extrai (pasta, extensao, tronco_limpo) removendo marcadores em loop."""
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
    return normalizar(pasta), normalizar(extensao), (tronco or normalizar(nome))


def chave_de_familia(rel: str) -> str:
    """Pasta + extensão + nome sem marcadores de versão.

    **A extensão entra na chave**, e isso foi medido: sem ela,
    `Apresentação IA RDE Dec-2025.pdf` e `.pptx` — o mesmo conteúdo exportado
    duas vezes, mesma data — viravam uma família só, e o desempate escolhia um
    formato ao acaso. A pergunta `g045` caiu do 1º lugar para fora do ranking por
    isso. Duplicata entre formatos é outro problema, com outra resposta certa:
    quem pede o deck quer o deck, não o PDF dele.
    """
    pasta, extensao, tronco = _tronco_sem_marcadores(rel)
    return f"{pasta}::{extensao}::{tronco}"


def chave_de_formato(rel: str) -> str:
    """Pasta + nome sem marcadores de versão, ignorando a extensão (C6).

    Usado no agrupamento de formatos alternativos do mesmo documento
    (ex: .pptx e .pdf do mesmo deck).
    """
    pasta, _, tronco = _tronco_sem_marcadores(rel)
    return f"{pasta}::{tronco}"


@dataclass(frozen=True)
class GrupoFormato:
    chave: str
    principal: str
    """O formato mais bem ranqueado entre os recuperados — o que ganha o slot."""
    formatos: tuple[str, ...]
    """Os formatos alternativos do mesmo documento, em ordem de ranqueamento."""
    posicao: int
    """Posição do representante principal no ranking original."""


def colapsar_formatos(
    ranking: Sequence[str],
) -> tuple[list[str], dict[str, GrupoFormato]]:
    """Colapsa múltiplos formatos do mesmo documento (mesmo tronco e pasta).

    Política C6.c: **um slot no top-k**, representante = **o mais bem ranqueado**
    (a primeira ocorrência na lista ordenada pelo recuperador). Os outros
    formatos viram `formatos` alternativos associados ao principal.
    Preserva g045: se o PPTX ranqueou melhor que o PDF, o PPTX ganha o slot
    e o PDF fica como formato alternativo.
    """
    grupos: dict[str, list[str]] = {}
    posicoes: dict[str, int] = {}
    for posicao, path in enumerate(ranking):
        chave = chave_de_formato(path)
        grupos.setdefault(chave, []).append(path)
        posicoes.setdefault(chave, posicao)

    resultado: dict[str, GrupoFormato] = {}
    for chave, membros in grupos.items():
        resultado[chave] = GrupoFormato(
            chave=chave,
            principal=membros[0],
            formatos=tuple(membros[1:]),
            posicao=posicoes[chave],
        )

    ordenados = sorted(resultado.values(), key=lambda g: g.posicao)
    return [g.principal for g in ordenados], {g.principal: g for g in ordenados}


@dataclass(frozen=True)
class Familia:
    chave: str
    vigente: str
    """O mais recente entre os recuperados — o que a busca devolve."""
    anteriores: tuple[str, ...]
    """Os outros, em ordem de data. Vão no retorno como procedência, não somem."""
    posicao: int
    """Melhor posição que a família ocupava antes do colapso."""
    formatos: tuple[str, ...] = ()
    """Formatos alternativos do mesmo documento em outros containers."""


def _colapsar_formatos_de_familias(
    ordenadas_versao: Sequence[Familia],
) -> tuple[list[str], dict[str, Familia]]:
    """Estágio 2 de colapso: agrupa famílias de diferentes formatos pelo mais bem ranqueado."""
    grupos_fmt: dict[str, list[Familia]] = {}
    for fam in ordenadas_versao:
        chave_fmt = chave_de_formato(fam.vigente)
        grupos_fmt.setdefault(chave_fmt, []).append(fam)

    resultado_final: dict[str, Familia] = {}
    for membros_fmt in grupos_fmt.values():
        vencedor = membros_fmt[0]
        outros_formatos = tuple(f.vigente for f in membros_fmt[1:])
        todas_anteriores = list(vencedor.anteriores)
        for f in membros_fmt[1:]:
            for ant in f.anteriores:
                if ant not in todas_anteriores:
                    todas_anteriores.append(ant)
        resultado_final[vencedor.vigente] = Familia(
            chave=vencedor.chave,
            vigente=vencedor.vigente,
            anteriores=tuple(todas_anteriores),
            posicao=vencedor.posicao,
            formatos=outros_formatos,
        )

    ordenadas_final = sorted(resultado_final.values(), key=lambda f: f.posicao)
    return [f.vigente for f in ordenadas_final], {f.vigente: f for f in ordenadas_final}


def colapsar(
    ranking: Sequence[str],
    mtimes: Mapping[str, float],
    *,
    agrupar_formatos: bool = True,
) -> tuple[list[str], dict[str, Familia]]:
    """Collapse a ranked list of paths, one slot per family (and format group if C6).

    Dois estágios (C6):
    1. Família de versões (mesma pasta e extensão): o mais recente (por vigência)
       herda a melhor posição entre seus irmãos e acumula as anteriores.
    2. Grupo de formatos (mesma pasta, formatos distintos): o mais bem ranqueado
       ganha o slot único e acumula os outros formatos em `formatos`.

    Ordem estável: quem não tem irmão no ranking passa intacto.
    """
    familias: dict[str, list[str]] = {}
    posicoes: dict[str, int] = {}
    for posicao, path in enumerate(ranking):
        chave = chave_de_familia(path)
        familias.setdefault(chave, []).append(path)
        posicoes.setdefault(chave, posicao)

    resultado_versao: dict[str, Familia] = {}
    for chave, membros in familias.items():
        ordenados_vigencia = por_vigencia(membros, mtimes)
        resultado_versao[chave] = Familia(
            chave=chave,
            vigente=ordenados_vigencia[0],
            anteriores=tuple(ordenados_vigencia[1:]),
            posicao=posicoes[chave],
        )

    ordenadas_versao = sorted(resultado_versao.values(), key=lambda f: f.posicao)
    if not agrupar_formatos:
        return [f.vigente for f in ordenadas_versao], {f.vigente: f for f in ordenadas_versao}
    return _colapsar_formatos_de_familias(ordenadas_versao)



def superados_de_ranking(
    caminhos_ordenados: Sequence[str],
    mtimes: Mapping[str, float],
    *,
    agrupar_formatos: bool = True,
) -> tuple[set[str], dict[str, Familia]]:
    """Identifica caminhos superados por versões mais recentes ou formatos mais bem ranqueados."""
    vencedores, mapa = colapsar(caminhos_ordenados, mtimes, agrupar_formatos=agrupar_formatos)
    conjunto_vencedores = set(vencedores)
    superados = {p for p in caminhos_ordenados if p not in conjunto_vencedores}
    return superados, mapa


def por_vigencia(membros: Sequence[str], mtimes: Mapping[str, float]) -> list[str]:
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
