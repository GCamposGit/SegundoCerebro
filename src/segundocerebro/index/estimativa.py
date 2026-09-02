"""Quanto tempo falta — e os jeitos de errar isso.

Método e coeficientes em [`docs/spec-estimativa-v2.md`](../../../docs/spec-estimativa-v2.md).

Os **quatro** erros que a v1 deste módulo existia para não cometer seguem
válidos, e a v2 não os reintroduz:

1. **Denominador errado.** O censo conta 3.154 arquivos; o indexador processa
   1.601. Usar a contagem bruta reporta 45% quando o real é 91%. Por isso o
   total é *declarado* por quem enumera — o mesmo `iter_files` do indexador.
2. **Contar documentos como se custassem o mesmo.** Mediana de 12 chunks por
   documento, média 67,8, máximo 7.017. Barra por contagem anda em solavancos.
3. **Tempo de parede.** 64 h de relógio contra ~39 h de trabalho. Daí
   `Relogio`, que conta só tempo ativo.
4. **Extrapolação linear ingênua.** `decorrido ÷ feito × restante` supõe itens
   intercambiáveis, e a ordem da varredura não é aleatória.

E **cinco** que a v1 cometia, medidos em 26/08/2026 (§1 da especificação):

5. **Intercepto por documento 350× alto**, absorvendo custo de chunk: 15 s
   contra 42 ms medidos. Agora `a_io` é ajustado, não constante.
6. **Fator global escalar** compensando um erro que é diferente por tipo.
   Agora os coeficientes são por tipo, fatorados em máquina × formato.
7. **Clipe de outlier cego ao pior caso**: a razão 6,0 do CSV caía exatamente
   na fronteira de rejeição. Agora a cauda entra com peso de Huber e só sai
   observação de relógio suspeito.
8. **Tempo de parede na calibragem**, carregado entre execuções. Agora o alvo é
   tempo ativo por etapa, e um documento atravessado por suspensão é descartado.
9. **`p50` e `p90` em bases diferentes**, o que invertia a faixa. Agora saem do
   mesmo modelo na mesma passada, com asserção.
"""

from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field

from .calibracao import Calibracao, tipo_de
from .mapa import Mapa
from .regime_maquina import ecoqos_ativo

# ---------------------------------------------------------------------------
# prior de formato herdado da v1 — segue servindo de semente para `peso_de`,
# que o painel e o censo usam para ordenar trabalho antes de haver calibragem.

SEGUNDOS_POR_MB: dict[str, float] = {
    "pptx": 3.8,
    "pdf": 48.7,
    "xlsx": 487.2,
    "txt": 496.0,
    "csv": 496.0,
    "md": 496.0,
    "markdown": 496.0,
    "docx": 522.5,
}
"""Medianas de s/MB do run de 13–16/08/2026. **Prior de ordenação**, não mais
o modelo: a estimativa passou a sair de `calibracao.PerfilFormato`."""

SEGUNDOS_POR_MB_PADRAO = 50.0
SEGUNDOS_POR_DOCUMENTO = 15.0
"""Mantido para `peso_de`. O custo fixo real por documento é 42 ms — os 15 s
absorviam custo por chunk de um corpus com 45,6 chunks/doc. Ver defeito 5."""

FATOR_GPU = 28.0
MEIA_VIDA = 20
CLIP_OUTLIER = 6.0
"""Mantidos por compatibilidade de import. `CLIP_OUTLIER` **não é mais usado**
para rejeitar observação: era o defeito 7."""

ALFA_UI = 0.2
"""Só para a fração exibida. A estimativa de tempo não é mais suavizada na
saída — suavizar p50 e não p90 era o defeito 9."""

LIMIAR_DE_SUSPENSAO = 120.0
"""Salto de relógio acima disto é máquina dormindo, não documento lento.

A justificativa da v1 dizia que nenhum documento levava dois minutos entre
tiques; isso é falso desde 26/08/2026 (uma planilha de 269 KB levou ~15 min).
O limite continua válido por outro motivo: os tiques não vêm de fronteira de
documento, vêm do callback de lote do embed e do laço de `wait` de 2 s. Um
documento longo tica muitas vezes; hibernação não tica nenhuma."""

