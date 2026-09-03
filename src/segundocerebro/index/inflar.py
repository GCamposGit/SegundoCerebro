"""Inflate an index to N chunks by perturbing existing vectors — R9.3.

The latency door is defined (`eval/latencia.py`, `eval/portas-latencia.toml`).
What was missing is the 1M-chunk index. Embedding 1M documents from scratch is
a 22 h job on this desktop. R4.1's recipe is to perturb vectors that already
exist: no encoder, minutes not hours, and the artefact is gitignored
(`/index-*/`).

The method is this module. The 1M file is a local measurement, not a commit.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..ingest.chunking import Chunk
from ..ingest.document import BlockKind
from ..logger import get_logger
from .store import Store, recusar_se_indexando

log = get_logger("index.inflar")

LOTE = 8192
CHUNKS_POR_DOC = 64
RUIDO = 0.01
PREFIXO = "inflado"


@dataclass(frozen=True)
class Relato:
    origem: Path
    destino: Path
    n_origem: int
    n_destino: int
    dim: int
    model_id: str
    seed: int


class InflarErro(RuntimeError):
    """Portuguese: the inflator refused, and the reason is the message."""


def dim_do_indice(diretorio: Path) -> int:
    """Read dimension from `model_id` (`e5-large:1024:fastembed0.8.0`).

    Opening Store with the wrong dim fails only when the Lance table is first
    touched. Parsing the registry is cheaper and does not load the encoder.
    """
    db = Path(diretorio) / "registro.db"
    if not db.is_file():
        raise InflarErro(f"não achei registro em {diretorio}")
    con = sqlite3.connect(str(db))
    try:
        linha = con.execute(
            "SELECT model_id FROM documentos "
            "WHERE model_id IS NOT NULL AND model_id != '' LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if not linha:
        raise InflarErro(f"índice em {diretorio} não tem model_id — nada a inflar")
    partes = str(linha[0]).split(":")
    if len(partes) < 2 or not partes[1].isdigit():
        raise InflarErro(f"model_id sem dimensão: {linha[0]}")
    return int(partes[1])


def semente(store: Store) -> tuple[list[Chunk], list[np.ndarray], str]:
    """Chunks that actually have a vector. Missing vectors are dropped."""
    vetores = store.vetores_por_id()
    chunks: list[Chunk] = []
    arr: list[np.ndarray] = []
    model_id = ""
    for path in store.paths_com_chunks():
        for gravado in store.chunks_de(path):
            vetor = vetores.get(gravado.id)
            if vetor is None:
                continue
            chunks.append(_como_chunk(gravado))
            arr.append(np.asarray(vetor, dtype=np.float32))
            if not model_id:
                model_id = _model_id_de(store, path)
    if not chunks:
        raise InflarErro(f"índice em {store.diretorio} não tem trechos com vetor")
    return chunks, arr, model_id


def _model_id_de(store: Store, path: str) -> str:
    linha = store.con.execute(
        "SELECT model_id FROM documentos WHERE path = ?", (path,)
    ).fetchone()
    return str(linha["model_id"]) if linha and linha["model_id"] else ""


def _como_chunk(gravado: object) -> Chunk:
    kind_bruto = getattr(gravado, "kind", "") or BlockKind.TEXT.value
    try:
        kind = BlockKind(kind_bruto)
    except ValueError:
        kind = BlockKind.TEXT
    trilha = getattr(gravado, "trilha", "") or ""
    heading = tuple(p for p in trilha.split(" > ") if p)
    return Chunk(
        id=gravado.id,
        doc_path=gravado.path,
        ordinal=int(gravado.ordinal),
        heading_path=heading,
        text=gravado.texto,
        locator=getattr(gravado, "locator", "") or "",
        kind=kind,
    )


def perturbar(vetor: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Small Gaussian noise, then L2-normalise. Same seed ⇒ same vector."""
    ruido = rng.standard_normal(vetor.shape).astype(np.float32) * RUIDO
    saida = vetor.astype(np.float32) + ruido
    norma = float(np.linalg.norm(saida))
    if norma == 0.0:
        return vetor.astype(np.float32)
    return saida / norma


def replica(base: Chunk, vetor: np.ndarray, i: int, seed: int) -> tuple[Chunk, np.ndarray]:
    rng = np.random.default_rng(seed + i)
    path = f"{PREFIXO}/{i // CHUNKS_POR_DOC:07d}.txt"
    novo = Chunk(
        id=f"{PREFIXO}-{i:07d}",
        doc_path=path,
        ordinal=i % CHUNKS_POR_DOC,
        heading_path=base.heading_path,
        text=base.text,
        locator=base.locator,
        kind=base.kind,
    )
    return novo, perturbar(vetor, rng)


def _matriz_perturbada(
    base: np.ndarray, start: int, size: int, rng: np.random.Generator
) -> np.ndarray:
    """One Gaussian draw for the whole batch — not one RNG per chunk."""
    k, dim = base.shape
    idx = np.arange(start, start + size) % k
    saida = base[idx] + rng.standard_normal((size, dim), dtype=np.float32) * RUIDO
    normas = np.linalg.norm(saida, axis=1, keepdims=True)
    np.maximum(normas, 1e-12, out=normas)
    saida /= normas
    return saida.astype(np.float32, copy=False)


