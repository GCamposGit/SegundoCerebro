"""The base map — how many files and how many MB, by type, and what is left.

One rule holds this module together: **the remaining map is derived by
difference, never decremented.**

    restante[tipo] = censo[tipo] − registro[tipo]

An incremental counter is the defect this repository has already paid for twice:
it fails in silence and produces a plausible number. So the map is recomputed
from the registry at each cycle boundary; inside a cycle the estimate uses the
last derived map, at most a few documents stale, and no drift accumulates
because every cycle re-derives from scratch.

The census side comes from the **same `iter_files` the indexer uses** — that is
failure mode 1 of `docs/estimativa-de-indexacao.md`: counting the raw file list
again is exactly how the wrong denominator is born (45% reported where the real
figure was 91%).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .calibracao import tipo_de

INTERVALO_MINIMO = 15.0
"""Seconds between re-derivations. Bounded so a big registry cannot turn the
map into a cost centre; the recompute also never runs more often than twice its
own measured duration."""

FILA_CURTA = 50
"""Abaixo disto a rederivação sai a cada documento: é barata e é o único
jeito de a barra fechar em vez de parar perto do fim."""

MAIORES_INDIVIDUAIS = 12
"""How many of the biggest remaining files are drawn individually in the Monte
Carlo instead of through their type aggregate. It is where the variance lives:
two of 3.530 files carried 49% of the chunks."""


@dataclass(frozen=True)
class Item:
    rel: str
    mb: float
    tipo: str
    tamanho: int = 0
    mtime: float = 0.0


@dataclass
class Fatia:
    n: int = 0
    mb: float = 0.0

    def somar(self, mb: float) -> None:
        self.n += 1
        self.mb += mb


@dataclass
class Mapa:
    """Census once, remainder re-derived.

    `situacao` per file, and the three cost ordens de grandeza apart:

    - **novo** — not in the registry: full model.
    - **mudado** — in the registry but needing work: a *mixture*, because
      whether the content really changed is unknowable before hashing. Some
      take the sha256 shortcut and never reach the encoder.
    - **inalterado** — filtered out of the work queue before any file is
      opened, so its cost is not "sha256 + I/O" as first specified: it is
      **zero**, and it must not enter the remaining time at all. Predicting it
      with the full model is what makes the bar ask for hours on a re-scan of
      minutes.
    """

    itens: list[Item] = field(default_factory=list)
    censo: dict[str, Fatia] = field(default_factory=dict)
    restante: dict[str, Fatia] = field(default_factory=dict)
    feito: dict[str, Fatia] = field(default_factory=dict)
    inalterados: dict[str, Fatia] = field(default_factory=dict)
    maiores: list[Item] = field(default_factory=list)
    _prontos: set[str] = field(default_factory=set)
    _ultimo: float = 0.0
    _custo: float = 0.0

    # -- construção

    def declarar(self, arquivos: Iterable) -> None:
        """Aceita `(rel, tamanho)` ou `(rel, tamanho, mtime)`.

        O `mtime` só serve para a rederivação — é o que `_precisa_indexar`
        compara. Quem apenas declara trabalho para estimar (o painel, o censo)
        não tem por que carregá-lo, e exigir a tripla espalharia um campo
        inútil por todos os chamadores.
        """
        for registro in arquivos:
            rel, tamanho = registro[0], registro[1]
            mtime = float(registro[2]) if len(registro) > 2 else 0.0
            mb = max(0.0, tamanho / 1_048_576)
            item = Item(rel=rel, mb=mb, tipo=tipo_de(rel), tamanho=tamanho, mtime=mtime)
            self.itens.append(item)
            self.censo.setdefault(item.tipo, Fatia()).somar(mb)
        # sem registro ainda: tudo é restante
        self.restante = {t: Fatia(f.n, f.mb) for t, f in self.censo.items()}
        self._maiores()

    def _maiores(self) -> None:
        cand = [i for i in self.itens if i.rel not in self._prontos]
        cand.sort(key=lambda i: -i.mb)
        self.maiores = cand[:MAIORES_INDIVIDUAIS]

    # -- derivação

    def vencido(self, agora: float | None = None) -> bool:
        """Quando vale rederivar.

        Três casos, e os dois últimos foram achados por teste:

        - passou o intervalo (nunca mais de metade do tempo derivando);
        - **nunca derivou** — antes da primeira derivação o mapa ainda é o
          censo inteiro, e a pré-passada pode pular milhares de arquivos antes
          de o trabalho começar. Sem isto a previsão inicial conta como
          restante tudo que já está indexado;
        - **falta pouco** — no fim da fila o custo da derivação é irrelevante e
          a alternativa é a barra nunca chegar a "terminando".
        """
        if self._ultimo <= 0:
            return True
        if 0 < self.n_restante <= FILA_CURTA:
            return True
        agora = time.monotonic() if agora is None else agora
        espera = max(INTERVALO_MINIMO, 2.0 * self._custo)
        return (agora - self._ultimo) >= espera

    def recalcular(
        self,
        estados: dict,
        precisa: Callable[[object, Item], bool],
        *,
        agora: float | None = None,
    ) -> None:
        """`restante = censo − registro`, from scratch.

        `precisa(estado, item)` wraps the indexer's own `_precisa_indexar` and
        is passed in rather than reimplemented — a derived cut computed twice is
        a derived cut computed differently, and this repository has the scar:
        a rule re-derived by folder prefix gave a smaller, plausible number.
        """
        t0 = time.perf_counter()
        restante: dict[str, Fatia] = {}
        feito: dict[str, Fatia] = {}
        inalt: dict[str, Fatia] = {}
        prontos: set[str] = set()
        for item in self.itens:
            estado = estados.get(item.rel)
            if estado is None or precisa(estado, item):
                restante.setdefault(item.tipo, Fatia()).somar(item.mb)
                continue
            feito.setdefault(item.tipo, Fatia()).somar(item.mb)
            prontos.add(item.rel)
            if getattr(estado, "n_chunks", 0) == 0 and getattr(estado, "status", "") == "ok":
                inalt.setdefault(item.tipo, Fatia()).somar(item.mb)
        self.restante, self.feito, self.inalterados = restante, feito, inalt
        self._prontos = prontos
        self._maiores()
        self._custo = time.perf_counter() - t0
        self._ultimo = time.monotonic() if agora is None else agora

    # -- leitura

    @property
    def n_censo(self) -> int:
        return len(self.itens)

    @property
    def n_feito(self) -> int:
        return sum(f.n for f in self.feito.values())

    @property
    def n_restante(self) -> int:
        return sum(f.n for f in self.restante.values())

    @property
    def mb_restante(self) -> float:
        return sum(f.mb for f in self.restante.values())

    @property
    def mb_censo(self) -> float:
        return sum(f.mb for f in self.censo.values())

    def mb_restante_por_tipo(self) -> dict[str, float]:
        return {t: f.mb for t, f in self.restante.items() if f.mb > 0}

    @property
    def fracao(self) -> float:
        if not self.itens:
            return 0.0
        return min(1.0, self.n_feito / len(self.itens))

    def diagnostico(self, *, limite: int = 12) -> list[str]:
        """Always shown, even with no time prediction — the map is information
        the user can act on, and it never depends on calibration."""
        linhas = [f"{self.n_censo:,} arquivos · {self.mb_censo:,.1f} MB".replace(",", ".")]
        ordem = sorted(self.censo.items(), key=lambda kv: -kv[1].mb)
        for tipo, fatia in ordem[:limite]:
            fez = self.feito.get(tipo, Fatia())
            pct = (100.0 * fez.n / fatia.n) if fatia.n else 0.0
            linhas.append(
                f"  {tipo or '(sem ext)':<12} {fatia.n:>6} {fatia.mb:>8.2f} MB"
                f"   já: {fez.n:>6} ({pct:>3.0f}%)"
            )
        if len(ordem) > limite:
            resto = sum(f.n for _, f in ordem[limite:])
            linhas.append(f"  … {len(ordem) - limite} outros tipos, {resto} arquivos")
        return linhas

    def como_json(self) -> dict:
        return {
            "arquivos": self.n_censo,
            "mb": round(self.mb_censo, 3),
            "restante_arquivos": self.n_restante,
            "restante_mb": round(self.mb_restante, 3),
            "tipos": {
                tipo: {
                    "n": fatia.n,
                    "mb": round(fatia.mb, 3),
                    "feito_n": self.feito.get(tipo, Fatia()).n,
                    "restante_n": self.restante.get(tipo, Fatia()).n,
                    "restante_mb": round(self.restante.get(tipo, Fatia()).mb, 3),
                }
                for tipo, fatia in sorted(self.censo.items(), key=lambda kv: -kv[1].mb)
            },
        }
