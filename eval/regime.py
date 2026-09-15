"""Vazão do encoder por regime de máquina — o instrumento do `F4-R`.

Existe por uma retratação. O achado 16.1 de `docs/spec-estimativa-v2.md` dizia
que a máscara de afinidade do perfil `normal` custa **12×** de vazão. Medindo com
braços intercalados, a mesma máscara custa **zero** num regime de agendamento do
sistema operacional e **8×** noutro, e a mesma máquina entrega 0,141 e 3,19
s/chunk sem nada do produto mudar — 22×. O laudo está em
`docs/afinidade-e-estado-de-maquina.md`.

O defeito de método que produziu a conclusão errada é o que este módulo torna
impossível, e é por isso que ele é a entrega e não o conserto da máscara:

1. **Braços em sequência mentem.** Um bloco do braço A, depois um bloco do braço
   B, produz tabela coerente e causa falsa quando o regime muda entre os blocos —
   e ele muda em minutos. `ordem_intercalada` obriga A/B/A/B.
2. **Uma réplica por braço não é contraste.** `contraste` **recusa** reportar
   razão com menos de duas réplicas por braço, em vez de devolver um número
   plausível.
3. **Número sem regime é mentira**, ao lado de "sem corpus, sem máquina e sem
   data" (`docs/colaboracao.md` §4, regra 7). `estado()` entra em toda observação,
   antes e depois, e `contraste` marca o resultado como suspeito quando o estado
   mudou no meio. Desde o R.1 (02/09/2026, 14700HX) o regime inclui EcoQoS, e
   `--contraste-ecoqos` liga e desliga o estado lento por comando.

Um braço por **processo**: a threadpool da ONNX Runtime e a afinidade são fixadas
na criação da sessão, então medir dois braços no mesmo processo mede o primeiro.

Isto mede **encoder**, não recuperação: não há corpus, não há dourado, e nenhum
número daqui entra em decisão de ranking.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _processador_da_maquina() -> str:
    """Obtém a identidade sem consultar WMI, que pode bloquear no CI Windows."""
    if sys.platform == "win32":
        return (
            os.environ.get("PROCESSOR_IDENTIFIER")
            or os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or "Windows"
        )
    return platform.processor() or platform.machine()

AQUECIMENTO = 3
"""Chunks descartados antes de cronometrar. Mesmo valor de `eval/latencia.py`."""

REPLICAS_MINIMAS = 2
"""Abaixo disto `contraste` recusa. Uma réplica por braço é uma janela, não um braço."""

TEXTO = (
    "O contrato NN-VCE-001 fixa o prazo de entrega do relatorio "
    "trimestral e a revisao do escopo pela VCE."
)
"""Vocabulário VCE, fixo. O braço mede a máquina; o texto não pode variar."""

SONDA_ITERS = 800_000
"""Iterações do laço da sonda. Mesmo valor da passada que isolou o EcoQoS no 14700HX."""


def estado() -> dict[str, object]:
    """Regime da máquina agora — o que faltava em toda medição de vazão daqui.

    `tomada` é `None` em desktop sem bateria, e isso é informação: significa que
    aquele setup não tem o eixo que produziu o 22× no 1355U. `ecoqos` é o
    gatilho isolado no 14700HX: ligar e desligar reproduz o par lento/rápido.
    """
    dados: dict[str, object] = {
        "maquina": platform.node(),
        "processador": _processador_da_maquina(),
        "logicos": os.cpu_count(),
    }
    try:
        from segundocerebro.index.esforco import observar_regime

        dados.update(observar_regime())
    except Exception:  # noqa: BLE001 — probe de hardware: o relato segue sem o regime
        dados.setdefault("tomada", None)
        dados.setdefault("ecoqos", None)
    return dados


def plano_de_bracos(n_logicos: int, n_por_braco: int) -> dict[str, list[int] | None]:
    """Máscaras a comparar, derivadas da topologia — não cravadas em 12 lógicos.

    Os nomes dizem a hipótese, e é de propósito que `altos` exista: num Intel
    híbrido os lógicos altos são os E-cores, e foi comparar `[0..5]` com `[4..11]`
    que mostrou que no regime lento o sistema só agenda E-core — uma máscara com
    **mais** núcleos ficou 5× mais lenta que uma com menos.
    """
    n_logicos = max(1, int(n_logicos))
    n = max(1, min(int(n_por_braco), n_logicos))
    passo = max(1, n_logicos // n)
    return {
        "livre": None,
        "contiguo": list(range(n)),
        "espalhado": [i * passo for i in range(n) if i * passo < n_logicos],
        "altos": list(range(n_logicos - n, n_logicos)),
    }


def ordem_intercalada(bracos: list[str], replicas: int) -> list[str]:
    """A/B/A/B, não AA/BB. O bloco em sequência foi o que produziu a causa falsa."""
    if replicas < 1:
        raise ValueError("replicas precisa ser ao menos 1")
    return [b for _ in range(replicas) for b in bracos]


@dataclass
class Observacao:
    braco: str
    s_chunk: list[float]
    estado_antes: dict[str, object]
    estado_depois: dict[str, object]
    mascara: list[int] = field(default_factory=list)

    @property
    def mediana(self) -> float:
        return statistics.median(self.s_chunk)

    @property
    def regime_mudou(self) -> bool:
        """Tomada ou EcoQoS mudaram no meio do braço — o número é suspeito."""
        a, d = self.estado_antes, self.estado_depois
        return a.get("tomada") != d.get("tomada") or a.get("ecoqos") != d.get("ecoqos")


def _ecoqos_nao_aplicou(observacoes: list[Observacao]) -> list[str]:
    """HANDLE truncado, API recusada: o comando rodou e o estado não mudou."""
    esperado = {"contiguo_on": True, "contiguo_off": False}
    return [
        o.braco
        for o in observacoes
        if o.braco in esperado and o.estado_antes.get("ecoqos") is not esperado[o.braco]
    ]


def contraste(observacoes: list[Observacao]) -> dict[str, object]:
    """Medianas por braço e a razão contra `livre` — ou a recusa, com o motivo.

    Recusa em vez de devolver número plausível: é a mesma escolha de
    `eval.comparar`, e é o que faltava quando o 16.1 concluiu de um bloco por
    braço.
    """
    por_braco: dict[str, list[Observacao]] = {}
    for o in observacoes:
        por_braco.setdefault(o.braco, []).append(o)

    magros = {b: len(v) for b, v in por_braco.items() if len(v) < REPLICAS_MINIMAS}
    if magros:
        return {
            "veredito": "recusado",
            "motivo": (
                f"réplicas por braço abaixo de {REPLICAS_MINIMAS}: {magros}. "
                "Uma réplica mede a janela, não o braço — o regime muda em minutos."
            ),
        }
    falhou = _ecoqos_nao_aplicou(observacoes)
    if falhou:
        return {
            "veredito": "recusado",
            "motivo": (
                f"EcoQoS não aplicado em: {falhou}. "
                "Número sem o gatilho ligado é a janela outra vez."
            ),
        }

    resumo = {
        b: {
            "medianas": [round(o.mediana, 4) for o in v],
            "mediana_das_replicas": round(statistics.median([o.mediana for o in v]), 4),
            "regime_mudou": any(o.regime_mudou for o in v),
            "ecoqos": [o.estado_antes.get("ecoqos") for o in v],
        }
        for b, v in por_braco.items()
    }
    base = resumo.get("livre", {}).get("mediana_das_replicas")
    if base:
        for b, d in resumo.items():
            d["razao_contra_livre"] = round(d["mediana_das_replicas"] / base, 2)
    off = resumo.get("contiguo_off", {}).get("mediana_das_replicas")
    on = resumo.get("contiguo_on", {}).get("mediana_das_replicas")
    if off and on:
        resumo["contiguo_on"]["razao_contra_off"] = round(on / off, 2)

    suspeito = [b for b, d in resumo.items() if d["regime_mudou"]]
    return {
        "veredito": "medido" if not suspeito else "medido_com_ressalva",
        "ressalva": (
            None
            if not suspeito
            else f"estado de regime mudou durante: {suspeito}. Refazer com o estado fixo."
        ),
        "bracos": resumo,
    }


# ---------------------------------------------------------------------------
# Execução de um braço: processo próprio, sempre.
# ---------------------------------------------------------------------------


def _preparar_braco(mascara: list[int] | None, ecoqos: bool | None) -> list[int]:
    """Aplica EcoQoS e afinidade **antes** de cronometrar. Nunca levanta."""
    if ecoqos is not None:
        from segundocerebro.index.regime_maquina import aplicar_ecoqos

        aplicar_ecoqos(ecoqos)
    efetiva: list[int] = []
    try:
        import psutil

        proc = psutil.Process()
        if mascara is not None:
            proc.cpu_affinity(mascara)
        efetiva = list(proc.cpu_affinity())
    except Exception:  # noqa: BLE001 — sonda de máscara não aborta a medição
        # Vazia no relato = afinidade não aplicada, em vez de fingir que foi.
        pass
    return efetiva


def _tempos_sonda(chunks: int) -> list[float]:
    """Laço de CPU sem encoder: isola o gatilho sem baixar 2 GB de modelo."""
    import math
    import time

    def volta() -> float:
        t = time.perf_counter()
        acc = 0.0
        for i in range(SONDA_ITERS):
            acc += math.sin(i)
        _ = acc
        return time.perf_counter() - t

    volta()
    return [volta() for _ in range(chunks)]


def _tempos_encoder(chunks: int, threads: int) -> list[float]:
    import time

    from segundocerebro.index.embeddings import Embedder

    emb = Embedder("e5-large", threads=threads, lazy=False)
    for _ in range(AQUECIMENTO):
        emb.embed_passagens([TEXTO], batch_size=1, ritmo=1.0)
    tempos: list[float] = []
    for _ in range(chunks):
        t = time.perf_counter()
        emb.embed_passagens([TEXTO], batch_size=1, ritmo=1.0)
        tempos.append(time.perf_counter() - t)
    return tempos


def medir_neste_processo(
    mascara: list[int] | None,
    chunks: int,
    threads: int,
    *,
    ecoqos: bool | None = None,
    sonda: bool = False,
) -> Observacao:
    """Um braço, neste processo. Chamado pelo subprocesso — não chamar em laço.

    A máscara e o EcoQoS entram **antes** do trabalho. A sessão do ORT fixa a
    threadpool na criação; a sonda não carrega o encoder.
    """
    efetiva = _preparar_braco(mascara, ecoqos)
    antes = estado()
    tempos = _tempos_sonda(chunks) if sonda else _tempos_encoder(chunks, threads)
    return Observacao(
        braco="",
        s_chunk=tempos,
        estado_antes=antes,
        estado_depois=estado(),
        mascara=efetiva,
    )


def plano_ecoqos(n_logicos: int, n_por_braco: int) -> tuple[dict[str, list[int]], dict[str, bool]]:
    """Mesma máscara contígua, EcoQoS ligado e desligado — o contraste do R.1."""
    n_logicos = max(1, int(n_logicos))
    n = max(1, min(int(n_por_braco), n_logicos))
    mask = list(range(n))
    return (
        {"contiguo_off": mask, "contiguo_on": mask},
        {"contiguo_off": False, "contiguo_on": True},
    )


TETO_LENTO_LIVRE = 1.5
"""R.3: candidato ≤ 1,5× de `livre` no regime lento. Declarado antes de medir."""

TETO_BENIGNO_CONTIGUO = 1.1
"""R.3: candidato ≤ 1,1× de `contiguo` no regime benigno. Declarado antes de medir."""

EMPATE_LENTO = 0.1
"""R.3: |candidato/contiguo − 1| no lento dentro disto é empate → remove a máscara."""


def plano_mascara(
    n_logicos: int, n_por_braco: int, topo: dict | None = None
) -> dict[str, list[int] | None]:
    """Um candidato, derivado da topologia — não uma grade, não a lista do 1355U."""
    from segundocerebro.index.regime_maquina import mascara_mista, topologia

    n_logicos = max(1, int(n_logicos))
    n = max(1, min(int(n_por_braco), n_logicos))
    t = topo if topo is not None else topologia()
    return {
        "livre": None,
        "contiguo": list(range(n)),
        "candidato": mascara_mista(n, t),
    }


def veredito_r3(lento: dict, benigno: dict) -> dict[str, object]:
    """Tetos do R.3, declarados antes da tabela. Empate encerra em remover a máscara."""
    for nome, bloco in (("lento", lento), ("benigno", benigno)):
        if bloco.get("veredito") == "recusado":
            return {"veredito": "recusado", "motivo": bloco.get("motivo"), "regime": nome}

    def _med(bloco: dict, braco: str) -> float:
        return float(bloco["bracos"][braco]["mediana_das_replicas"])

    livre_l = _med(lento, "livre")
    cand_l = _med(lento, "candidato")
    contig_l = _med(lento, "contiguo")
    cand_b = _med(benigno, "candidato")
    contig_b = _med(benigno, "contiguo")
    razao_lento_livre = round(cand_l / livre_l, 2)
    razao_lento_contig = round(cand_l / contig_l, 2)
    razao_benigno_contig = round(cand_b / contig_b, 2)
    passa_lento = razao_lento_livre <= TETO_LENTO_LIVRE
    passa_benigno = razao_benigno_contig <= TETO_BENIGNO_CONTIGUO
    empate = abs(razao_lento_contig - 1.0) <= EMPATE_LENTO
    if passa_lento and passa_benigno and not empate and razao_lento_contig < 1.0:
        decisao = "adotar_candidato"
    else:
        decisao = "remover_mascara"
    return {
        "veredito": "medido",
        "decisao": decisao,
        "razao_lento_livre": razao_lento_livre,
        "razao_lento_contiguo": razao_lento_contig,
        "razao_benigno_contiguo": razao_benigno_contig,
        "passa_lento": passa_lento,
        "passa_benigno": passa_benigno,
        "empate_lento": empate,
        "tetos": {"lento_livre": TETO_LENTO_LIVRE, "benigno_contiguo": TETO_BENIGNO_CONTIGUO},
    }


def rodar(
    bracos: dict[str, list[int] | None],
    *,
    replicas: int = 2,
    chunks: int = 8,
    threads: int = 6,
    ecoqos: bool | dict[str, bool] | None = None,
    sonda: bool = False,
    executor=None,
) -> list[Observacao]:
    """Roda os braços intercalados, um processo por braço.

    `executor` existe para o teste: recebe `(nome, mascara)` e devolve
    `Observacao`. Sem ele, cada braço vai para um subprocesso deste módulo.
    """
    if executor is None:

        def executor(nome: str, mascara: list[int] | None) -> Observacao:
            flag = ecoqos.get(nome) if isinstance(ecoqos, dict) else ecoqos
            return _em_subprocesso(
                nome, mascara, chunks=chunks, threads=threads, ecoqos=flag, sonda=sonda
            )

    fora: list[Observacao] = []
    for nome in ordem_intercalada(list(bracos), replicas):
        obs = executor(nome, bracos[nome])
        obs.braco = nome
        fora.append(obs)
    return fora


def _em_subprocesso(
    nome: str,
    mascara: list[int] | None,
    *,
    chunks: int,
    threads: int,
    ecoqos: bool | None = None,
    sonda: bool = False,
) -> Observacao:
    cmd = [
        sys.executable,
        "-m",
        "eval.regime",
        "--um-braco",
        "--mascara",
        "" if mascara is None else ",".join(str(i) for i in mascara),
        "--chunks",
        str(chunks),
        "--threads",
        str(threads),
    ]
    if ecoqos is True:
        cmd.extend(["--ecoqos", "on"])
    elif ecoqos is False:
        cmd.extend(["--ecoqos", "off"])
    if sonda:
        cmd.append("--sonda")
    saida = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if saida.returncode != 0:
        raise RuntimeError(f"braço '{nome}' falhou: {saida.stderr[-800:]}")
    dados = json.loads(saida.stdout.strip().splitlines()[-1])
    return Observacao(
        braco=nome,
        s_chunk=dados["s_chunk"],
        estado_antes=dados["estado_antes"],
        estado_depois=dados["estado_depois"],
        mascara=dados["mascara"],
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Vazão do encoder por regime de máquina (F4-R)")
    ap.add_argument("--um-braco", action="store_true", help="uso interno: mede e imprime JSON")
    ap.add_argument("--mascara", default="", help="lógicos separados por vírgula; vazio = livre")
    ap.add_argument("--chunks", type=int, default=8)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--replicas", type=int, default=2)
    ap.add_argument("--nucleos", type=int, default=None, help="tamanho das máscaras restritas")
    ap.add_argument("--ecoqos", choices=("on", "off"), default=None)
    ap.add_argument(
        "--contraste-ecoqos",
        action="store_true",
        help="mesma máscara contígua, EcoQoS ligado e desligado intercalados",
    )
    ap.add_argument(
        "--sonda",
        action="store_true",
        help="laço de CPU sem encoder — isola o gatilho sem carregar o modelo",
    )
    ap.add_argument(
        "--contraste-mascara",
        action="store_true",
        help="R.3: livre vs contiguo vs candidato, nos dois regimes, intercalado",
    )
    a = ap.parse_args(argv)
    eco = None if a.ecoqos is None else a.ecoqos == "on"

    if a.um_braco:
        mascara = [int(i) for i in a.mascara.split(",") if i.strip()] or None
        obs = medir_neste_processo(mascara, a.chunks, a.threads, ecoqos=eco, sonda=a.sonda)
        print(
            json.dumps(
                {
                    "s_chunk": obs.s_chunk,
                    "estado_antes": obs.estado_antes,
                    "estado_depois": obs.estado_depois,
                    "mascara": obs.mascara,
                }
            )
        )
        return 0

    n_log = os.cpu_count() or 4
    n_por_braco = a.nucleos or max(1, n_log // 2)
    if a.contraste_mascara:
        bracos = plano_mascara(n_log, n_por_braco)
        comum = dict(replicas=a.replicas, chunks=a.chunks, threads=a.threads, sonda=a.sonda)
        obs_off = rodar(bracos, ecoqos=False, **comum)
        obs_on = rodar(bracos, ecoqos=True, **comum)
        benigno = contraste(obs_off)
        lento = contraste(obs_on)
        if any(o.estado_antes.get("ecoqos") is not False for o in obs_off):
            benigno = {
                "veredito": "recusado",
                "motivo": "EcoQoS não ficou off no regime benigno.",
            }
        if any(o.estado_antes.get("ecoqos") is not True for o in obs_on):
            lento = {
                "veredito": "recusado",
                "motivo": "EcoQoS não ficou on no regime lento.",
            }
        print(
            json.dumps(
                {
                    "estado": estado(),
                    "mascaras": bracos,
                    "benigno": benigno,
                    "lento": lento,
                    "r3": veredito_r3(lento, benigno),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if a.contraste_ecoqos:
        bracos, flags = plano_ecoqos(n_log, n_por_braco)
        obs = rodar(
            bracos,
            replicas=a.replicas,
            chunks=a.chunks,
            threads=a.threads,
            ecoqos=flags,
            sonda=a.sonda,
        )
    else:
        bracos = plano_de_bracos(n_log, n_por_braco)
        obs = rodar(
            bracos,
            replicas=a.replicas,
            chunks=a.chunks,
            threads=a.threads,
            ecoqos=eco,
            sonda=a.sonda,
        )
    print(json.dumps({"estado": estado(), "contraste": contraste(obs)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