def _chunks_do_lote(bases: list[Chunk], start: int, size: int) -> list[Chunk]:
    k = len(bases)
    saida: list[Chunk] = []
    for i in range(start, start + size):
        b = bases[i % k]
        saida.append(
            Chunk(
                id=f"{PREFIXO}-{i:07d}",
                doc_path=f"{PREFIXO}/{i // CHUNKS_POR_DOC:07d}.txt",
                ordinal=i % CHUNKS_POR_DOC,
                heading_path=b.heading_path,
                text=b.text,
                locator=b.locator,
                kind=b.kind,
            )
        )
    return saida


def _registrar_docs(dest: Store, chunks: list[Chunk], model_id: str) -> None:
    from collections import Counter

    from .store import agora

    n_por = Counter(c.doc_path for c in chunks)
    agora_iso = agora()
    dest.con.executemany(
        "INSERT OR REPLACE INTO documentos "
        "(path, raiz, tamanho, mtime, sha256, status, detalhe, n_chunks, "
        "model_id, chunker, parser, indexado_em) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (path, PREFIXO, 0, 1.0, "", "ok", "", n_chunks, model_id, "", "", agora_iso)
            for path, n_chunks in n_por.items()
        ],
    )


def _gravar_vetores_arrow(
    dest: Store, chunks: list[Chunk], matriz: np.ndarray, model_id: str
) -> None:
    import pyarrow as pa

    dim = int(matriz.shape[1])
    flat = pa.array(matriz.reshape(-1), type=pa.float32())
    dest.tabela.add(
        pa.table(
            {
                "id": [c.id for c in chunks],
                "path": [c.doc_path for c in chunks],
                "ordinal": [c.ordinal for c in chunks],
                "kind": [c.kind.value for c in chunks],
                "ext": [".txt"] * len(chunks),
                "mtime": [1.0] * len(chunks),
                "model_id": [model_id] * len(chunks),
                "vetor": pa.FixedSizeListArray.from_arrays(flat, dim),
            }
        )
    )


def inflar(origem: Path, destino: Path, n: int, seed: int = 42) -> Relato:
    """Write `n` chunks into `destino`, copied-and-perturbed from `origem`."""
    origem = Path(origem)
    destino = Path(destino)
    if origem.resolve() == destino.resolve():
        raise InflarErro("destino e origem são o mesmo índice")
    if n < 1:
        raise InflarErro(f"n={n} não infla nada")
    recusar_se_indexando(origem)
    dim = dim_do_indice(origem)
    src = Store(origem, dim)
    try:
        chunks, vetores, model_id = semente(src)
    finally:
        src.fechar()
    if n < len(chunks):
        raise InflarErro(
            f"n={n} é menor que a semente ({len(chunks)} trechos) — inflar não apaga"
        )
    recusar_se_indexando(destino)
    dest = Store(destino, dim)
    try:
        dest.con.execute("PRAGMA synchronous=OFF")
        dest.con.execute("PRAGMA cache_size=-262144")
        _escrever(dest, chunks, vetores, n, seed, model_id)
        cons = dest.verificar_consistencia()
        if cons["diferenca"] != 0:
            raise InflarErro(
                f"índice inflado inconsistente: {cons['chunks']} trechos, "
                f"{cons['vetores']} vetores"
            )
        n_dest = int(dest.estatisticas()["chunks"])
    finally:
        dest.fechar()
    return Relato(origem, destino, len(chunks), n_dest, dim, model_id, seed)


def _escrever(
    dest: Store,
    chunks: list[Chunk],
    vetores: list[np.ndarray],
    n: int,
    seed: int,
    model_id: str,
) -> None:
    rng = np.random.default_rng(seed)
    base = np.stack(vetores).astype(np.float32, copy=False)
    for start in range(0, n, LOTE):
        size = min(LOTE, n - start)
        lote = _chunks_do_lote(chunks, start, size)
        matriz = _matriz_perturbada(base, start, size, rng)
        _registrar_docs(dest, lote, model_id)
        dest.gravar_textos(lote)
        _gravar_vetores_arrow(dest, lote, matriz, model_id)
        dest.commit()
        log.info("inflar %d/%d", start + size, n)
    log.info("índice inflado: %d trechos em %s", n, dest.diretorio)


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="segundocerebro.index.inflar",
        description=(
            "Infla um índice para N trechos perturbando vetores já gravados. "
            "Não carrega o encoder. O destino fica fora do Git (`/index-*/`)."
        ),
    )
    p.add_argument("--origem", required=True, type=Path)
    p.add_argument("--destino", required=True, type=Path)
    p.add_argument("--n", required=True, type=int, help="trechos no destino (≥ semente)")
    p.add_argument("--seed", type=int, default=42)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        relato = inflar(args.origem, args.destino, args.n, args.seed)
    except InflarErro as erro:
        log.error("%s", erro)
        print(erro)
        return 2
    print(
        f"inflado: {relato.n_origem} → {relato.n_destino} trechos · "
        f"dim {relato.dim} · `{relato.model_id}` · seed {relato.seed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
