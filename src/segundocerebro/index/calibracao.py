"""Master table for indexing-time estimation — machine half and format half.

Why the split (see `docs/spec-estimativa-v2.md` §3): the encoder costs a
constant per token (0,0027 s/token measured flat from 63 to 465 tokens on this
notebook) and that number knows nothing about file formats. What a *format*
decides is how many tokens a megabyte of it contains — and that spans 375×,
from 1.029 tok/MB for `.docx` (zipped XML) to 386.353 for `.csv`.

So a new machine has to learn **three numbers**, and any file type teaches
them; the format half travels in this repository as a measured prior and is
only refined per base. The v1 design mixed both halves into one s/MB per type,
which is why nothing learned about `.txt` ever helped predict `.pdf`.

Fitting is recursive least squares with a forgetting factor — the EWMA of the
sufficient statistics — so every document costs O(1) and the whole history is
present with weight lambda^n. Coefficients are constrained non-negative (a time
cannot be negative, and unconstrained 2x2 fits do produce negative intercepts
with correlated regressors), and outliers are down-weighted in log space rather
than discarded: the v1 clip rejected exactly the observations that carried the
information (a type whose coefficient is N× wrong produces ratio N).
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..logger import get_logger
from .regime_maquina import (  # noqa: F401 — impressao re-exported for indexer/tests
    aceita_regime,
    diretorio_de_calibracao,
    impressao_da_maquina,
)

log = get_logger("calibracao")

LAMBDA = 0.995
"""Forgetting factor. Half-life ~140 documents — recent enough to follow
thermal state, long enough not to oscillate."""

N0_ENCOLHIMENTO = 8.0
"""Observations at which a local fit weighs the same as the prior."""

HUBER_LOG = 0.7
"""Above this |log(medido/previsto)| the observation is down-weighted (never
dropped). 0,7 ≈ um fator 2 de erro."""

"""O ridge é proporcional à **escala observada**: `τ_i = n0 · s_ii / peso`.

Isso faz o prior valer exatamente `n0` observações em peso efetivo, qualquer que
seja o tamanho dos arquivos que apareceram — uma observação pesa 1/9 do prior,
duzentas pesam 96%. Escala-livre e sem constante para calibrar.

Duas tentativas anteriores, e as duas falharam por motivos opostos:

- **Encolhimento pós-ajuste** (`w = n/(n+n0)` sobre a solução livre): com uma
  observação o ajuste de dois parâmetros é indeterminado, e encolher uma
  resposta arbitrária a mantém arbitrária. Uma medição de 120 s num arquivo de
  2 KB mandava no coeficiente de máquina, que depois multiplicava os 51 mil
  chunks de um PDF de 50 MB.
- **Escala de referência fixa** (40 chunks, 5.000 tokens): consertou aquilo e
  criou o contrário — duzentos arquivos de 52 bytes têm `x²` mil vezes menor que
  a referência, então **nunca** conseguiam ensinar nada. Num run real de 200
  documentos o modelo seguia prevendo 0,29 s onde o medido era 0,90 s, e o viés
  sistemático vazava para o `mu` do resíduo, que existe para dispersão.

O que resolve os dois é a escala observada **mais o peso de Huber desde a
primeira observação**: a absurda entra com peso 0,16 contra `n0` do prior (2%),
e duzentas consistentes somam peso 200 contra 8 (96%)."""

FATOR_DE_EXTRAPOLACAO = 8.0
"""Até quantas vezes o maior documento medido a previsão confia nos
coeficientes aprendidos.

Acima disso ela encolhe para a predição do prior, proporcionalmente à distância.
Sessenta documentos de **um** chunk determinam muito bem `c0 + 120·c1`, e quase
nada sobre a *separação* dos dois — que é exactamente o que faz falta para
prever um CSV de 767 chunks. Sem o encolhimento, um run real de 60 arquivos de
52 bytes previa 2 dias e meio para 3.471 arquivos iguais mais 12 grandes, contra
~8 h plausíveis: o erro todo vinha de `c0` aprendido em 1 chunk e multiplicado
por 767.

Regularizar o *ajuste* não resolve isso, e é por isso que este limite existe
separado: o ajuste é bom no ponto medido: o problema é a distância."""

CAMINHOS_BARATOS = frozenset({"inalterado", "revalidado", "texto"})
"""Situações que nunca chegam ao encoder, e por isso não custam por token.

- `inalterado`: filtrado da fila antes de abrir.
- `revalidado`: atalho de sha256, conteúdo idêntico com mtime novo.
- `texto`: passe 1 do modo de dois passes (R3.2) — grava o texto e deixa o
  embedding para o passe 2.

O nome do conjunto existe para que a próxima situação nova seja acrescentada
**aqui**, e não num `if` novo em algum call site: foi assim que o modo de dois
passes reintroduziu, sem conflito de merge, a chamada antiga que a v2 tinha
removido de cinco lugares.

