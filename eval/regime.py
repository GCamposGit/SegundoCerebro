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
   mudou no meio.

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

AQUECIMENTO = 3
"""Chunks descartados antes de cronometrar. Mesmo valor de `eval/latencia.py`."""

REPLICAS_MINIMAS = 2
"""Abaixo disto `contraste` recusa. Uma réplica por braço é uma janela, não um braço."""

TEXTO = (
    "O contrato NN-VCE-001 fixa o prazo de entrega do relatorio "
    "trimestral e a revisao do escopo pela VCE."
)
"""Vocabulário VCE, fixo. O braço mede a máquina; o texto não pode variar."""


def estado() -> dict[str, object]:
    """Regime da máquina agora — o que faltava em toda medição de vazão daqui.

    `tomada` é `None` em desktop sem bateria, e isso é informação: significa que
    aquele setup não tem o eixo que produziu o 22× neste notebook.
    """
    dados: dict[str, object] = {
        "maquina": platform.node(),
        "processador": platform.processor(),
        "logicos": os.cpu_count(),
    }
    try:
        import psutil

        bateria = psutil.sensors_battery()
        dados["tomada"] = None if bateria is None else bool(bateria.power_plugged)
        dados["bateria_pct"] = None if bateria is None else bateria.percent
        freq = psutil.cpu_freq()
        dados["mhz"] = None if freq is None else round(freq.current)
        dados["fisicos"] = psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001 — sem psutil o resto do relato continua válido
        dados["tomada"] = None
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
        """Tomada ou frequência mudaram no meio do braço — o número é suspeito."""
        a, d = self.estado_antes, self.estado_depois
        return a.get("tomada") != d.get("tomada")


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

    resumo = {
        b: {
            "medianas": [round(o.mediana, 4) for o in v],
            "mediana_das_replicas": round(statistics.median([o.mediana for o in v]), 4),
            "regime_mudou": any(o.regime_mudou for o in v),
        }
        for b, v in por_braco.items()
    }
    base = resumo.get("livre", {}).get("mediana_das_replicas")
    if base:
        for b, d in resumo.items():
            d["razao_contra_livre"] = round(d["mediana_das_replicas"] / base, 2)

    suspeito = [b for b, d in resumo.items() if d["regime_mudou"]]
    return {
        "veredito": "medido" if not suspeito else "medido_com_ressalva",
        "ressalva": (
            None
            if not suspeito
            else f"estado de energia mudou durante: {suspeito}. Refazer com o estado fixo."
        ),
        "bracos": resumo,
    }


# ---------------------------------------------------------------------------
# Execução de um braço: processo próprio, sempre.
# ---------------------------------------------------------------------------


def medir_neste_processo(mascara: list[int] | None, chunks: int, threads: int) -> Observacao:
    """Um braço, neste processo. Chamado pelo subprocesso — não chamar em laço.

    A máscara entra **antes** do `Embedder`, porque a sessão do ORT fixa a
    threadpool na criação. (Que a ordem não seja a causa do 22× foi medido e está
    no laudo; ainda assim o instrumento aplica na ordem do arranque do produto.)
    """
    import time

    mascara_efetiva: list[int] = []
    try:
        import psutil

        proc = psutil.Process()
        if mascara is not None:
            proc.cpu_affinity(mascara)
        mascara_efetiva = list(proc.cpu_affinity())
    except Exception:  # noqa: BLE001 — sonda de máscara não aborta a medição
        # `mascara_efetiva` fica vazia, e é isso que o relatório registra: a
        # observação sai declarando que a afinidade **não** foi aplicada, em vez
        # de sair como se tivesse sido. psutil ausente, plataforma sem afinidade
        # de CPU e máscara recusada pelo SO caem todas aqui, e as três têm a
        # mesma consequência para quem lê o número.
        pass

    antes = estado()
    from segundocerebro.index.embeddings import Embedder

    emb = Embedder("e5-large", threads=threads, lazy=False)
    for _ in range(AQUECIMENTO):
        emb.embed_passagens([TEXTO], batch_size=1, ritmo=1.0)

    tempos: list[float] = []
    for _ in range(chunks):
        t = time.perf_counter()
        emb.embed_passagens([TEXTO], batch_size=1, ritmo=1.0)
        tempos.append(time.perf_counter() - t)

    return Observacao(
        braco="",
        s_chunk=tempos,
        estado_antes=antes,
        estado_depois=estado(),
        mascara=mascara_efetiva,
    )


def rodar(
    bracos: dict[str, list[int] | None],
    *,
    replicas: int = 2,
    chunks: int = 8,
    threads: int = 6,
    executor=None,
) -> list[Observacao]:
    """Roda os braços intercalados, um processo por braço.

    `executor` existe para o teste: recebe `(nome, mascara)` e devolve
    `Observacao`. Sem ele, cada braço vai para um subprocesso deste módulo.
    """
    if executor is None:
        executor = lambda nome, mascara: _em_subprocesso(  # noqa: E731
            nome, mascara, chunks=chunks, threads=threads
        )
    fora: list[Observacao] = []
    for nome in ordem_intercalada(list(bracos), replicas):
        obs = executor(nome, bracos[nome])
        obs.braco = nome
        fora.append(obs)
    return fora


def _em_subprocesso(
    nome: str, mascara: list[int] | None, *, chunks: int, threads: int
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
    a = ap.parse_args(argv)

    if a.um_braco:
        mascara = [int(i) for i in a.mascara.split(",") if i.strip()] or None
        obs = medir_neste_processo(mascara, a.chunks, a.threads)
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
    bracos = plano_de_bracos(n_log, n_por_braco)
    obs = rodar(bracos, replicas=a.replicas, chunks=a.chunks, threads=a.threads)
    print(json.dumps({"estado": estado(), "contraste": contraste(obs)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
