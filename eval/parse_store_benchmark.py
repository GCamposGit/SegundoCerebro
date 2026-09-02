"""J.f paired end-to-end rebuilds; no production flags or cache shortcuts."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
from importlib.metadata import version

import psutil
import onnxruntime

from segundocerebro.census import Config, RootSpec
from segundocerebro.index.embeddings import Embedder
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import Store
from segundocerebro.ingest.parse_cache import canonicos_disponiveis
from segundocerebro.ingest.parse_store import assinatura_do_motor
from segundocerebro.ingest.ocr import backend_disponivel
from segundocerebro.logger import get_logger
from .estatistica import ic_da_media
from .parse_store_corpus import ROTAS, gerar, manifesto
from .regime import ordem_intercalada

log = get_logger("eval.parse_store")
PARES = 6
RAM_PARSE_MB = 2048


def gravar(path: Path, dados: dict) -> None:
    with path.open("x", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, sort_keys=True, indent=2)


def estado() -> dict:
    freq, bateria = psutil.cpu_freq(), psutil.sensors_battery()
    termometro = getattr(psutil, "sensors_temperatures", None)
    temperaturas = termometro() if termometro else {}
    return {"cpu_pct": psutil.cpu_percent(interval=0.1),
            "mhz": freq.current if freq else None,
            "ram_livre_gb": round(psutil.virtual_memory().available / 2**30, 2),
            "tomada": bateria.power_plugged if bateria else None,
            "temperaturas_c": [t.current for grupo in temperaturas.values() for t in grupo]
            or None}


def digest(dados: object) -> str:
    return sha256(json.dumps(dados, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def assinatura(store: Store) -> dict:
    """Compare logical records and exact vectors, not physical DB file layout."""
    documentos = [dict(r) for r in store.con.execute("SELECT * FROM documentos ORDER BY path")]
    if len(documentos) != sum(ROTAS.values()) or any(
        r["status"] != "ok" or r["n_chunks"] < 1 for r in documentos
    ):
        raise ValueError("rebuild incompleto: documentos sem texto indexado")
    canonicos, rotas = {}, Counter()
    for row in documentos:
        row.pop("indexado_em")
        chave, canonico = next(canonicos_disponiveis(
            store.diretorio, row["sha256"], Path(row["path"]).suffix, ocr=True,
        ))
        canonicos[row["path"]] = asdict(canonico)
        rotas[chave.rota] += 1
    if dict(rotas) != ROTAS:
        raise ValueError(f"rotas não exercitadas: {dict(rotas)}")
    chunks = [dict(r) for r in store.con.execute("SELECT * FROM chunks ORDER BY id")]
    vetores = store.vetores_por_id()
    if set(vetores) != {c["id"] for c in chunks}:
        raise ValueError("vetores ausentes ou divergentes dos chunks")
    return {"registro": digest(documentos), "canonico": digest(canonicos),
            "chunks": digest(chunks), "vetores": digest({
                k: sha256(v.astype("<f4").tobytes()).hexdigest() for k, v in vetores.items()}),
            "n_chunks": len(chunks), "rotas": dict(rotas)}


def worker(raiz: Path, nome: str) -> None:
    """Every invocation owns one new index; the parent only seeds Parse Store."""
    corpus, indice = raiz / "corpus", raiz / nome
    if (indice / "registro.db").exists():
        raise ValueError("rodada já existe; recusando reutilizar um índice")
    arquivos = manifesto(corpus)
    antes = estado()
    inicio = time.perf_counter()
    encoder = Embedder("e5-large", threads=4)
    store = Store(indice, encoder.dim)
    try:
        progresso = indexar(Config(roots=[RootSpec("sintetico", corpus)]), store, encoder,
                            parse_workers=1, ram_parse_mb=RAM_PARSE_MB, ocr=True)
        store.commit()
    finally:
        store.fechar()
    segundos = time.perf_counter() - inicio
    depois = estado()
    if manifesto(corpus) != arquivos:
        raise ValueError("corpus alterado durante o rebuild")
    auditoria = Store(indice, encoder.dim)
    try:
        conteudo = assinatura(auditoria)
        etapas = [dict(r) for r in auditoria.con.execute(
            "SELECT path,s_parse,s_chunk,s_embed,s_grava,suspeito FROM medicoes ORDER BY id")]
    finally:
        auditoria.fechar()
    gravar(raiz / f"{nome}.json", {
        "nome": nome, "segundos": segundos, "progresso": asdict(progresso),
        "assinatura": conteudo, "manifesto": arquivos,
        "estado_antes": antes, "estado_depois": depois, "etapas": etapas,
        "modelo": encoder.model_id,
    })


def resumir(observacoes: list[dict]) -> dict:
    """A missing/failed arm invalidates the experiment instead of looking fast."""
    if len(observacoes) != PARES * 2:
        raise ValueError("experimento exige seis pares completos")
    referencia = observacoes[0]
    reducoes = []
    for i in range(0, len(observacoes), 2):
        frio, quente = observacoes[i:i + 2]
        for obs, braco in ((frio, "frio"), (quente, "quente")):
            if obs["nome"] != f"{i // 2 + 1:02d}-{braco}":
                raise ValueError("ordem de braços inválida")
            if any(obs[k] != referencia[k] for k in ("assinatura", "manifesto", "modelo")):
                raise ValueError("conteúdo ou configuração divergente")
            if not math.isfinite(obs["segundos"]) or obs["segundos"] <= 0:
                raise ValueError("tempo inválido")
            p = obs["progresso"]
            consultas, hits = p["parse_store_consultas"], p["parse_store_hits"]
            if (consultas < sum(ROTAS.values()) or hits != (0 if braco == "frio" else consultas)
                    or p["interrompido"] or p["quarentena"] or p["pulados"]):
                raise ValueError("braço não exerceu o rebuild/cache esperado")
            if any(e["suspeito"] for e in obs["etapas"]):
                raise ValueError("medição marcada como suspeita pelo produto")
            if obs["estado_antes"]["tomada"] != obs["estado_depois"]["tomada"]:
                raise ValueError("alimentação mudou durante a rodada")
        reducoes.append(1 - quente["segundos"] / frio["segundos"])
    baixo, alto = ic_da_media(reducoes)
    media = statistics.mean(reducoes)
    veredito = "confirmada" if baixo >= 0.8 else "refutada" if media < 0.8 else "inconclusiva"
    return {"pares": PARES, "reducao_media": media, "ic95": [baixo, alto],
            "reducoes_pareadas": reducoes, "hipotese_80pct": veredito,
            "mediana_fria_s": statistics.median(o["segundos"] for o in observacoes[::2]),
            "mediana_quente_s": statistics.median(o["segundos"] for o in observacoes[1::2])}


def executar(raiz: Path, nome: str, ambiente: dict) -> dict:
    inicio = time.perf_counter()
    subprocess.run(  # noqa: S603 — fixed module, own generated paths and no shell
        [sys.executable, "-m", "eval.parse_store_benchmark", "--out", str(raiz), "--worker", nome],
        check=True, timeout=300, stdout=subprocess.DEVNULL,
        env=dict(ambiente, SEGUNDOCEREBRO_CALIBRACAO=str(raiz / nome / "calibracao")),
    )
    observacao = json.loads((raiz / f"{nome}.json").read_text(encoding="utf-8"))
    observacao["segundos_processo"] = time.perf_counter() - inicio
    return observacao


def rodar(raiz: Path) -> dict:
    """Fixed sample size and stopping rule; never tune after seeing results."""
    if backend_disponivel() not in {"rapidocr", "tesseract"}:
        raise RuntimeError("OCR real obrigatório; motor falso ou ausente não mede J.f")
    ambiente = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                    SEGUNDOCEREBRO_PROVIDER="cpu")
    arquivos = gerar(raiz)
    aquecimento = executar(raiz, "aquecimento", ambiente)
    observacoes = []
    for n, braco in enumerate(ordem_intercalada(["frio", "quente"], PARES)):
        nome = f"{n // 2 + 1:02d}-{braco}"
        if braco == "quente":
            shutil.copytree(raiz / "aquecimento" / "parse_store", raiz / nome / "parse_store")
        obs = executar(raiz, nome, ambiente)
        if obs["assinatura"] != aquecimento["assinatura"] or obs["manifesto"] != arquivos:
            raise ValueError("rebuild divergiu do aquecimento ou alterou originais")
        observacoes.append(obs)
        log.warning("J.f %s concluído: %.2f s", nome, obs["segundos"])
    resultado = {"data_utc": datetime.now(timezone.utc).isoformat(),
                 "maquina": "Desktop", "cpu": platform.processor(), "so": platform.platform(),
                 "cpu_fisicos": psutil.cpu_count(logical=False), "cpu_logicos": os.cpu_count(),
                 "ram_gb": round(psutil.virtual_memory().total / 2**30, 2),
                 "codigo_sha256": {n: sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                                   for n in ("parse_store_benchmark.py", "parse_store_corpus.py")},
                 "python": platform.python_version(), "threads": 4, "parse_workers": 1,
                 "ram_parse_mb": RAM_PARSE_MB, "calibracao": "nova e isolada por rodada",
                 "ocr": backend_disponivel(), "libreoffice": assinatura_do_motor("libreoffice"),
                 "versoes": {"fastembed": version("fastembed"), "pymupdf": version("pymupdf"),
                             "onnxruntime": onnxruntime.__version__,
                             "ocr": version("rapidocr-onnxruntime")
                             if backend_disponivel() == "rapidocr" else version("pytesseract")},
                 "cache_so": "não controlado; corpus pré-lido em ambos os braços",
                 "corpus": arquivos, "aquecimento": aquecimento,
                 "observacoes": observacoes, "resumo": resumir(observacoes)}
    gravar(raiz / "resultado.json", resultado)
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", choices=["aquecimento"] + [
        f"{i:02d}-{b}" for i in range(1, PARES + 1) for b in ("frio", "quente")],
        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.out.resolve(), args.worker)
    else:
        resultado = rodar(args.out.resolve())
        sys.stdout.write(json.dumps(resultado["resumo"], ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
