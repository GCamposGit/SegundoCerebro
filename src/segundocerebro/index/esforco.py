"""Nível de esforço da indexação — o que faz `leve` significar algo.

Justificativa medida, não suposta: o run completo de 13 a 16/08/2026 teve **11 h
de parada em 46 h**, porque a alternativa a parar era o notebook ficar
inutilizável. Um indexador que não sabe ficar em segundo plano é um indexador que
o usuário desliga — e aí ele não indexa nada.

Três níveis, no `[maquina] perfil` da configuração. Eles governam prioridade,
afinidade de CPU, quais GPUs recebem trabalho e com que fração — **e nada mais**.
Nenhum nível muda o conteúdo do índice: hardware muda velocidade, nunca conteúdo
(`ARCHITECTURE.md` §4).

A fração é do hardware **desta** máquina, descoberta agora. Um notebook com uma
4070 e um desktop com duas 980 Ti usam o mesmo perfil e recebem planos diferentes.

`gpu` **não** é nível de esforço: é backend, e mora no campo `provider`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import FRACAO_CPU, PERFIS, normalizar_perfil, nucleos_para
from ..logger import get_logger

log = get_logger("index.esforco")

PERFIS_DE_ESFORCO = PERFIS

NOME_PEDIDO = "esforco.txt"
"""Pedido ao vivo, ao lado do índice — o mesmo contrato de `comando.txt`.

