"""Intervalo de confiança por bootstrap — o pacote `E5`.

    from .estatistica import Delta, ic_da_media, ic_do_delta

Existe porque o harness comparava médias secas, e com este n isso já produziu
decisões no fio do ruído. Com as 49 perguntas no escopo do acervo corporativo,
**mover duas perguntas move recall@1 em 4,1 pontos**; nas fatias que a onda 2
decide o n é bem menor — `reunião` tem 11 e `cross-lingual` tem 12, onde *uma*
pergunta vale 9 e 8 pontos. Vários ganhos já celebrados em ablação são dessa
ordem: o reranking da F2 vale +0,011 de nDCG@5.

O que este módulo **não** faz: decidir. Ele devolve `Δ ± IC95` e um veredito de
três valores; quem adota é o pacote, com a regra escrita e o número na mesa.

## Por que pareado, e por que isso não é detalhe

A comparação certa aqui não é "média do braço A contra média do braço B". Os
dois braços respondem **as mesmas perguntas sobre o mesmo corpus**, então os
resultados são fortemente correlacionados: uma pergunta difícil é difícil nos
dois lados. Reamostrar os dois braços de forma independente joga essa correlação
fora e infla o intervalo — é potência descartada de graça.

O bootstrap pareado reamostra **índices de pergunta**, e usa os mesmos índices
nos dois braços:

    idx = amostra_com_reposicao(n)
    delta_b = media(depois[idx]) - media(antes[idx])

E aqui vale a identidade que torna o pareamento **estrutural em vez de
convenção**: como a média é linear,

    media(depois[idx]) - media(antes[idx]) == media((depois - antes)[idx])

Então reamostrar o **vetor de diferenças por pergunta** é exatamente o mesmo
cálculo, e é o que `ic_do_delta` faz. A diferença prática é que ninguém pode
quebrar o pareamento por engano depois — não há dois vetores para dessincronizar.

## Por que percentil, e não normal

A métrica por pergunta é 0/1 em recall@1 e discreta em MRR (1, 1/2, 1/3, …). A
média dessas amostras não é normal com n=11, e um intervalo `média ± 1,96 σ/√n`
seria simétrico onde a distribuição não é. O percentil do bootstrap não assume
forma nenhuma, e o custo é irrelevante nesta escala.

## Determinismo

`SEMENTE` é fixa e o intervalo entra em documento versionado. Um IC que mudasse
a cada regeneração faria o diff do relatório mentir sobre o que mudou — e a
tabela regenerável é metade do valor de `docs/ablacao-f2-tabela.md`. Mesmo vetor
de entrada, mesmo intervalo, sempre.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

REAMOSTRAGENS = 1000
"""O número que a literatura de IR usa para intervalo de percentil (Smucker,
Allan & Carterette, CIKM 2007). Custa milissegundos nesta escala; subir para
10.000 muda a terceira casa e nenhuma decisão."""

CONFIANCA = 0.95

SEMENTE = 20260824
"""Fixa de propósito — ver "Determinismo" no topo. A data é a do pacote `E5`."""

N_MINIMO = 30
"""Piso de `E5.3` por fatia.

Não é um limiar mágico: é o ponto a partir do qual o intervalo de uma proporção
fica estreito o bastante para separar os efeitos que este projeto persegue (2 a
4 pontos). Abaixo dele o intervalo **não** é inválido — é honesto, e larguíssimo.
A tabela marca a fatia em vez de escondê-la, porque "n=11, intervalo de 30
pontos" é o diagnóstico, não um defeito do relatório.