Limite declarado: o modo de dois passes é decidido por execução, e o mapa não
sabe de antemão que um documento pagará só metade. A previsão do passe 1 sai
pelo modelo completo e portanto alta; medir e modelar isso pede uma passada
própria."""

PERFIL_REFERENCIA = "maximo"
"""Profile where `g` is pinned to 1. Everything else is measured against it."""

DUTY = {"leve": 0.25, "normal": 0.50, "maximo": 1.00}
"""Seed for `g`: `dormir_ritmo` sleeps proportionally to work, so 1/duty."""


# --------------------------------------------------------------------------
# recursive least squares, two variables, non-negative


@dataclass
class Ajuste:
    """`y ≈ t0·x0 + t1·x1`, recursive, forgetting, non-negative.

    Five accumulated numbers and a closed-form 2x2 solve. No history kept.
    """

    s00: float = 0.0
    s01: float = 0.0
    s11: float = 0.0
    u0: float = 0.0
    u1: float = 0.0
    peso: float = 0.0
    n: int = 0

    def observar(self, x0: float, x1: float, y: float, *, peso: float = 1.0) -> None:
        if y < 0 or peso <= 0:
            return
        lam = LAMBDA
        self.s00 = lam * self.s00 + peso * x0 * x0
        self.s01 = lam * self.s01 + peso * x0 * x1
        self.s11 = lam * self.s11 + peso * x1 * x1
        self.u0 = lam * self.u0 + peso * x0 * y
        self.u1 = lam * self.u1 + peso * x1 * y
        self.peso = lam * self.peso + peso
        self.n += 1

    def _objetivo(self, t0: float, t1: float) -> float:
        # theta' S theta - 2 u' theta — o termo em y² é constante e não muda o argmin
        return (
            t0 * t0 * self.s00
            + 2 * t0 * t1 * self.s01
            + t1 * t1 * self.s11
            - 2 * (t0 * self.u0 + t1 * self.u1)
        )

    def resolver(
        self,
        prior: tuple[float, float] = (0.0, 0.0),
        n0: float = N0_ENCOLHIMENTO,
    ) -> tuple[float, float]:
        """Non-negative least squares with a ridge centred on the prior.

        `(S + T)θ = u + T·prior`, with `T = diag(n0·s_ii/peso)` — Bayesian
        linear regression with a Gaussian prior, which is the same thing.

        Why not fit freely and shrink afterwards, as the first version did:
        with **one** observation a two-parameter fit is underdetermined, and
        the active-set enumeration then loads one axis arbitrarily (both
        candidates tie on the objective, so the answer depends on list order).
        Shrinking an arbitrary answer toward the prior still leaves it
        arbitrary. The ridge makes the system positive definite from zero
        observations on, so there is nothing to disambiguate.

        The sign constraint stays: with two coefficients the active set is
        enumerable — the unconstrained solution, each axis alone, the origin —
        so this is exact NNLS with no iteration and no tolerance to tune.
        """
        if self.peso <= 0:
            return max(0.0, prior[0]), max(0.0, prior[1])
        # `s_ii / peso` é o x_i² médio observado; multiplicado por n0, o prior
        # passa a valer n0 observações em peso efetivo. Regressor que nunca
        # apareceu (s_ii = 0) fica cravado no prior em vez de indeterminado.
        t0_reg = n0 * self.s00 / self.peso if self.s00 > 0 else 1.0
        t1_reg = n0 * self.s11 / self.peso if self.s11 > 0 else 1.0
        s00 = self.s00 + t0_reg
        s11 = self.s11 + t1_reg
        s01 = self.s01
        u0 = self.u0 + t0_reg * prior[0]
        u1 = self.u1 + t1_reg * prior[1]

        def objetivo(t0: float, t1: float) -> float:
            return (
                t0 * t0 * s00 + 2 * t0 * t1 * s01 + t1 * t1 * s11
                - 2 * (t0 * u0 + t1 * u1)
            )

        cands: list[tuple[float, float]] = [(0.0, 0.0)]
        if s00 > 0:
            cands.append((max(0.0, u0 / s00), 0.0))
        if s11 > 0:
            cands.append((0.0, max(0.0, u1 / s11)))
        det = s00 * s11 - s01 * s01
        if abs(det) > 1e-18:
            t0 = (u0 * s11 - u1 * s01) / det
            t1 = (u1 * s00 - u0 * s01) / det
            if t0 >= 0 and t1 >= 0:
                cands.append((t0, t1))
        return min(cands, key=lambda c: objetivo(*c))

    def peso_de_huber(self, previsto: float, medido: float) -> float:
        """IRLS weight in log space, using the *previous* fit as reference.

        Genuine dispersion enters with decreasing weight instead of being
        excluded. This is the line that lets the estimator learn that a CSV is
        expensive — the v1 rejected it at exactly ratio 6,0.
        """
        if previsto <= 0 or medido <= 0:
            return 1.0
        # Sempre, desde a primeira observação. A versão anterior só pesava
        # depois de quatro, e as quatro primeiras entravam cruas — o que dava a
        # uma medição absurda o poder de mandar o coeficiente de máquina. Há
        # sempre uma referência: o prior **é** um ajuste.
        desvio = abs(math.log(medido / previsto)) / HUBER_LOG
        if desvio <= 1.0:
            return 1.0
        # Peso de Cauchy: cai com o **quadrado** do desvio, não com o inverso do
        # log. Para um desvio de 281× o Huber clássico devolvia 0,12 — alto o
        # bastante para uma medição só mexer no coeficiente de máquina, que
        # depois multiplica os 51 mil chunks de um PDF de 50 MB. Aqui devolve
        # 0,015.
        #
        # E não zera nunca, ao contrário de um peso redescendente: o que separa
        # "absurdo" de "caro de verdade" não é a distância, é **quantos
        # concordam**. Zerar mataria a única forma de aprender a cauda — 25
        # observações de CSV a 6× cada uma, que juntas somam peso e movem o
        # ajuste, enquanto uma sozinha não move.
        return 1.0 / (1.0 + desvio * desvio)

    def como_json(self) -> dict[str, float]:
        return {
            "s00": self.s00, "s01": self.s01, "s11": self.s11,
            "u0": self.u0, "u1": self.u1, "peso": self.peso, "n": self.n,
        }

    @classmethod
    def de_json(cls, d: dict | None) -> "Ajuste":
        if not d:
            return cls()
        return cls(
            s00=float(d.get("s00", 0.0)), s01=float(d.get("s01", 0.0)),
            s11=float(d.get("s11", 0.0)), u0=float(d.get("u0", 0.0)),
            u1=float(d.get("u1", 0.0)), peso=float(d.get("peso", 0.0)),
            n=int(d.get("n", 0)),
        )


def encolher(local: float, prior: float, n: int, n0: float = N0_ENCOLHIMENTO) -> float:
    """Empirical-Bayes blend. With 0 observations it is the prior; with `n0`
    it is half; with 10·n0 it is 91% local. Replaces `if n < k` scattered
    around the code with one curve."""
    if n <= 0:
        return prior
    w = n / (n + n0)
    return w * local + (1.0 - w) * prior


# --------------------------------------------------------------------------
# machine half


@dataclass
class PerfilMaquina:
    """`a_io`, `a_ch`, `c0`, `c1` and one `g` per effort profile.

    `s_grava ≈ a_io + a_ch·n_chunks` — the write is not a constant: LanceDB
    appends one fragment per document (~40 ms measured at one chunk) and grows
    with the chunk count.

    `s_embed ≈ g[perfil] · (c0·n_chunks + c1·tokens)` — and `g` multiplies
    **only** this term. That is the whole correction: from `ritmo=1.0` to
    `0.5` the embed stage went 2,1× while the document went 1,20×, because the
    ratio of encoder work to I/O work changes with the file. A single global
    scalar cannot be both; applied to the encoder alone, `g` is identifiable.
    """

    fingerprint: str = ""
    model_id: str = ""
    grava: Ajuste = field(default_factory=Ajuste)
    embed: Ajuste = field(default_factory=Ajuste)
    pulo: Ajuste = field(default_factory=Ajuste)
    # maior n_chunks já observado — a fronteira da faixa em que o ajuste vale
    _max_chunks: float = 0.0
    # perfil -> (soma_medido, soma_previsto, n) para o fator pareado
    _g: dict[str, list[float]] = field(default_factory=dict)
    # perfil -> quantas observações de embed vieram dele
    _por_perfil: dict[str, int] = field(default_factory=dict)

    # priores de semente, medidos em 26/08/2026 no notebook corporativo
    PRIOR_A_IO = 0.042
    PRIOR_A_CH = 0.0
    PRIOR_C0 = 0.019
    PRIOR_C1 = 0.00269
    PRIOR_PULO_FIXO = 0.010
    PRIOR_PULO_MB = 0.5

    def _grava(self) -> tuple[float, float]:
        return self.grava.resolver(prior=(self.PRIOR_A_IO, self.PRIOR_A_CH))

    def _embed(self) -> tuple[float, float]:
        return self.embed.resolver(prior=(self.PRIOR_C0, self.PRIOR_C1))

    @property
    def a_io(self) -> float:
        return self._grava()[0]

    @property
    def a_ch(self) -> float:
        return self._grava()[1]

    @property
    def c0(self) -> float:
        return self._embed()[0]

    @property
    def c1(self) -> float:
        return self._embed()[1]

    def custo_do_pulo(self, mb: float) -> float:
        """Unchanged document: sha256 plus I/O, no encoder. A re-scan of an
        indexed corpus is almost entirely this, and predicting it with the full
        model is what makes the bar ask for hours on a job of minutes."""
        fixo, por_mb = self.pulo.resolver(
            prior=(self.PRIOR_PULO_FIXO, self.PRIOR_PULO_MB)
        )
        return max(0.0, fixo + por_mb * mb)

    def confianca_em(self, n_chunks: float) -> float:
        """1,0 dentro da faixa medida, caindo para 0 conforme se afasta dela."""
        if self._max_chunks <= 0:
            return 0.0
        limite = FATOR_DE_EXTRAPOLACAO * self._max_chunks
        if n_chunks <= limite:
            return 1.0
        return max(0.0, limite / n_chunks)

    def custo_do_encoder(self, n_chunks: float, tokens: float, perfil: str) -> float:
        """Custo do encoder, encolhido para o prior fora da faixa medida.

        Dentro da faixa vale o que foi aprendido. Fora, a previsão é uma mistura
        entre o aprendido e o prior, com peso na distância — porque o ajuste
        acertar no ponto medido não o autoriza a extrapolar mil vezes além.
        """
        aprendido = self.c0 * n_chunks + self.c1 * tokens
        w = self.confianca_em(n_chunks)
        if w >= 1.0:
            return aprendido * self.g(perfil)
        do_prior = self.PRIOR_C0 * n_chunks + self.PRIOR_C1 * tokens
        return (w * aprendido + (1.0 - w) * do_prior) * self.g(perfil)

    def g(self, perfil: str) -> float:
        semente = 1.0 / DUTY.get(perfil, 1.0)
        if perfil == PERFIL_REFERENCIA:
            return 1.0
        medido, previsto, n = self._g.get(perfil, [0.0, 0.0, 0])
        local = (medido / previsto) if previsto > 0 else semente
        return max(0.05, encolher(local, semente, int(n)))

    OBS_PARA_PAREAR = 5
    """Observações no perfil de referência necessárias para `g` sair da semente."""

    @property
    def pareavel(self) -> bool:
        return self._por_perfil.get(PERFIL_REFERENCIA, 0) >= self.OBS_PARA_PAREAR

    def observar_g(self, perfil: str, previsto_ref: float, medido: float) -> None:
        """Aprendizado **pareado** — e só pareado.

        `g` e `(c0, c1)` explicam o mesmo dado: numa execução que só viu um
        perfil, o produto `g·c` é identificável e a separação não é. Mover `g`
        ali é escolher arbitrariamente uma das infinitas fatorações, e a
        escolha errada estraga a previsão do *outro* perfil, que é justamente
        para o que `g` serve.

        Então `g` só sai da semente quando existe medição no perfil de
        referência para ancorar. Sem âncora, `(c0, c1)` absorve a velocidade da
        máquina — o que prevê **este** perfil corretamente — e a previsão de
        outro perfil usa a razão entre as sementes, que é a melhor inferência
        disponível.

        Limite conhecido: uma máquina que nunca rode em `maximo` nunca ancora, e
        fica na razão das sementes para sempre. É honesto e é barato de sair
        dessa (uma passada curta em `maximo`), ao contrário de um `g` aprendido
        de dados que não o determinam.
        """
        if perfil == PERFIL_REFERENCIA or previsto_ref <= 0 or medido <= 0:
            return
        if not self.pareavel:
            return
        acc = self._g.setdefault(perfil, [0.0, 0.0, 0])
        acc[0] = LAMBDA * acc[0] + medido
        acc[1] = LAMBDA * acc[1] + previsto_ref
        acc[2] = int(acc[2]) + 1

    def observar(
        self,
        *,
        perfil: str,
        n_chunks: int,
        tokens: int,
        s_embed: float | None,
        s_grava: float | None,
        mb: float = 0.0,
        s_pulo: float | None = None,
    ) -> None:
        if s_grava is not None and s_grava >= 0:
            previsto = self.a_io + self.a_ch * n_chunks
            p = self.grava.peso_de_huber(previsto, s_grava)
            self.grava.observar(1.0, float(n_chunks), s_grava, peso=p)
        if s_embed is not None and s_embed > 0 and n_chunks > 0:
            self._max_chunks = max(self._max_chunks, float(n_chunks))
            self._por_perfil[perfil] = self._por_perfil.get(perfil, 0) + 1
            fator = self.g(perfil)
            # desconfundir: normaliza para o perfil de referência ANTES de
            # entrar no acumulador, senão a inclinação absorve o perfil e os
            # dois nunca se separam
            base = self.c0 * n_chunks + self.c1 * tokens
            self.observar_g(perfil, base, s_embed)
            normalizado = s_embed / max(fator, 1e-6)
            p = self.embed.peso_de_huber(base, normalizado)
            self.embed.observar(float(n_chunks), float(tokens), normalizado, peso=p)
        if s_pulo is not None and s_pulo >= 0:
            previsto = self.custo_do_pulo(mb)
            p = self.pulo.peso_de_huber(previsto, s_pulo)
            self.pulo.observar(1.0, mb, s_pulo, peso=p)

    def como_json(self) -> dict:
        return {
            "grava": self.grava.como_json(),
            "embed": self.embed.como_json(),
            "pulo": self.pulo.como_json(),
            "g": {k: list(v) for k, v in self._g.items()},
            "por_perfil": dict(self._por_perfil),
            "max_chunks": self._max_chunks,
        }

    @classmethod
    def de_json(cls, fingerprint: str, model_id: str, d: dict | None) -> "PerfilMaquina":
        d = d or {}
        return cls(
            fingerprint=fingerprint,
            model_id=model_id,
            grava=Ajuste.de_json(d.get("grava")),
            embed=Ajuste.de_json(d.get("embed")),
            pulo=Ajuste.de_json(d.get("pulo")),
            _g={k: list(v) for k, v in (d.get("g") or {}).items()},
            _por_perfil={k: int(v) for k, v in (d.get("por_perfil") or {}).items()},
            _max_chunks=float(d.get("max_chunks") or 0.0),
        )

    @property
    def n_obs(self) -> int:
        return self.embed.n


# --------------------------------------------------------------------------
# format half


@dataclass
class PerfilFormato:
    """`k_tok` (tokens per MB), `tok_por_chunk`, `p_parse` and `p_ok`.

    `k_tok` and `tok_por_chunk` are properties of the *format*, so they ship as
    a prior and transfer between machines. `p_parse` does not — opening a PDF
    costs what this machine's CPU costs.
    """

    tipo: str = ""
    k_tok: float = 0.0
    tok_por_chunk: float = 0.0
    p_parse: float = 0.0
    p_ok: float = 1.0
    n_obs: int = 0
    _mb: float = 0.0
    _tokens: float = 0.0
    _chunks: float = 0.0
    _ok: float = 0.0
    _docs: float = 0.0
    parse: Ajuste = field(default_factory=Ajuste)

    def observar(
        self, *, mb: float, tokens: int, n_chunks: int, ok: bool, s_parse: float | None
    ) -> None:
        """`ok` significa **pagou o encoder**, não "terminou sem erro".

        Um `duplicado` termina `ok` e nunca chega ao encoder; contá-lo como ok
        faria a fração prever trabalho de embed que não acontece. E MB/tokens
        só entram quando houve chunk — senão um documento vazio de 40 MB
        derrubaria `k_tok` do tipo inteiro.
        """
        self._ok = LAMBDA * self._ok + (1.0 if ok else 0.0)
        self._docs = LAMBDA * self._docs + 1.0
        self.n_obs += 1
        if n_chunks > 0 and tokens > 0 and mb > 0:
            self._mb = LAMBDA * self._mb + mb
            self._tokens = LAMBDA * self._tokens + tokens
            self._chunks = LAMBDA * self._chunks + n_chunks
        if s_parse is not None and s_parse >= 0:
            previsto = self.p_parse * mb
            p = self.parse.peso_de_huber(previsto, s_parse)
            self.parse.observar(1.0, mb, s_parse, peso=p)

    def valores(self, prior: "PerfilFormato") -> tuple[float, float, float, float]:
        """(k_tok, tok_por_chunk, p_parse_fixo, p_parse_mb), já encolhidos."""
        k_local = (self._tokens / self._mb) if self._mb > 1e-9 else 0.0
        tpc_local = (self._tokens / self._chunks) if self._chunks > 0 else 0.0
        k = encolher(k_local, prior.k_tok, self.n_obs)
        tpc = encolher(tpc_local, prior.tok_por_chunk, self.n_obs)
        f0, f1 = self.parse.resolver(prior=(0.0, prior.p_parse))
        return k, max(tpc, 1.0), max(f0, 0.0), max(f1, 0.0)

    def fracao_ok(self, prior: "PerfilFormato") -> float:
        local = (self._ok / self._docs) if self._docs > 0 else 1.0
        return min(1.0, max(0.0, encolher(local, prior.p_ok, self.n_obs)))

    def como_json(self) -> dict:
        return {
            "mb": self._mb, "tokens": self._tokens, "chunks": self._chunks,
            "ok": self._ok, "docs": self._docs, "n": self.n_obs,
            "parse": self.parse.como_json(),
        }

    @classmethod
    def de_json(cls, tipo: str, d: dict | None) -> "PerfilFormato":
        d = d or {}
        p = cls(tipo=tipo)
        p._mb = float(d.get("mb", 0.0))
        p._tokens = float(d.get("tokens", 0.0))
        p._chunks = float(d.get("chunks", 0.0))
        p._ok = float(d.get("ok", 0.0))
        p._docs = float(d.get("docs", 0.0))
        p.n_obs = int(d.get("n", 0))
        p.parse = Ajuste.de_json(d.get("parse"))
        return p


PRIOR_FORMATO: dict[str, PerfilFormato] = {
    # Medidos em 26/08/2026 sobre `corpus-e1` (semente 42) com o tokenizador
    # real do `e5-large`. `n_obs` é honesto de propósito: é o que o
    # encolhimento usa para decidir o quanto confiar no prior, e n=1 tem de
    # ceder rápido à medição local.
    "txt":   PerfilFormato("txt", k_tok=116_882, tok_por_chunk=13, p_parse=2.0, n_obs=3069),
    "md":    PerfilFormato("md", k_tok=331_948, tok_por_chunk=36, p_parse=2.0, n_obs=32),
    "csv":   PerfilFormato("csv", k_tok=386_353, tok_por_chunk=287, p_parse=8.0, n_obs=4),
    "eml":   PerfilFormato("eml", k_tok=197_961, tok_por_chunk=70, p_parse=4.0, n_obs=101),
    "msg":   PerfilFormato("msg", k_tok=21_358, tok_por_chunk=73, p_parse=4.0, n_obs=1),
    "docx":  PerfilFormato("docx", k_tok=1_058, tok_por_chunk=37, p_parse=6.0, n_obs=1),
    "pptx":  PerfilFormato("pptx", k_tok=1_442, tok_por_chunk=39, p_parse=6.0, n_obs=1),
    "xlsx":  PerfilFormato("xlsx", k_tok=10_184, tok_por_chunk=14, p_parse=10.0, n_obs=3),
    "doc":   PerfilFormato("doc", k_tok=15_974, tok_por_chunk=39, p_parse=8.0, n_obs=1),
    "ppt":   PerfilFormato("ppt", k_tok=15_974, tok_por_chunk=39, p_parse=8.0, n_obs=1),
    "xls":   PerfilFormato("xls", k_tok=77_101, tok_por_chunk=5, p_parse=10.0, n_obs=1),
    "rtf":   PerfilFormato("rtf", k_tok=332_881, tok_por_chunk=40, p_parse=3.0, n_obs=1),
    # `pdf:texto` tem uma observação só; `pdf:ocr` **não tem nenhuma**, e o OCR
    # existe desde o PR #38 (R1.2 / F4-O) — então a lacuna é de medição, não de
    # implementação. Prior ausente de propósito: inventar coeficiente aqui
    # produziria número confiante sobre trabalho que ninguém mediu, e OCR é o
    # caminho mais caro do indexador. O estado cai para `calibrando` quando
    # aparecer um digitalizado, até a primeira passada real medir.
    "pdf:texto": PerfilFormato("pdf:texto", k_tok=41_814, tok_por_chunk=39, p_parse=15.0, n_obs=1),
}

PRIOR_GENERICO = PerfilFormato("*", k_tok=50_000, tok_por_chunk=120, p_parse=8.0, n_obs=0)
"""Formato sem prior medido. `n_obs=0` faz o encolhimento ceder à primeira
observação local, e §9 mantém a tela sem número enquanto a cobertura não
fechar."""

SEM_PRIOR = frozenset({"pdf:ocr"})
"""Tipos cujo custo ninguém mediu neste projeto. Nunca entram como
`calibrado`."""


def prior_de(tipo: str) -> PerfilFormato:
    if tipo in PRIOR_FORMATO:
        return PRIOR_FORMATO[tipo]
    base = tipo.split(":", 1)[0]
    if base in PRIOR_FORMATO:
        return PRIOR_FORMATO[base]
    # `pdf` sem natureza conhecida — antes do primeiro parse não se sabe se é
    # digitalizado — cai no prior da variante de texto, que é a mistura
    # dominante. Sem esta linha ele caía no genérico e a cobertura de §9 lia
    # zero para todo PDF, inclusive os que já foram medidos.
    if f"{base}:texto" in PRIOR_FORMATO:
        return PRIOR_FORMATO[f"{base}:texto"]
    # legado herda do irmão moderno como prior, nunca como verdade — o F4-L
    # existe porque o container OLE mente sobre o próprio conteúdo
    irmao = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}.get(base)
    if irmao and irmao in PRIOR_FORMATO:
        return PRIOR_FORMATO[irmao]
    return PRIOR_GENERICO


def tipo_de(rel: str, *, digitalizado: bool | None = None, tem_tabela: bool | None = None) -> str:
    """The type key is not the extension.

    `pdf:ocr` cannot be told from `pdf:texto` by the file name — only the
    parser knows, and only after it has opened the file. The registry already
    carries the columns (`digitalizado`, `tem_tabela`), so the refinement costs
    nothing; before the first parse the caller passes `None` and gets the
    extension, whose prior is the observed mixture.
    """
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    if ext == "pdf" and digitalizado is not None:
        return "pdf:ocr" if digitalizado else "pdf:texto"
    if ext in {"xlsx", "xlsm", "xls"} and tem_tabela is not None:
        return f"{ext}:{'tabela' if tem_tabela else 'texto'}"
    return ext


# --------------------------------------------------------------------------
# the store


ESQUEMA = """
CREATE TABLE IF NOT EXISTS perfil_maquina (
    fingerprint TEXT NOT NULL,
    model_id    TEXT NOT NULL,
    dados       TEXT NOT NULL DEFAULT '{}',
    atualizado  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (fingerprint, model_id)
);
CREATE TABLE IF NOT EXISTS perfil_formato (
    fingerprint TEXT NOT NULL,
    base_id     TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    dados       TEXT NOT NULL DEFAULT '{}',
    atualizado  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (fingerprint, base_id, tipo)
);
CREATE TABLE IF NOT EXISTS execucoes_previstas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    base_id     TEXT NOT NULL,
    p50         REAL NOT NULL,
    p90         REAL NOT NULL,
    real        REAL,
    dentro      INTEGER,
    quando      TEXT NOT NULL DEFAULT ''
);
"""


class Calibracao:
    """Read/write of the master table. One file per machine.

    The machine half is keyed by fingerprint only; the format half also by
    base, because a base's PDFs can be all scanned and another's all native.
    """

    def __init__(self, fingerprint: str, model_id: str, base_id: str, diretorio: Path | None = None):
        self.fingerprint = fingerprint
        self.model_id = model_id
        self.base_id = base_id or "?"
        self.diretorio = diretorio or diretorio_de_calibracao()
        self.maquina = PerfilMaquina(fingerprint, model_id)
        self.formatos: dict[str, PerfilFormato] = {}
        self._con: sqlite3.Connection | None = None
        self._sujo = False
        self._sem_disco = False
        self.descartes_regime = 0

    @classmethod
    def em_memoria(cls) -> "Calibracao":
        """Calibragem que não persiste — priores e aprendizado só desta sessão.

        Existe para que `Estimador()` funcione sem cerimônia: um estimador que
        exige banco em disco para ser construído empurra todo chamador a
        inventar um, e é assim que teste e painel passam a montar caminhos de
        calibragem que ninguém quis.
        """
        inst = cls("memoria", "memoria", "memoria", Path("."))
        inst._sem_disco = True
        return inst

    # -- persistência

    @property
    def caminho(self) -> Path:
        return self.diretorio / "calibracao.db"

    def _conectar(self) -> sqlite3.Connection | None:
        if self._sem_disco:
            return None
        if self._con is not None:
            return self._con
        try:
            self.diretorio.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(str(self.caminho), timeout=10)
            con.executescript(ESQUEMA)
            con.commit()
            self._con = con
        except Exception as erro:  # noqa: BLE001 — sem calibragem persistida ainda funciona
            log.warning("calibração não pôde ser aberta em %s: %s", self.caminho, erro)
            return None
        return self._con

    def carregar(self) -> "Calibracao":
        con = self._conectar()
        if con is None:
            return self
        try:
            linha = con.execute(
                "SELECT dados FROM perfil_maquina WHERE fingerprint=? AND model_id=?",
                (self.fingerprint, self.model_id),
            ).fetchone()
            if linha:
                self.maquina = PerfilMaquina.de_json(
                    self.fingerprint, self.model_id, json.loads(linha[0])
                )
            for tipo, dados in con.execute(
                "SELECT tipo, dados FROM perfil_formato"
                " WHERE fingerprint=? AND base_id=?",
                (self.fingerprint, self.base_id),
            ):
                self.formatos[tipo] = PerfilFormato.de_json(tipo, json.loads(dados))
        except Exception as erro:  # noqa: BLE001 — calibragem ilegível: prior é melhor que passada morta
            log.warning("calibração ilegível, começando do prior: %s", erro)
        return self

    def gravar(self) -> None:
        if not self._sujo:
            return
        con = self._conectar()
        if con is None:
            return
        agora = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            con.execute(
                "INSERT OR REPLACE INTO perfil_maquina (fingerprint, model_id, dados, atualizado)"
                " VALUES (?,?,?,?)",
                (self.fingerprint, self.model_id, json.dumps(self.maquina.como_json()), agora),
            )
            con.executemany(
                "INSERT OR REPLACE INTO perfil_formato"
                " (fingerprint, base_id, tipo, dados, atualizado) VALUES (?,?,?,?,?)",
                [
                    (self.fingerprint, self.base_id, t, json.dumps(p.como_json()), agora)
                    for t, p in self.formatos.items()
                ],
            )
            con.commit()
            self._sujo = False
        except Exception as erro:  # noqa: BLE001 — gravar calibragem não pode derrubar a indexação
            log.warning("calibração não pôde ser gravada: %s", erro)

    def fechar(self) -> None:
        self.gravar()
        if self._con is not None:
            try:
                self._con.close()
            finally:
                self._con = None

    # -- uso

    def formato(self, tipo: str) -> PerfilFormato:
        p = self.formatos.get(tipo)
        if p is None:
            p = PerfilFormato(tipo)
            self.formatos[tipo] = p
        return p

    def observar(self, obs) -> None:  # noqa: ANN001 — Observacao, evita import circular
        """Feed one document's measurement into both halves.

        Wall-clock never gets here: `obs.suspeito` marks a document the clock
        cannot vouch for, and it is dropped. That is D4 — and the reason it is
        checked here, once, instead of at each of the five call sites.

        F4-R.2: EcoQoS-on is the other drop. Mixing it with EcoQoS-off is the
        22× bias the fingerprint cannot see.
        """
        if obs.suspeito:
            return
        if not aceita_regime(getattr(obs, "ecoqos", None)):
            self.descartes_regime += 1
            return
        self._sujo = True
        tipo = obs.tipo
        fmt = self.formato(tipo)
        if obs.situacao in CAMINHOS_BARATOS:
            self.maquina.observar(
                perfil=obs.perfil, n_chunks=0, tokens=0, s_embed=None,
                s_grava=None, mb=obs.mb, s_pulo=obs.s_total_ativo,
            )
            return
        self.maquina.observar(
            perfil=obs.perfil,
            n_chunks=obs.n_chunks,
            tokens=obs.tokens,
            s_embed=obs.s_embed,
            s_grava=obs.s_grava,
            mb=obs.mb,
        )
        fmt.observar(
            mb=obs.mb,
            tokens=obs.tokens,
            n_chunks=obs.n_chunks,
            ok=bool(obs.s_embed and obs.s_embed > 0),
            s_parse=obs.s_parse,
        )

    def prever(self, tipo: str, mb: float, perfil: str, *, situacao: str = "novo") -> float:
        """Expected active seconds for one document, before opening it."""
        if situacao in CAMINHOS_BARATOS:
            return self.maquina.custo_do_pulo(mb)
        fmt = self.formato(tipo)
        prior = prior_de(tipo)
        k_tok, tpc, parse0, parse_mb = fmt.valores(prior)
        tokens = max(0.0, k_tok * mb)
        n_chunks = max(1.0, tokens / tpc) if tokens > 0 else 0.0
        m = self.maquina
        encoder = m.custo_do_encoder(n_chunks, tokens, perfil)
        ok = fmt.fracao_ok(prior)
        return max(
            0.0,
            m.a_io
            + m.a_ch * n_chunks * ok
            + parse0
            + parse_mb * mb
            + encoder * ok,
        )

    def cobertura(self, tipos_restantes: dict[str, float]) -> float:
        """Fraction of the remaining MB that sits in types with enough local
        observations. This — not a cycle count — is the display gate: 3.000
        `.txt` teach nothing about the 40 PDFs that are left."""
        total = sum(tipos_restantes.values())
        if total <= 0:
            return 1.0
        coberto = 0.0
        for tipo, mb in tipos_restantes.items():
            if tipo in SEM_PRIOR:
                continue
            fmt = self.formatos.get(tipo)
            prior = prior_de(tipo)
            n = (fmt.n_obs if fmt else 0) + (prior.n_obs if prior is not PRIOR_GENERICO else 0)
            if n >= N0_ENCOLHIMENTO:
                coberto += mb
        return coberto / total

    def registrar_previsao(self, p50: float, p90: float) -> int | None:
        con = self._conectar()
        if con is None:
            return None
        try:
            cur = con.execute(
                "INSERT INTO execucoes_previstas (fingerprint, base_id, p50, p90, quando)"
                " VALUES (?,?,?,?,?)",
                (self.fingerprint, self.base_id, p50, p90,
                 time.strftime("%Y-%m-%dT%H:%M:%S")),
            )
            con.commit()
            return int(cur.lastrowid)
        except Exception as erro:  # noqa: BLE001 — registrar previsão é telemetria, não requisito
            log.debug("previsão não registrada: %s", erro)
            return None

    def fechar_previsao(self, previsao: int | None, real: float) -> None:
        """Calibration self-test: the estimate now has measured regression,
        like everything else in this project."""
        if previsao is None:
            return
        con = self._conectar()
        if con is None:
            return
        try:
            linha = con.execute(
                "SELECT p90 FROM execucoes_previstas WHERE id=?", (previsao,)
            ).fetchone()
            dentro = 1 if (linha and real <= float(linha[0])) else 0
            con.execute(
                "UPDATE execucoes_previstas SET real=?, dentro=? WHERE id=?",
                (real, dentro, previsao),
            )
            con.commit()
            fora = con.execute(
                "SELECT count(*), sum(1-dentro) FROM execucoes_previstas"
                " WHERE fingerprint=? AND real IS NOT NULL",
                (self.fingerprint,),
            ).fetchone()
            if fora and fora[0] >= 10 and (fora[1] or 0) / fora[0] > 0.10:
                log.warning(
                    "calibragem suspeita: %d de %d execuções passaram da p90 prevista",
                    fora[1], fora[0],
                )
        except Exception as erro:  # noqa: BLE001 — fechar previsão é telemetria, não requisito
            log.debug("previsão não fechada: %s", erro)