SORTEIOS = 200
"""Sorteios do Monte Carlo da faixa. Aritmética de milissegundos sobre ~15
tipos, uma vez por ciclo."""

SEMENTE_FAIXA = 20260826
"""Semente fixa. A faixa não pode tremer entre duas publicações com o mesmo
estado — isso leria como instabilidade, e reamostrar não acrescenta informação."""

COBERTURA_MINIMA = 0.80
LARGURA_MAXIMA = 1.5
RESERVATORIO = 200


def _semente(extensao: str) -> float:
    bruto = SEGUNDOS_POR_MB.get(extensao, SEGUNDOS_POR_MB_PADRAO)
    if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        return bruto / FATOR_GPU
    return bruto


def peso_de(rel: str, tamanho: int) -> float:
    """Trabalho estimado de um arquivo pela semente da v1, em segundos.

    Segue existindo porque a fila de prioridade precisa ordenar trabalho antes
    de qualquer calibragem. **Não** é mais o que a barra exibe.
    """
    extensao = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    return SEGUNDOS_POR_DOCUMENTO + _semente(extensao) * (tamanho / 1e6)


# ---------------------------------------------------------------------------


@dataclass
class Relogio:
    """Tempo ativo, medido em relógio monotônico com suspensão descontada.

    `time.monotonic` não anda durante a hibernação no Windows, mas anda durante
    uma pausa de processo — e as duas coisas precisam sair da conta. Por isso o
    salto é detectado por diferença entre tiques, não por confiança no relógio.
    """

    _ativo: float = 0.0
    _ultimo: float | None = None
    suspensoes: int = 0
    parado: float = 0.0
    _em_pausa: bool = False
    _pausa_atual: float = 0.0

    def tique(self, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        self._em_pausa = False
        self._pausa_atual = 0.0
        if self._ultimo is not None:
            passou = agora - self._ultimo
            if passou > LIMIAR_DE_SUSPENSAO:
                self.suspensoes += 1
                self.parado += passou
            else:
                self._ativo += max(passou, 0.0)
        self._ultimo = agora

    def contar_parado(self, segundos: float, agora: float | None = None) -> None:
        """Pausa pedida pelo usuário: sai do tempo ativo sem virar suspensão."""
        dt = max(segundos, 0.0)
        self._em_pausa = True
        self._pausa_atual += dt
        self.parado += dt
        self._ultimo = time.monotonic() if agora is None else agora

    def fim_pausa(self) -> None:
        self._em_pausa = False
        self._pausa_atual = 0.0

    def restaurar(self, ativo: float = 0.0, parado: float = 0.0, suspensoes: int = 0) -> None:
        """Continua o relógio de um processo que morreu. O próximo tique não soma o buraco."""
        self._ativo = max(0.0, float(ativo))
        self.parado = max(0.0, float(parado))
        self.suspensoes = max(0, int(suspensoes))
        self._ultimo = None
        self._em_pausa = False
        self._pausa_atual = 0.0

    @property
    def ativo(self) -> float:
        return self._ativo

    @property
    def pausa_atual(self) -> float:
        return self._pausa_atual if self._em_pausa else 0.0


# ---------------------------------------------------------------------------


@dataclass
class Observacao:
    """One document's measurement. Per stage, in active time.

    Mixing stages is what let one coefficient absorb another and produced a
    15 s per-document intercept out of per-chunk cost (defeito 5). So each
    stage has its own target, and `suspeito` marks a clock the estimator cannot
    vouch for — dropped at a single place, in `Calibracao.observar`. F4-R.2
    drops EcoQoS-on the same way: another clock the coefficient cannot mix.
    """

    rel: str
    tipo: str
    mb: float
    n_chunks: int = 0
    tokens: int = 0
    s_parse: float | None = None
    s_chunk: float | None = None
    s_embed: float | None = None
    s_grava: float | None = None
    s_total_ativo: float = 0.0
    suspeito: bool = False
    perfil: str = "maximo"
    situacao: str = "novo"
    status: str = "ok"
    ecoqos: bool | None = None

    @property
    def previsto_zerado(self) -> bool:
        return self.mb <= 0 and self.n_chunks == 0

class Cronometro:
    """Per-document stopwatch, one instance per document.

    Reads suspensions off the `Relogio` instead of guessing: if the clock
    jumped while this document was in flight, the elapsed time is not the
    document's cost and the observation is marked `suspeito`.
    """

    __slots__ = ("relogio", "_t", "_ativo0", "_susp0", "_parado0", "etapas")

    def __init__(self, relogio: Relogio) -> None:
        self.relogio = relogio
        self._t = time.perf_counter()
        self._ativo0 = relogio.ativo
        self._susp0 = relogio.suspensoes
        self._parado0 = relogio.parado
        self.etapas: dict[str, float] = {}

    def marcar(self, etapa: str) -> None:
        agora = time.perf_counter()
        self.etapas[etapa] = self.etapas.get(etapa, 0.0) + (agora - self._t)
        self._t = agora

    def descartar(self) -> None:
        """Zera o cronômetro do trecho corrente sem creditar etapa."""
        self._t = time.perf_counter()

    @property
    def suspeito(self) -> bool:
        """Houve suspensão **ou pausa** enquanto este documento estava em voo.

        As duas invalidam o relógio do documento e por motivos diferentes:
        hibernação incrementa `suspensoes`, pausa pedida pelo usuário incrementa
        só `parado`. A primeira versão olhava apenas `suspensoes`, então um
        documento atravessado por um "Pausar" no painel entrava na calibragem
        com o tempo da pausa dentro — o defeito 8 voltando pela porta do lado.
        """
        return (
            self.relogio.suspensoes > self._susp0
            or self.relogio.parado > self._parado0 + 1e-9
        )

    @property
    def ativo(self) -> float:
        """Tempo do documento: a soma das etapas, validada pelo `Relogio`.

        A primeira versão devolvia `relogio.ativo - ativo0`, e uma tabela
        `medicoes` de um run real mostrou a soma das etapas **excedendo** o
        "ativo" em cerca de 2× em todos os documentos — impossível se as duas
        medidas estivessem certas. A causa: `Relogio.ativo` só avança em
        `tique()`, e os tiques são esparsos (laço de `wait` de 2 s e callback de
        lote), então o trecho entre o último tique e o fim do documento não
        estava contado.

        As etapas, ao contrário, cobrem o documento inteiro por construção —
        cada `marcar()` credita tudo desde a marca anterior, inclusive as folgas
        entre elas (publicar progresso, entrega de fila, ler comando). Então a
        soma **é** o tempo do documento.

        O papel do `Relogio` aqui é outro e continua essencial: dizer se houve
        suspensão ou pausa enquanto este documento estava em voo (`suspeito`).
        É isso que impede tempo de máquina dormindo de entrar na calibragem —
        o defeito 8 — e não o valor de `ativo`.
        """
        return max(0.0, sum(self.etapas.values()))

    def observacao(
        self,
        *,
        rel: str,
        tipo: str,
        mb: float,
        n_chunks: int = 0,
        tokens: int = 0,
        perfil: str = "maximo",
        situacao: str = "novo",
        status: str = "ok",
    ) -> Observacao:
        return Observacao(
            rel=rel,
            tipo=tipo,
            mb=mb,
            n_chunks=n_chunks,
            tokens=tokens,
            s_parse=self.etapas.get("parse"),
            s_chunk=self.etapas.get("chunk"),
            s_embed=self.etapas.get("embed"),
            s_grava=self.etapas.get("grava"),
            s_total_ativo=self.ativo,
            suspeito=self.suspeito,
            perfil=perfil,
            situacao=situacao,
            status=status,
            ecoqos=ecoqos_ativo(),
        )

@dataclass(frozen=True)
class Faixa:
    """Estimativa como faixa, nunca como ponto.

    A dispersão por documento é enorme — coeficiente de variação 4,6 — e a
    cauda é pesada: dois de 3.530 arquivos carregaram 49% dos chunks. A soma de
    milhares é confiável; um documento isolado não é.
    """

    p50: float
    p90: float

    def __post_init__(self) -> None:
        # invariante I1. p50 > p90 foi exibido em produção ("entre 4 h 8 min e
        # 2 h 13 min") porque um lado era suavizado e o outro não.
        assert self.p50 <= self.p90 + 1e-6, f"faixa invertida: p50={self.p50} p90={self.p90}"

    @property
    def vazia(self) -> bool:
        return self.p50 <= 0

    @property
    def largura_relativa(self) -> float:
        if self.p50 <= 0:
            return 0.0 if self.p90 <= 0 else float("inf")
        return (self.p90 - self.p50) / self.p50


CEGO = "cego"
CALIBRANDO = "calibrando"
CALIBRADO = "calibrado"


@dataclass
class Estimador:
    """Trabalho declarado por quem enumera, custo aprendido por quem executa.

    A previsão sai da tabela master (`Calibracao`) aplicada ao mapa restante
    (`Mapa`), e o mapa é derivado por diferença a cada ciclo — nunca
    decrementado.
    """

    calibracao: Calibracao = field(default_factory=Calibracao.em_memoria)
    perfil: str = "maximo"
    mapa: Mapa = field(default_factory=Mapa)
    documentos_totais: int = 0
    documentos_feitos: int = 0
    _residuos: dict[str, list[float]] = field(default_factory=dict)
    _previsto_total: float = 0.0
    _previsto_feito: float = 0.0
    _medido_feito: float = 0.0
    _previsao: int | None = None
    _descartadas: int = 0
    _versao: int = 0
    _faixa_cache: tuple[tuple, "Faixa"] | None = None

    # -- declaração

    def declarar(self, arquivos) -> None:  # noqa: ANN001 — iterável de (rel, tamanho, mtime)
        itens = list(arquivos)
        self.mapa.declarar(itens)
        self.documentos_totais = self.mapa.n_censo
        self._versao += 1
        self._previsto_total = self._prever_mapa(self.mapa.censo)

    def recalcular_mapa(self, estados: dict, precisa) -> None:  # noqa: ANN001
        """Re-derives `restante` from the registry. Called at cycle boundaries."""
        self.mapa.recalcular(estados, precisa)
        self.documentos_feitos = max(self.documentos_feitos, self.mapa.n_feito)
        self._versao += 1

    def pular(self, rel: str, tamanho: int) -> None:
        """Documento fora da fila de trabalho — filtrado antes de abrir.

        Duas contas diferentes, e confundi-las é fácil:

        - **Tempo restante**: o pulo custa zero, e é o que faz uma revarredura
          de acervo indexado fechar em minutos. Isso é do mapa, que simplesmente
          não conta o arquivo em `restante`.
        - **Barra**: o pulo conta o trabalho **cheio**, porque a barra responde
          "quanto deste acervo está indexado", não "quanto desta passada
          andou". Contar zero aqui faria uma retomada com 90% pronto abrir em
          0% e saltar para 100% — pior que barra imprecisa.
        """
        self._versao += 1
        self.documentos_feitos += 1
        self._previsto_feito += self.calibracao.prever(
            tipo_de(rel), tamanho / 1_048_576, self.perfil
        )

    # -- observação

    def registrar(self, obs: Observacao) -> None:
        """Documento processado: alimenta a tabela master e a dispersão."""
        self._versao += 1
        self.documentos_feitos += 1
        previsto = self.calibracao.prever(obs.tipo, obs.mb, self.perfil, situacao=obs.situacao)
        self._previsto_feito += previsto
        if obs.suspeito:
            self._descartadas += 1
            return
        self._medido_feito += obs.s_total_ativo
        self.calibracao.observar(obs)
        if previsto > 0 and obs.s_total_ativo > 0:
            res = self._residuos.setdefault(obs.tipo, [])
            res.append(math.log(obs.s_total_ativo / previsto))
            if len(res) > RESERVATORIO:
                del res[0]

    # -- previsão

    def _prever_mapa(self, fatias: dict) -> float:
        total = 0.0
        for tipo, fatia in fatias.items():
            if fatia.n <= 0:
                continue
            por_doc = fatia.mb / fatia.n
            total += fatia.n * self.calibracao.prever(tipo, por_doc, self.perfil)
        return total

    def _dispersao(self, tipo: str) -> tuple[float, float]:
        """(mu, sigma) do log-resíduo do tipo.

        **O viés não se empresta; a largura sim.** Com poucas observações de um
        tipo, o `sigma` do agregado é a melhor estimativa disponível da
        dispersão — mas o `mu` do agregado é o erro sistemático de *outros*
        tipos, e aplicá-lo aqui reintroduz o defeito que a v1 tinha por outro
        caminho: quarenta `.txt` lentos multiplicavam o restante de PDF por
        `exp(mu)`. Foi assim que este método nasceu errado, e foi
        `test_txt_pequeno_nao_infla_o_restante_de_pdf` que pegou.
        """
        propria = self._residuos.get(tipo) or []
        if len(propria) >= 5:
            mu = sum(propria) / len(propria)
            var = sum((x - mu) ** 2 for x in propria) / (len(propria) - 1)
            return mu, max(0.15, math.sqrt(var))

        todos: list[float] = []
        for v in self._residuos.values():
            todos.extend(v)
        if len(todos) < 5:
            # Sem amostra nenhuma a incerteza é grande, e a faixa tem de dizer
            # isso em vez de fingir precisão.
            return 0.0, 0.55
        media = sum(todos) / len(todos)
        var = sum((x - media) ** 2 for x in todos) / (len(todos) - 1)
        return 0.0, max(0.15, math.sqrt(var))

    def restante(self) -> Faixa:
        """Segundos ativos que faltam, como faixa.

        Ponto: soma por tipo do modelo aplicado ao mapa restante. Faixa: Monte
        Carlo sobre esse mapa — o quantil de uma soma não é a soma dos
        quantis, e com cauda pesada a diferença não é pequena.

        Os maiores arquivos restantes são sorteados **individualmente**; o
        resto entra pelo agregado do tipo, cuja dispersão encolhe com
        `sqrt(n)`. Tratar um agregado de mil arquivos com a dispersão de um só
        inflaria a faixa até não dizer nada.
        """
        chave = self._chave_da_faixa()
        if self._faixa_cache is not None and self._faixa_cache[0] == chave:
            return self._faixa_cache[1]
        faixa = self._calcular_faixa()
        self._faixa_cache = (chave, faixa)
        return faixa

    def _chave_da_faixa(self) -> tuple:
        """Chave derivada das **entradas**, não um contador de versão.

        `instantaneo()` pede a faixa três vezes por publicação, e cada pedido
        é um Monte Carlo — daí o cache. Mas contador incremental é a mesma
        classe de defeito do mapa decrementado: quem mexer no mapa por fora
        esquece de invalidar, e a faixa devolvida deixa de corresponder ao
        estado. Aconteceu no primeiro teste que escrevi. Derivar a chave torna
        isso impossível.
        """
        return (
            self._versao,
            self.mapa.n_restante,
            round(self.mapa.mb_restante, 6),
            len(self.mapa.maiores),
            tuple(sorted(self.mapa.restante)),
        )

    def _calcular_faixa(self) -> Faixa:
        if self.mapa.n_restante <= 0:
            return Faixa(0.0, 0.0)

        maiores = {i.rel: i for i in self.mapa.maiores}
        mb_maiores: dict[str, float] = {}
        n_maiores: dict[str, int] = {}
        for item in maiores.values():
            mb_maiores[item.tipo] = mb_maiores.get(item.tipo, 0.0) + item.mb
            n_maiores[item.tipo] = n_maiores.get(item.tipo, 0) + 1

        blocos: list[tuple[float, float, float, int]] = []  # (previsto, mu, sigma, n)
        for tipo, fatia in self.mapa.restante.items():
            n = fatia.n - n_maiores.get(tipo, 0)
            mb = fatia.mb - mb_maiores.get(tipo, 0.0)
            mu, sigma = self._dispersao(tipo)
            if n > 0 and mb >= 0:
                por_doc = mb / n
                previsto = n * self.calibracao.prever(tipo, por_doc, self.perfil)
                blocos.append((previsto, mu, sigma, n))
        individuais: list[tuple[float, float, float]] = []
        for item in maiores.values():
            mu, sigma = self._dispersao(item.tipo)
            individuais.append(
                (self.calibracao.prever(item.tipo, item.mb, self.perfil), mu, sigma)
            )

        ponto = sum(b[0] for b in blocos) + sum(i[0] for i in individuais)
        if ponto <= 0:
            return Faixa(0.0, 0.0)

        rng = random.Random(SEMENTE_FAIXA)
        somas: list[float] = []
        for _ in range(SORTEIOS):
            total = 0.0
            for previsto, mu, sigma, n in blocos:
                escala = sigma / math.sqrt(n)
                total += previsto * math.exp(rng.gauss(mu, escala))
            for previsto, mu, sigma in individuais:
                total += previsto * math.exp(rng.gauss(mu, sigma))
            somas.append(total)
        somas.sort()
        p50 = somas[len(somas) // 2]
        p90 = somas[min(int(len(somas) * 0.9), len(somas) - 1)]
        # I1 por construção: p90 é um quantil superior da mesma amostra que p50
        return Faixa(max(0.0, p50), max(0.0, max(p50, p90)))

    # -- estado de exibição

    @property
    def cobertura(self) -> float:
        return self.calibracao.cobertura(self.mapa.mb_restante_por_tipo())

    def estado(self, faixa: Faixa | None = None) -> str:
        """Sem base local não sai número. Com base parcial, sai rotulado.

        A porta é de cobertura **do que falta**, não de quantos ciclos já
        rodaram: um ciclo de 3.000 `.txt` não ensina nada sobre os 40 PDFs que
        sobraram. Por isso uma pasta com formato nunca visto derruba o estado
        mesmo com meses de histórico.
        """
        if self.calibracao.maquina.n_obs <= 0:
            return CEGO
        if self.mapa.n_restante <= 0:
            return CALIBRADO
        faixa = self.restante() if faixa is None else faixa
        if self.cobertura < COBERTURA_MINIMA:
            return CALIBRANDO
        if faixa.largura_relativa > LARGURA_MAXIMA:
            return CALIBRANDO
        return CALIBRADO

    # -- fração

    @property
    def fracao(self) -> float:
        """Ponderada por trabalho previsto, não por contagem — modo de errar 2.

        E **derivada do mapa**, não acumulada, pela mesma razão que o restante:
        acumular `previsto_feito` contra um `previsto_total` congelado no prior
        faz os dois divergirem conforme a calibragem aprende, e a barra param em
        97,98% no fim de uma passada completa — foi o que
        `test_indexacao_publica_progresso_e_encerra` pegou. Numerador e
        denominador saem do **mesmo** modelo na mesma passada, e por construção
        fecham em 1,0 quando não resta nada.

        O acumulador segue como reserva para a pré-passada, que roda antes da
        primeira derivação e ainda precisa mover a barra enquanto pula milhares
        de arquivos já indexados.
        """
        feito = self._prever_mapa(self.mapa.feito)
        resta = self._prever_mapa(self.mapa.restante)
        if feito + resta > 0 and (self.mapa.feito or self.mapa.n_restante == 0):
            return min(1.0, max(0.0, feito / (feito + resta)))
        if self._previsto_total > 0:
            return min(1.0, max(0.0, self._previsto_feito / self._previsto_total))
        if self.documentos_totais:
            return min(1.0, self.documentos_feitos / self.documentos_totais)
        return 0.0

    # -- ciclo de vida da previsão (autoteste de calibragem)

    def abrir_previsao(self) -> None:
        faixa = self.restante()
        if faixa.p50 > 0:
            self._previsao = self.calibracao.registrar_previsao(faixa.p50, faixa.p90)

    def fechar_previsao(self, ativo_real: float) -> None:
        self.calibracao.fechar_previsao(self._previsao, ativo_real)
        self._previsao = None

    # -- serialização

    def restaurar(self, dados: dict) -> None:
        """Não restaura coeficiente.

        A v1 trazia `previsto/medido` da execução anterior e com isso trazia a
        contaminação por suspensão para sempre (defeito 8). A calibragem agora
        vive em `calibracao.db`, alimentada só por observação de relógio limpo,
        e é carregada de lá. Este método existe para não quebrar
        `progresso.json` antigo.
        """
        return None

    def como_json(self) -> dict:
        m = self.calibracao.maquina
        faixa = self.restante()
        return {
            "estado": self.estado(faixa),
            "cobertura": round(self.cobertura, 3),
            "descartadas": self._descartadas,
            "previsto_total": round(self._previsto_total, 3),
            "previsto_feito": round(self._previsto_feito, 3),
            "medido_feito": round(self._medido_feito, 3),
            "maquina": {
                "fingerprint": m.fingerprint,
                "a_io": round(m.a_io, 5),
                "a_ch": round(m.a_ch, 6),
                "c0": round(m.c0, 6),
                "c1": round(m.c1, 7),
                "g": round(m.g(self.perfil), 4),
                "n_obs": m.n_obs,
                "perfil": self.perfil,
            },
        }


# ---------------------------------------------------------------------------


def humano(segundos: float) -> str:
    """`4 h 20 min`, `35 min`, `um instante` — nunca `15600 s`."""
    if segundos < 60:
        return "um instante"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h" + (f" {resto} min" if resto else "")
    dias, horas = divmod(horas, 24)
    return f"{dias} d" + (f" {horas} h" if horas else "")


def faixa_humana(faixa: Faixa, estado: str = CALIBRADO) -> str:
    """Texto da faixa. No estado `cego` **não sai tempo** — sai o que é
    verdade: que a máquina ainda está sendo medida."""
    if estado == CEGO:
        return "medindo esta máquina"
    if faixa.vazia:
        return "terminando"
    baixo, alto = humano(faixa.p50), humano(faixa.p90)
    texto = baixo if baixo == alto else f"entre {baixo} e {alto}"
    return f"{texto} (calibrando)" if estado == CALIBRANDO else texto


def decompor(estimador: Estimador, faixa: Faixa) -> str:
    """`3.100 arquivos pequenos (~6 min) + 3 planilhas grandes (~35 min)`.

    A cauda domina o restante, e o usuário pode agir sobre ela — excluir uma
    planilha de 269 KB que vira 345 chunks muda a conta. Esconder isso atrás de
    um número único é esconder a única alavanca que existe.
    """
    maiores = estimador.mapa.maiores
    if not maiores or estimador.mapa.n_restante <= len(maiores):
        return ""
    pesado = sum(
        estimador.calibracao.prever(i.tipo, i.mb, estimador.perfil) for i in maiores
    )
    if pesado <= 0.25 * faixa.p50:
        return ""
    leve = max(0.0, faixa.p50 - pesado)
    n_leves = estimador.mapa.n_restante - len(maiores)
    return (
        f"{n_leves} arquivos ({humano(leve)}) + "
        f"{len(maiores)} grandes ({humano(pesado)})"
    )


