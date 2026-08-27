"""Ingestion report: parse the corpus and account for every file.

Answers the questions F1 cannot proceed without: how many PDFs are scanned and
would need OCR, how many files are locked during a run, how many formats have
no parser, and how long a full pass takes. A file that produced no text is a
decision to make, not a rounding error — so nothing is allowed to vanish
silently between the census count and the index count.

    py -m segundocerebro.ingest.report --config census.toml --amostra 200
"""

from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..census import Config, load_config
from ..census import iter_files
from ..logger import get_logger
from .chunking import ChunkConfig, chunk_document
from .document import ParseStatus
from .reader import parse_file

log = get_logger("ingest.report")


def amostra_estratificada(arquivos: list, alvo: int) -> list:  # noqa: ANN001
    """Every k-th file within each extension, so rare formats still show up."""
    if alvo <= 0 or len(arquivos) <= alvo:
        return arquivos
    por_extensao: dict[str, list] = defaultdict(list)
    for f in arquivos:
        por_extensao[Path(f.rel).suffix.lower()].append(f)

    escolhidos: list = []
    for _, grupo in sorted(por_extensao.items()):
        cota = max(1, round(alvo * len(grupo) / len(arquivos)))
        passo = max(1, len(grupo) // cota)
        escolhidos.extend(grupo[::passo][:cota])
    return escolhidos


def executar(cfg: Config, alvo_amostra: int = 0, limite_mb: float = 0.0) -> dict:
    arquivos = [f for root in cfg.roots for f in iter_files(root, cfg)]
    total_corpus = len(arquivos)
    arquivos = amostra_estratificada(arquivos, alvo_amostra)
    if limite_mb:
        arquivos = [f for f in arquivos if f.size <= limite_mb * 1024 * 1024]

    por_status: Counter[str] = Counter()
    por_extensao_status: dict[str, Counter[str]] = defaultdict(Counter)
    chars_por_extensao: Counter[str] = Counter()
    blocos_por_extensao: Counter[str] = Counter()
    chunks_por_extensao: Counter[str] = Counter()
    chars_de_chunk_por_extensao: Counter[str] = Counter()
    exemplos: dict[str, list[str]] = defaultdict(list)
    segundos_por_extensao: Counter[str] = Counter()
    formulas_sem_cache = 0
    exemplos_sem_cache: list[str] = []
    cfg_chunk = ChunkConfig()

    inicio = time.perf_counter()
    for i, arquivo in enumerate(arquivos, start=1):
        ext = Path(arquivo.rel).suffix.lower() or "(sem extensão)"
        t0 = time.perf_counter()
        resultado = parse_file(arquivo.path, retries=1, espera=0.5)
        segundos_por_extensao[ext] += time.perf_counter() - t0

        por_status[resultado.status.value] += 1
        por_extensao_status[ext][resultado.status.value] += 1
        if resultado.doc is not None:
            chars_por_extensao[ext] += resultado.doc.total_chars
            blocos_por_extensao[ext] += len(resultado.doc.blocks)
            # o chunk é a unidade que custa embedding — é dele que sai a conta
            chunks = chunk_document(resultado.doc, arquivo.rel, cfg_chunk)
            chunks_por_extensao[ext] += len(chunks)
            chars_de_chunk_por_extensao[ext] += sum(c.chars for c in chunks)
            if resultado.doc.meta.get("sem_valor_em_cache") == "1":
                formulas_sem_cache += 1
                if len(exemplos_sem_cache) < 12:
                    exemplos_sem_cache.append(arquivo.rel)
        if resultado.status is not ParseStatus.OK and len(exemplos[resultado.status.value]) < 12:
            exemplos[resultado.status.value].append(arquivo.rel)
        if i % 100 == 0:
            log.info("%d/%d arquivos", i, len(arquivos))

    return {
        "total_corpus": total_corpus,
        "analisados": len(arquivos),
        "segundos": time.perf_counter() - inicio,
        "por_status": por_status,
        "por_extensao_status": por_extensao_status,
        "chars_por_extensao": chars_por_extensao,
        "blocos_por_extensao": blocos_por_extensao,
        "chunks_por_extensao": chunks_por_extensao,
        "chars_de_chunk_por_extensao": chars_de_chunk_por_extensao,
        "segundos_por_extensao": segundos_por_extensao,
        "exemplos": exemplos,
        "formulas_sem_cache": formulas_sem_cache,
        "exemplos_sem_cache": exemplos_sem_cache,
    }


def render_markdown(r: dict) -> str:
    linhas: list[str] = []
    add = linhas.append
    total = r["analisados"]

    add("# Relatório de ingestão")
    add("")
    add(f"- Corpus: **{r['total_corpus']}** documentos · analisados: **{total}**")
    add(f"- Tempo: **{r['segundos']:.1f}s** ({r['segundos'] / total:.2f}s por arquivo)" if total else "")
    add("")

    add("## Situação")
    add("")
    add("| Situação | Arquivos | % |")
    add("|---|---:|---:|")
    for status, n in r["por_status"].most_common():
        add(f"| {status} | {n} | {n / total * 100:.1f}% |")
    add("")
    n_sem_cache = r.get("formulas_sem_cache") or 0
    if n_sem_cache:
        add(
            f"**{n_sem_cache} planilha(s) com fórmulas não calculadas.** "
            "Sem LibreOffice o número (Equity Value, total) não entra no índice. "
            "Instalar o `soffice` e reindexar preenche o cache (C7.a)."
        )
        add("")
        for rel in r.get("exemplos_sem_cache") or []:
            add(f"- `{rel}`")
        add("")

    add("## Por formato")
    add("")
    add("| Extensão | n | ok | vazio | travado | erro | sem parser | blocos | chunks | chunks/doc | chars/chunk | s/doc |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for ext, contagem in sorted(r["por_extensao_status"].items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(contagem.values())
        ok = contagem.get("ok", 0)
        chunks = r["chunks_por_extensao"][ext]
        add(
            f"| `{ext}` | {n} | {ok} | {contagem.get('vazio', 0)} | {contagem.get('travado', 0)} | "
            f"{contagem.get('erro', 0)} | {contagem.get('sem_parser', 0)} | "
            f"{r['blocos_por_extensao'][ext]} | {chunks} | {chunks / ok if ok else 0:.1f} | "
            f"{r['chars_de_chunk_por_extensao'][ext] // chunks if chunks else 0} | "
            f"{r['segundos_por_extensao'][ext] / n:.2f} |"
        )
    add("")

    total_chunks = sum(r["chunks_por_extensao"].values())
    if total_chunks and r["analisados"]:
        por_doc = total_chunks / r["analisados"]
        projecao = por_doc * r["total_corpus"]
        add("## Projeção de custo de indexação")
        add("")
        add(f"- Chunks na amostra: **{total_chunks}** ({por_doc:.1f} por documento)")
        add(f"- Projeção para {r['total_corpus']} documentos: **~{projecao:,.0f} chunks**".replace(",", "."))
        add("- Cada chunk é um forward pass do BGE-M3 em CPU — é esta a conta que domina a indexação")
        add("")

    for status, arquivos in sorted(r["exemplos"].items()):
        add(f"## Exemplos — {status}")
        add("")
        for rel in arquivos:
            add(f"- `{rel}`")
        add("")

    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.ingest.report")
    parser.add_argument("--config", type=Path, default=Path("census.toml"))
    parser.add_argument("--amostra", type=int, default=0, help="amostra estratificada por extensão (0 = tudo)")
    parser.add_argument("--limite-mb", type=float, default=0.0, help="ignora arquivos acima deste tamanho")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    resultado = executar(cfg, args.amostra, args.limite_mb)
    relatorio = render_markdown(resultado)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(relatorio, encoding="utf-8")
        log.info("relatório gravado em %s", args.out)
    else:
        print(relatorio)  # noqa: T201 — saída do CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
