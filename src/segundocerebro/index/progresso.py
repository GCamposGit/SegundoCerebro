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
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logger import get_logger
from .estimativa import Estimador, Relogio, faixa_humana

log = get_logger("index.progresso")

NOME = "progresso.json"
INTERVALO_PADRAO = 2.0
"""Segundos entre publicações.

Documento rápido dura menos que isto, e gravar a cada um transformaria a barra em
carga de E/S concorrendo com a indexação. Dois segundos é abaixo do que o olho
percebe como travado e acima do que custa."""


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
    _ultima: float = 0.0
    _extra: dict[str, Any] = field(default_factory=dict)

    def anotar(self, **campos: Any) -> None:
        """Campos que a tela mostra e o indexador conhece: base, perfil, arquivo."""
        self._extra.update(campos)

    def instantaneo(self, status: str = "indexando") -> dict[str, Any]:
        faixa = self.estimador.restante()
        agora = time.time()
        pausada_ha = self.relogio.pausa_atual if status == "pausada" else 0.0
        return {
            "status": status,
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
            "restante_segundos": round(faixa.p50),
            "restante_p90_segundos": round(faixa.p90),
            "restante": faixa_humana(faixa),
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
        agora = time.monotonic()
        if not forcar and agora - self._ultima < self.intervalo:
            return
        self._ultima = agora
        self._gravar(self.instantaneo(status))

    def encerrar(self, status: str) -> None:
        """`concluida`, `interrompida` ou `falhou` — nunca simplesmente somir.

        O arquivo **fica**: é o que permite à tela dizer "terminou às 02:46" em
        vez de "não há nada acontecendo", que é indistinguível de nunca ter
        rodado.
        """
        self._gravar(self.instantaneo(status))

    def _gravar(self, dados: dict[str, Any]) -> None:
        alvo = caminho_de(self.indice)
        temporario = alvo.with_suffix(".json.tmp")
        try:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(
                json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            temporario.replace(alvo)
        except OSError as erro:
            # Progresso é conveniência. Falhar em publicá-lo não pode derrubar a
            # indexação, que é o trabalho de verdade.
            log.warning("não consegui publicar progresso: %s", erro)
