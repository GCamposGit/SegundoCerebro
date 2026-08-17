"""Nível de esforço da indexação — o que faz `leve` significar algo.

Justificativa medida, não suposta: o run completo de 13 a 16/08/2026 teve **11 h
de parada em 46 h**, porque a alternativa a parar era o notebook ficar
inutilizável. Um indexador que não sabe ficar em segundo plano é um indexador que
o usuário desliga — e aí ele não indexa nada.

Três níveis, no `[maquina] perfil` da configuração. Eles governam prioridade de
processo, prioridade de E/S e número de threads — **e nada mais**. Nenhum nível
muda o conteúdo do índice: hardware muda velocidade, nunca conteúdo
(`ARCHITECTURE.md` §4). É a mesma regra que mantém o índice portátil entre
máquinas.

`gpu` **não** é nível de esforço, e por isso não está aqui: é backend, e mora no
campo `provider`. Eram eixos misturados até 16/08/2026.
"""

from __future__ import annotations

from ..logger import get_logger

log = get_logger("index.esforco")

PERFIS_DE_ESFORCO = ("leve", "normal", "maximo")


def aplicar(perfil: str) -> dict[str, object]:
    """Ajusta prioridade deste processo. Devolve o que conseguiu fazer.

    Nunca levanta: `psutil` pode faltar, o sistema pode recusar a mudança, e
    nenhuma das duas coisas é motivo para não indexar. O relatório de volta existe
    para a tela poder dizer "pedi leve e o sistema não deixou" em vez de mentir
    que está leve.
    """
    feito: dict[str, object] = {"perfil": perfil, "prioridade": None, "e_s": None}
    if perfil == "normal":
        return feito

    try:
        import psutil
    except ModuleNotFoundError:
        log.warning("psutil ausente: perfil '%s' não pôde ser aplicado", perfil)
        feito["aviso"] = "psutil ausente"
        return feito

    processo = psutil.Process()

    # `leve` fica abaixo do normal, não em `IDLE`: em idle o indexador só anda
    # quando a máquina está completamente ociosa, e um run de 39 h nunca
    # terminaria num computador em uso. Abaixo do normal cede a vez ao que está
    # em primeiro plano e continua progredindo.
    alvo = {
        "leve": getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10),
        "maximo": getattr(psutil, "HIGH_PRIORITY_CLASS", -10),
    }.get(perfil)
    if alvo is not None:
        try:
            processo.nice(alvo)
            feito["prioridade"] = perfil
        except Exception as erro:  # noqa: BLE001
            log.warning("não consegui mudar a prioridade: %s", erro)
            feito["aviso"] = str(erro)

    # E/S baixa importa mais que CPU aqui: o gargalo percebido por quem está
    # usando a máquina é o disco, não o processador.
    if perfil == "leve":
        try:
            processo.ionice(getattr(psutil, "IOPRIO_LOW", 1))
            feito["e_s"] = "baixa"
        except Exception as erro:  # noqa: BLE001
            log.debug("prioridade de E/S indisponível: %s", erro)

    log.info("perfil de esforço '%s' aplicado: %s", perfil, feito)
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
