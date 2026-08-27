"""Publicação do progresso da indexação, para quem quiser olhar.

**A arquitetura é a parte que não pode sair errada:** o indexador é um processo
independente que *publica*; o painel apenas *lê*. Fechar o painel não para a
indexação, e a linha de comando continua fazendo tudo sozinha. O painel é cliente
do mecanismo, não dono — mesma razão da invariante 6.

Publicação por arquivo, e não por IPC: um JSON gravado atomicamente ao lado do
índice. Sem porta, sem socket, sem protocolo a versionar. O registro SQLite
continua sendo a verdade de fundo; este arquivo é conveniência de leitura, e
perdê-lo não perde nada.

Gravação atômica com `.tmp` + `replace` porque a barra lê a qualquer momento: um
JSON truncado no meio faria a tela mostrar erro justamente durante o trabalho
longo que ela existe para acompanhar.

**Quem publica não pode ser quem trabalha.** Medido em 26/08/2026: o indexador
entrou num único `session.run` do ONNX com um lote de 32 trechos de janela cheia
e ficou lá dentro; a thread principal não voltou, `publicar()` não foi chamado, e
o arquivo congelou dizendo `"status": "indexando"` com ETA de 9 h enquanto o
processo não avançava um documento por 3 h 22 min. Um indexador parado não pode
reportar que está indexando — e não pode depender da thread travada para dizer
isso. Daí o `vigia`: uma thread daemon que republica sozinha e, se nada avança
por `LIMITE_SEM_AVANCO`, troca o status para `travada` e grita no log. É o
mesmo princípio do resto do módulo — o mecanismo não depende de ninguém lembrar
de chamá-lo.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logger import get_logger
from .estimativa import CEGO, Estimador, Relogio, decompor, faixa_humana

log = get_logger("index.progresso")

NOME = "progresso.json"
INTERVALO_PADRAO = 2.0
"""Segundos entre publicações.

Documento rápido dura menos que isto, e gravar a cada um transformaria a barra em
carga de E/S concorrendo com a indexação. Dois segundos é abaixo do que o olho
percebe como travado e acima do que custa."""

INTERVALO_VIGIA = 30.0
"""Segundos entre batidas do vigia.

Acima do intervalo normal de propósito: o vigia existe para o caso em que a
thread principal **não volta**, e nesse caso a única coisa que precisa ser fresca
é o carimbo de tempo."""

TENTATIVAS_DE_GRAVACAO = 3
ESPERA_DE_GRAVACAO = 0.03
"""Retentativa curta da troca atômica. Ver `_gravar`."""

LIMITE_SEM_AVANCO = 600.0
"""Segundos de tempo de parede sem nenhum avanço antes de chamar de `travada`.

