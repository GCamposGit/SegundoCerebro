"""Quanto tempo falta — e os quatro jeitos de errar isso.

Método e coeficientes medidos em `docs/estimativa-de-indexacao.md`, sobre o run
completo de 13 a 16/08/2026: 1.601 documentos, 92.137 chunks, 64 h de parede.

Os quatro erros que este módulo existe para não cometer, **três deles cometidos
por mim durante a F1**:

1. **Denominador errado.** O censo conta 3.154 arquivos; o indexador processa
   1.601. Usar a contagem bruta reporta 45% quando o real é 91%. Por isso o total
   é *declarado* por quem enumera — o mesmo `iter_files` do indexador — e nunca
   contado aqui de novo.
2. **Contar documentos como se custassem o mesmo.** Mediana de 12 chunks por
   documento, média de 67,8, máximo de 7.017: quase 600× entre a mediana e o pior
   caso. Barra por contagem anda em solavancos.
3. **Tempo de parede.** 64 h de relógio contra ~39 h de trabalho: 40% foi
   suspensão e pausa. Daí `Relogio`, que conta só tempo ativo.
4. **Extrapolação linear ingênua.** `decorrido ÷ feito × restante` supõe itens
   intercambiáveis. A ordem da varredura é alfabética por pasta e as pastas não
   têm composição parecida.

A unidade de trabalho é **byte ponderado por formato**, porque é o único preditor
disponível *antes* de abrir o arquivo — e abrir para estimar custaria o mesmo que
indexar.
"""

from __future__ import annotations

import time
from bisect import insort
from dataclasses import dataclass, field
from pathlib import Path

SEGUNDOS_POR_MB: dict[str, float] = {
    "pptx": 3.8,
    "pdf": 48.7,
    "xlsx": 487.2,
    "docx": 522.5,
}
"""Medianas medidas sobre 1.419 documentos com duração observada.

Um megabyte de PPTX é quase todo imagem e vira 8 chunks; um de DOCX é texto puro
e vira centenas. Daí os 137× entre o menor e o maior coeficiente.

São **semente**, não verdade: valem para esta máquina, este corpus e o
`e5-large`. Trocar qualquer um dos três invalida a tabela, e é por isso que o
estimador recalibra sozinho durante o run."""

SEGUNDOS_POR_MB_PADRAO = 50.0
"""Para extensão sem coeficiente medido. Perto do PDF, que é metade do acervo."""

MEIA_VIDA = 20
"""Documentos até um coeficiente novo valer metade do peso total.

Média móvel exponencial: a tabela governa os primeiros minutos e o run governa o
resto. Alto demais e a semente demora a sair de cena; baixo demais e um único
arquivo atípico desestabiliza a estimativa."""

LIMIAR_DE_SUSPENSAO = 120.0
"""Salto de relógio acima disto é máquina dormindo, não documento lento.

Nenhum documento do acervo levou dois minutos entre registros consecutivos, e a
maior planilha adiada nem chegou a ser aberta. Um salto maior que isso é
hibernação, tampa fechada ou processo suspenso — e contá-lo como trabalho
derruba a vazão estimada pela metade."""


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

    def tique(self, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        if self._ultimo is not None:
            passou = agora - self._ultimo
            if passou > LIMIAR_DE_SUSPENSAO:
                self.suspensoes += 1
                self.parado += passou
            else:
                self._ativo += max(passou, 0.0)
        self._ultimo = agora

    @property
    def ativo(self) -> float:
        return self._ativo


def peso_de(rel: str, tamanho: int) -> float:
    """Trabalho estimado de um arquivo, em segundos."""
    extensao = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    return SEGUNDOS_POR_MB.get(extensao, SEGUNDOS_POR_MB_PADRAO) * (tamanho / 1e6)


@dataclass(frozen=True)
class Faixa:
    """Estimativa como faixa, nunca como ponto.

    A dispersão por documento é enorme — coeficiente de variação 4,6 — e a cauda
    é pesada: um arquivo de 7.017 chunks pesa mais que centenas de DOCX. A soma
    de mil e seiscentos é confiável; um documento isolado não é. Exibir ponto
    seria apresentar ruído como informação.
    """

    p50: float
    p90: float

    @property
    def vazia(self) -> bool:
        return self.p50 <= 0


@dataclass
class Estimador:
    """Trabalho declarado por quem enumera, e recalibrado por quem executa."""

    total: float = 0.0
    feito: float = 0.0
    documentos_totais: int = 0
    documentos_feitos: int = 0
    _fatores: list[float] = field(default_factory=list)
    _fator: float = 1.0
    """Razão medido ÷ previsto, por média móvel. 1,0 = a semente está certa."""

    def declarar(self, arquivos) -> None:  # noqa: ANN001 — iterável de (rel, tamanho)
        """O total vem de fora, do mesmo enumerador que o indexador usa.

        Contar aqui de novo é como o denominador errado nasce.
        """
        for rel, tamanho in arquivos:
            self.total += peso_de(rel, tamanho)
            self.documentos_totais += 1

    def pular(self, rel: str, tamanho: int) -> None:
        """Documento já indexado: some do restante sem entrar na calibragem."""
        self.feito += peso_de(rel, tamanho)
        self.documentos_feitos += 1

    def registrar(self, rel: str, tamanho: int, segundos: float) -> None:
        """Documento processado: conta como feito e corrige a semente."""
        previsto = peso_de(rel, tamanho)
        self.feito += previsto
        self.documentos_feitos += 1
        if previsto > 0 and segundos > 0:
            razao = segundos / previsto
            peso = 2.0 / (MEIA_VIDA + 1)
            self._fator = self._fator + peso * (razao - self._fator)
            insort(self._fatores, razao)

    @property
    def fracao(self) -> float:
        return min(self.feito / self.total, 1.0) if self.total else 0.0

    def restante(self) -> Faixa:
        """Segundos ativos que faltam, como faixa.

        `p90` sai do percentil observado da razão medido÷previsto, não de um
        multiplicador inventado: se este acervo se comporta pior que a semente, a
        própria dispersão dele diz quanto.
        """
        falta = max(self.total - self.feito, 0.0)
        if falta <= 0:
            return Faixa(0.0, 0.0)
        p50 = falta * self._fator
        if len(self._fatores) < 5:
            # Amostra curta: a faixa é larga porque a ignorância é real.
            return Faixa(p50, p50 * 2.0)
        alto = self._fatores[min(int(len(self._fatores) * 0.9), len(self._fatores) - 1)]
        return Faixa(p50, falta * max(alto, self._fator))


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


def faixa_humana(faixa: Faixa) -> str:
    if faixa.vazia:
        return "terminando"
    baixo, alto = humano(faixa.p50), humano(faixa.p90)
    return baixo if baixo == alto else f"entre {baixo} e {alto}"


def tamanho_de(caminho: Path) -> int:
    """Bytes, sem abrir o arquivo — metadado, nunca conteúdo.

    Abrir um placeholder do SharePoint dispararia download; `stat` não.
    """
    try:
        return caminho.stat().st_size
    except OSError:
        return 0