É este piso que dimensiona as ≥500 perguntas do `E1`."""

GANHA = "ganha"
PERDE = "perde"
EMPATE = "empate"


@dataclass(frozen=True)
class Delta:
    """Diferença entre dois braços, com o intervalo e o veredito."""

    valor: float
    baixo: float
    alto: float
    n: int

    @property
    def exclui_zero(self) -> bool:
        """A regra de adoção de `E5.2`, e a única pergunta que decide."""
        return self.baixo > 0.0 or self.alto < 0.0

    @property
    def veredito(self) -> str:
        """`ganha`, `perde` ou `empate`.

        `empate` **não** é "não sabemos ainda, meça mais": no contrato de `E5.2`
        empate resolve por simplicidade, e simplicidade é não adotar. Um braço
        que empata estatisticamente com o padrão e custa mais — latência,
        rebuild, um botão a mais na configuração — perde por não empatar em
        custo."""
        if not self.exclui_zero:
            return EMPATE
        return GANHA if self.valor > 0 else PERDE

    @property
    def subdimensionado(self) -> bool:
        return self.n < N_MINIMO

    def __str__(self) -> str:
        return f"{self.valor:+.3f} [{self.baixo:+.3f}, {self.alto:+.3f}]"


def _percentis(confianca: float) -> tuple[float, float]:
    cauda = (1.0 - confianca) / 2.0 * 100.0
    return cauda, 100.0 - cauda


def _reamostrar(valores: np.ndarray, reamostragens: int, semente: int) -> np.ndarray:
    """Médias de `reamostragens` amostras com reposição do mesmo tamanho."""
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, len(valores), size=(reamostragens, len(valores)))
    return valores[idx].mean(axis=1)


def ic_da_media(
    valores: Sequence[float],
    *,
    reamostragens: int = REAMOSTRAGENS,
    confianca: float = CONFIANCA,
    semente: int = SEMENTE,
) -> tuple[float, float]:
    """Intervalo de percentil para a média de **um** braço.

    Serve à leitura de uma tabela isolada: `recall@1 = 0,551` não diz nada sobre
    o próprio ruído, e `[0,408; 0,694]` diz. Para comparar dois braços use
    `ic_do_delta` — este intervalo é largo justamente porque ignora a correlação
    que o pareamento aproveita, e dois intervalos que se sobrepõem **não**
    provam empate.
    """
    vals = np.asarray(list(valores), dtype=float)
    if vals.size == 0:
        return 0.0, 0.0
    if vals.size == 1:
        return float(vals[0]), float(vals[0])
    baixo, alto = _percentis(confianca)
    medias = _reamostrar(vals, reamostragens, semente)
    return float(np.percentile(medias, baixo)), float(np.percentile(medias, alto))


def ic_do_delta(
    antes: Sequence[float],
    depois: Sequence[float],
    *,
    reamostragens: int = REAMOSTRAGENS,
    confianca: float = CONFIANCA,
    semente: int = SEMENTE,
) -> Delta:
    """Bootstrap **pareado** do ganho de `depois` sobre `antes`.

    As duas sequências são a mesma métrica, pergunta a pergunta, **na mesma
    ordem** — é responsabilidade de quem chama, e `alinhar()` faz isso a partir
    do id da pergunta em vez de confiar na ordem de iteração.
    """
    a = np.asarray(list(antes), dtype=float)
    d = np.asarray(list(depois), dtype=float)
    if a.shape != d.shape:
        raise ValueError(
            f"braços de tamanhos diferentes ({a.size} e {d.size}) — "
            "o teste é pareado e exige a mesma pergunta dos dois lados"
        )
    if a.size == 0:
        return Delta(0.0, 0.0, 0.0, 0)
    diferencas = d - a
    valor = float(diferencas.mean())
    if a.size == 1:
        return Delta(valor, valor, valor, 1)
    baixo_p, alto_p = _percentis(confianca)
    medias = _reamostrar(diferencas, reamostragens, semente)
    return Delta(valor, float(np.percentile(medias, baixo_p)), float(np.percentile(medias, alto_p)), int(a.size))


def alinhar(
    antes: dict[str, float],
    depois: dict[str, float],
) -> tuple[list[float], list[float], list[str]]:
    """Casa os dois braços por id de pergunta e devolve os vetores pareados.

    Só entra o id presente nos dois lados, e a lista dos ids sai junto para que
    quem chama possa dizer quantos ficaram de fora. Descartar em silêncio seria
    o modo de falha do próprio pacote: um braço medido sobre 49 perguntas e
    outro sobre 45 daria um Δ que não é de ninguém.
    """
    comuns = sorted(set(antes) & set(depois))
    return [antes[i] for i in comuns], [depois[i] for i in comuns], comuns