Dez minutos porque documento legítimo pode demorar: um PDF de 800 trechos com
e5-large na CPU passa de meia hora, e nele o avanço aparece por trecho, não por
documento. O que não é legítimo é *nada* mudar — nem documento, nem trecho, nem
arquivo em voo. Medido em 26/08/2026 no caso que motivou isto: o lote de 32
trechos de janela cheia passou de 4 min dentro de uma única chamada do ONNX,
sem publicar nada, e o congelamento real durou 3 h 22 min."""


def caminho_de(indice: Path) -> Path:
    return Path(indice) / NOME


def ler(indice: Path) -> dict[str, Any] | None:
    """O que o painel chama. `None` quando não há indexação publicada."""
    alvo = caminho_de(indice)
    if not alvo.exists():
        return None
    try:
        return json.loads(alvo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Publicação atômica torna isto improvável, não impossível — disco cheio,
        # antivírus segurando o arquivo. Ausência de dado não é erro de leitura.
        return None


@dataclass
class Publicador:
    """Escreve o estado da indexação a cada `intervalo`, no máximo."""

    indice: Path
    estimador: Estimador
    relogio: Relogio = field(default_factory=Relogio)
    intervalo: float = INTERVALO_PADRAO
    iniciado_em: float = field(default_factory=time.time)
    limite_sem_avanco: float = LIMITE_SEM_AVANCO
    intervalo_vigia: float = INTERVALO_VIGIA
    _ultima: float = 0.0
    _extra: dict[str, Any] = field(default_factory=dict)
    _trava: threading.RLock = field(default_factory=threading.RLock)
    _marco: tuple = ()
    _marco_em: float = field(default_factory=time.monotonic)
    _avisado_em: float = 0.0
    _vigia: threading.Thread | None = None
    _fim: threading.Event = field(default_factory=threading.Event)

    # --- vigia -----------------------------------------------------------

    def _sinais(self) -> tuple:
        """O que precisa mudar para a passada estar viva.

        Documento **e** trecho **e** arquivo em voo: sem o trecho, um PDF de 800
        trechos legítimo cairia como travado; sem o documento, uma fila de
        arquivos de um trecho cada nunca mudaria o trecho."""
        return (
            self.estimador.documentos_feitos,
            self._extra.get("trecho"),
            self._extra.get("arquivo"),
        )

    def sem_avanco(self) -> float:
        """Segundos de tempo de parede desde o último avanço observado."""
        with self._trava:
            sinais = self._sinais()
            if not self._marco or sinais != self._marco:
                self._marco = sinais
                self._marco_em = time.monotonic()
                self._avisado_em = 0.0
                return 0.0
            return max(0.0, time.monotonic() - self._marco_em)

    def iniciar_vigia(self) -> None:
        """Sobe a thread que publica mesmo quando a principal não volta.

        Daemon: o vigia nunca pode segurar o encerramento do processo, e nunca
        pode derrubar a indexação — cada batida é engolida por `except`, porque
        ele lê estruturas que a thread principal está mutando."""
        if self._vigia is not None:
            return
        self._fim.clear()
        self._vigia = threading.Thread(
            target=self._rodar_vigia, name="vigia-progresso", daemon=True
        )
        self._vigia.start()

    def parar_vigia(self) -> None:
        self._fim.set()
        vigia, self._vigia = self._vigia, None
        if vigia is not None:
            vigia.join(timeout=2.0)

    def _rodar_vigia(self) -> None:
        while not self._fim.wait(self.intervalo_vigia):
            try:
                parada = self.sem_avanco()
                if parada < self.limite_sem_avanco:
                    continue
                # Republica com carimbo novo: sem isto a tela não distingue
                # "processo morto" de "processo vivo e parado", e as duas pedem
                # coisas diferentes do dono do acervo.
                self.publicar("travada", forcar=True)
                if parada - self._avisado_em >= self.limite_sem_avanco:
                    self._avisado_em = parada
                    log.warning(
                        "sem avanço há %.0f min — %d documentos feitos, arquivo %s. O processo "
                        "pode estar dentro de uma única chamada de embed (lote grande demais "
                        "para a memória livre) ou preso num arquivo. Confira a CPU do PID %d",
                        parada / 60,
                        self.estimador.documentos_feitos,
                        self._extra.get("arquivo"),
                        os.getpid(),
                    )
            except Exception as erro:  # noqa: BLE001 — vigia não derruba indexação
                log.debug("batida do vigia falhou: %s", erro)

    # --- publicação ------------------------------------------------------

    def anotar(self, **campos: Any) -> None:
        """Campos que a tela mostra e o indexador conhece: base, perfil, arquivo."""
        with self._trava:
            self._extra.update(campos)

    def instantaneo(self, status: str = "indexando") -> dict[str, Any]:
        with self._trava:
            return self._instantaneo(status)

    def _instantaneo(self, status: str = "indexando") -> dict[str, Any]:
        parada = self.sem_avanco()
        if status == "indexando" and parada >= self.limite_sem_avanco:
            # Verdade acima de continuidade: "indexando" com ETA de 9 h enquanto
            # nada anda é a mentira que custou 3 h 22 min sem ninguém perceber.
            status = "travada"
        faixa = self.estimador.restante()
        # O estado sai junto com a faixa, calculado da **mesma** faixa. Pedir o
        # estado depois recalcularia o Monte Carlo e poderia rotular um número
        # que não é o exibido.
        estado = self.estimador.estado(faixa)
        agora = time.time()
        pausada_ha = self.relogio.pausa_atual if status == "pausada" else 0.0
        return {
            "status": status,
            "sem_avanco_segundos": round(parada),
            "pid": os.getpid(),
            "atualizado_em": agora,
            "iniciado_em": self.iniciado_em,
            "documentos": {
                "feitos": self.estimador.documentos_feitos,
                "totais": self.estimador.documentos_totais,
            },
            # Fração por **trabalho**, não por contagem: o custo por documento
            # varia quase 600× entre a mediana e o pior caso, e barra por contagem
            # anda em solavancos.
            "fracao": round(self.estimador.fracao, 4),
            # `cego` não publica tempo: número sem base local é mentira, e o
            # painel precisa poder mostrar o mapa sem inventar previsão.
            "restante_segundos": None if estado == CEGO else round(faixa.p50),
            "restante_p90_segundos": None if estado == CEGO else round(faixa.p90),
            "restante": faixa_humana(faixa, estado),
            "estimativa_estado": estado,
            "cobertura": round(self.estimador.cobertura, 3),
            "decomposicao": decompor(self.estimador, faixa) or None,
            "mapa": self.estimador.mapa.como_json(),
            # Ativo = indexando de fato. Corrido = relógio de parede desde o
            # primeiro start desta passada (sobrevive a reboot).
            "ativo_segundos": round(self.relogio.ativo),
            "corrido_segundos": round(max(0.0, agora - self.iniciado_em)),
            "parado_segundos": round(self.relogio.parado),
            "pausada_ha_segundos": round(pausada_ha),
            "suspensoes": self.relogio.suspensoes,
            "calibracao": self.estimador.como_json(),
            **self._extra,
        }

    def publicar(self, status: str = "indexando", *, forcar: bool = False) -> None:
        with self._trava:
            agora = time.monotonic()
            if not forcar and agora - self._ultima < self.intervalo:
                return
            self._ultima = agora
            self._gravar(self._instantaneo(status))

    def encerrar(self, status: str) -> None:
        """`concluida`, `interrompida` ou `falhou` — nunca simplesmente somir.

        O arquivo **fica**: é o que permite à tela dizer "terminou às 02:46" em
        vez de "não há nada acontecendo", que é indistinguível de nunca ter
        rodado.
        """
        self.parar_vigia()
        with self._trava:
            self._gravar(self._instantaneo(status))

    def _gravar(self, dados: dict[str, Any]) -> None:
        alvo = caminho_de(self.indice)
        temporario = alvo.with_suffix(".json.tmp")
        texto = json.dumps(dados, ensure_ascii=False, indent=1)
        erro: OSError | None = None
        # `replace` recusa com "acesso negado" enquanto **outro** processo tem o
        # arquivo aberto — no Windows a leitura do painel basta. Publicação que
        # falha em silêncio devolve exatamente o sintoma que este módulo existe
        # para eliminar: barra parada com o indexador vivo. Duas tentativas
        # curtas cobrem a leitura do painel, que dura microssegundos.
        for tentativa in range(TENTATIVAS_DE_GRAVACAO):
            try:
                alvo.parent.mkdir(parents=True, exist_ok=True)
                temporario.write_text(texto, encoding="utf-8")
                temporario.replace(alvo)
                return
            except OSError as falha:
                erro = falha
                if tentativa < TENTATIVAS_DE_GRAVACAO - 1:
                    time.sleep(ESPERA_DE_GRAVACAO)
        # Progresso é conveniência. Falhar em publicá-lo não pode derrubar a
        # indexação, que é o trabalho de verdade.
        log.warning("não consegui publicar progresso: %s", erro)