Gravar aqui não mata o processo. O indexador lê entre lotes e entre documentos,
aplica o que dá para aplicar agora (prioridade, afinidade, ritmo das GPUs) e
deixa o documento em voo terminar."""


@dataclass(frozen=True)
class GpuInfo:
    indice: str
    nome: str
    display: bool = False


@dataclass(frozen=True)
class GpuPlano:
    indice: str
    nome: str
    display: bool
    ativo: bool
    percentual: int
    """0–100. 0 = esta placa não recebe trabalho neste perfil."""

    @property
    def duty(self) -> float:
        return max(0.0, min(1.0, self.percentual / 100.0))


@dataclass(frozen=True)
class Plano:
    """O que este perfil faz **nesta** máquina, agora."""

    perfil: str
    cpu_total: int
    cpu_nucleos: int
    cpu_percentual: int
    parse_workers: int
    gpus: tuple[GpuPlano, ...] = ()

    def duty_da(self, indice: str) -> float:
        for g in self.gpus:
            if g.indice == indice:
                return g.duty if g.ativo else 0.0
        return 1.0 if not self.gpus else 0.0

    @property
    def duty_padrao(self) -> float:
        """Ritmo do embed na thread principal (uma GPU ou só CPU)."""
        ativas = [g for g in self.gpus if g.ativo]
        if not ativas:
            return 1.0 if self.perfil == "maximo" else FRACAO_CPU.get(self.perfil, 0.5)
        return ativas[0].duty

    @property
    def gpu_ids_ativos(self) -> list[str]:
        return [g.indice for g in self.gpus if g.ativo and g.percentual > 0]

    def como_json(self) -> dict[str, Any]:
        return {
            "perfil": self.perfil,
            "cpu": {
                "ativo": True,
                "percentual": self.cpu_percentual,
                "nucleos": self.cpu_nucleos,
                "nucleos_total": self.cpu_total,
            },
            "gpus": [
                {
                    "id": g.indice,
                    "nome": g.nome,
                    "display": g.display,
                    "ativo": g.ativo,
                    "percentual": g.percentual,
                }
                for g in self.gpus
            ],
        }


def listar_gpus() -> list[GpuInfo]:
    """Placas NVIDIA visíveis agora. Vazio = CPU, e isso é um plano válido."""
    from .gpu_pool import _linhas_smi

    linhas = _linhas_smi("index,name,display_active")
    if not linhas:
        return []
    saida: list[GpuInfo] = []
    for linha in linhas:
        partes = [p.strip() for p in linha.split(",")]
        if not partes:
            continue
        idx = partes[0]
        nome = partes[1] if len(partes) > 1 else f"GPU {idx}"
        display = False
        if len(partes) > 2:
            display = partes[2].lower() in {"enabled", "enable"}
        saida.append(GpuInfo(indice=idx, nome=nome, display=display))
    return saida


def _percentual_gpu(perfil: str, gpu: GpuInfo, todas: list[GpuInfo]) -> int:
    """Quanto desta placa o perfil pode usar. 0 = fica de fora.

    Regras, na ordem, para caber em 1×4070, 2×980 Ti e o que vier:

    1. Máximo: 100% em todas.
    2. Leve, 2+ placas: a do monitor (ou a 0, se o smi não disser) fica de fora.
       As outras a 50%. TDR no desktop GPU é preocupação de `leve`.
    3. Leve, 1 placa: 40%. É o caso do notebook; pular a única GPU deixaria
       a máquina sem acelerador.
    4. Normal, 2+ placas: GPU 0 / monitor a 40%; as outras a 75%.
    5. Normal, 1 placa: 60%. A GPU 0 não vai a 100%.
    """
    perfil = normalizar_perfil(perfil)
    n = len(todas)
    display = gpu.display or gpu.indice == "0"
    if perfil == "maximo":
        return 100
    if perfil == "leve":
        if n >= 2 and display:
            return 0
        return 40 if n == 1 else 50
    # normal
    if n == 1:
        return 60
    return 40 if display else 75


def planar(perfil: str, *, nucleos: int | None = None, gpus: list[GpuInfo] | None = None) -> Plano:
    """Descobre o hardware se não vier dado — testes passam a lista."""
    perfil = normalizar_perfil(perfil)
    if perfil == "automatico":
        perfil = "normal"
    total = nucleos if nucleos is not None else (os.cpu_count() or 4)
    total = max(1, int(total))
    usados = nucleos_para(perfil, total)
    pct_cpu = 100 if perfil == "maximo" else int(round(FRACAO_CPU.get(perfil, 0.5) * 100))
    if gpus is None:
        # F6-C: listing GPUs is not using them. Without an explicit cuda
        # request the plan is CPU, even if nvidia-smi can see cards.
        cuda = os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda"
        gpus = listar_gpus() if cuda else []
    gpu_planos = tuple(
        GpuPlano(
            indice=g.indice,
            nome=g.nome,
            display=g.display,
            percentual=pct,
            ativo=pct > 0,
        )
        for g in gpus
        for pct in (_percentual_gpu(perfil, g, gpus),)
    )
    cuda = os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda"
    if cuda:
        parse = max(1, min(8, usados))
    else:
        parse = 1
    return Plano(
        perfil=perfil,
        cpu_total=total,
        cpu_nucleos=usados,
        cpu_percentual=pct_cpu,
        parse_workers=parse,
        gpus=gpu_planos,
    )


def _afinidade(n_usados: int, n_total: int | None = None) -> list[int]:
    total = n_total if n_total is not None else (os.cpu_count() or 4)
    total = max(1, int(total))
    n_usados = max(1, min(int(n_usados), total))
    return list(range(n_usados))


def aplicar(perfil: str, *, pids: list[int] | None = None, nucleos: int | None = None) -> dict[str, object]:
    """Ajusta prioridade e afinidade deste processo (e filhos, se vierem).

    Nunca levanta: `psutil` pode faltar, o sistema pode recusar, e nenhuma das
    duas coisas é motivo para não indexar. O relatório de volta existe para a
    tela poder dizer "pedi leve e o sistema não deixou" em vez de mentir.
    """
    pedido = normalizar_perfil(perfil)
    perfil = "normal" if pedido == "automatico" else pedido
    plano = planar(perfil, nucleos=nucleos)
    feito: dict[str, object] = {
        "perfil": pedido,
        "prioridade": None,
        "e_s": None,
        "afinidade": None,
        "cpu_percentual": plano.cpu_percentual,
        "cpu_nucleos": plano.cpu_nucleos,
        "recursos": plano.como_json(),
    }

    try:
        import psutil
    except ModuleNotFoundError:
        log.warning("psutil ausente: perfil '%s' não pôde ser aplicado", perfil)
        feito["aviso"] = "psutil ausente"
        return feito

    alvos = [psutil.Process()]
    for pid in pids or []:
        try:
            alvos.append(psutil.Process(pid))
        except Exception:  # noqa: BLE001
            continue

    # `leve` fica abaixo do normal, não em `IDLE`: em idle o indexador só anda
    # quando a máquina está completamente ociosa, e um run de 39 h nunca
    # terminaria num computador em uso. Abaixo do normal cede a vez ao que está
    # em primeiro plano e continua progredindo.
    alvo_nice = {
        "leve": getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10),
        "maximo": getattr(psutil, "HIGH_PRIORITY_CLASS", -10),
    }.get(perfil)
    if alvo_nice is not None:
        try:
            for proc in alvos:
                proc.nice(alvo_nice)
            feito["prioridade"] = perfil
        except Exception as erro:  # noqa: BLE001
            log.warning("não consegui mudar a prioridade: %s", erro)
            feito["aviso"] = str(erro)

    if perfil == "leve":
        try:
            alvos[0].ionice(getattr(psutil, "IOPRIO_LOW", 1))
            feito["e_s"] = "baixa"
        except Exception as erro:  # noqa: BLE001
            log.debug("prioridade de E/S indisponível: %s", erro)

    cores = _afinidade(plano.cpu_nucleos, plano.cpu_total)
    try:
        for proc in alvos:
            if hasattr(proc, "cpu_affinity"):
                proc.cpu_affinity(cores)
        feito["afinidade"] = cores
    except Exception as erro:  # noqa: BLE001
        log.debug("afinidade de CPU indisponível: %s", erro)
        if "aviso" not in feito:
            feito["aviso"] = str(erro)

    log.info("perfil de esforço '%s' aplicado: %s", pedido, {k: feito[k] for k in ("prioridade", "e_s", "cpu_nucleos")})
    return feito


def na_bateria() -> bool | None:
    """`True` se a máquina está sem tomada. `None` quando não se sabe.

    O perfil `leve` pausa na bateria: indexar 39 h queima a carga e esquenta o
    notebook, e quem escolheu "leve" escolheu não sentir a indexação.
    """
    try:
        import psutil

        energia = psutil.sensors_battery()
    except Exception:  # noqa: BLE001
        return None
    if energia is None:
        return None
    return not energia.power_plugged


def caminho_pedido(indice: Path) -> Path:
    return Path(indice) / NOME_PEDIDO


def ler_pedido(indice: Path) -> str | None:
    """Perfil pedido ao vivo, ou `None` se não há pedido."""
    alvo = caminho_pedido(indice)
    if not alvo.exists():
        return None
    try:
        texto = alvo.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    perfil = normalizar_perfil(texto)
    return perfil if perfil in PERFIS_DE_ESFORCO or perfil == "automatico" else None


def pedir(indice: Path, perfil: str) -> None:
    perfil = normalizar_perfil(perfil)
    if perfil not in PERFIS_DE_ESFORCO and perfil != "automatico":
        raise ValueError(f"perfil desconhecido: {perfil}")
    alvo = caminho_pedido(indice)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_suffix(".txt.tmp")
    tmp.write_text(perfil + "\n", encoding="utf-8")
    tmp.replace(alvo)
    log.info("pedido de esforço '%s' em %s", perfil, alvo)


def limpar_pedido(indice: Path) -> None:
    caminho_pedido(indice).unlink(missing_ok=True)


def dormir_ritmo(trabalho: float, duty: float, *, passo: float = 0.4) -> None:
    """Pausa para que trabalho / (trabalho+pausa) ≈ duty. Cancelável a cada `passo`."""
    if duty >= 0.999 or trabalho <= 0:
        return
    duty = max(0.05, min(duty, 1.0))
    restante = trabalho * (1.0 / duty - 1.0)
    fim = time.monotonic() + restante
    while True:
        falta = fim - time.monotonic()
        if falta <= 0:
            return
        time.sleep(min(falta, passo))


@dataclass
class ControleEsforco:
    """Perfil vivo: o painel grava o arquivo, o indexador aplica entre lotes."""

    indice: Path
    perfil: str
    plano: Plano = field(init=False)
    relato: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.perfil = normalizar_perfil(self.perfil)
        self.plano = planar(self.perfil)
        self.relato = aplicar(self.perfil)

    def atualizar(self, *, pids: list[int] | None = None) -> bool:
        """Relê o pedido. Devolve True se o plano mudou."""
        pedido = ler_pedido(self.indice)
        if not pedido or pedido == self.perfil:
            return False
        log.info("esforço ao vivo: %s → %s", self.perfil, pedido)
        self.perfil = pedido
        self.plano = planar(pedido)
        self.relato = aplicar(pedido, pids=pids)
        return True

    def como_json(self) -> dict[str, object]:
        extra = dict(self.relato)
        extra["recursos"] = self.plano.como_json()
        extra["perfil"] = self.perfil
        return extra
