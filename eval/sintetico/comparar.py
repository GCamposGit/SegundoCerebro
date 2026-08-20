"""Dois índices do mesmo corpus — os vetores são o mesmo espaço?

    py -m eval.sintetico.comparar --a index-sintetico-gpu --b index-sintetico-cpu

Critério da F3.6: similaridade de cosseno > 0,9999 em cada chunk presente
nos dois lados, e o mesmo `model_id`. Hardware não entra no fingerprint.

Não carrega o encoder. Não reindexa.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np

from segundocerebro.index.embeddings import MODELOS
from segundocerebro.index.store import Store
from segundocerebro.logger import get_logger

log = get_logger("eval.sintetico")

LIMIAR = 0.9999
MODELO = "e5-large"


@dataclass(frozen=True)
class Relatorio:
    comuns: int
    so_a: int
    so_b: int
    min_cosseno: float
    med_cosseno: float
    abaixo: tuple[str, ...]
    modelos_a: tuple[str, ...]
    modelos_b: tuple[str, ...]

    @property
    def passou(self) -> bool:
        return (
            self.comuns > 0
            and self.so_a == 0
            and self.so_b == 0
            and not self.abaixo
            and not self.abaixo
            and self.modelos_a == self.modelos_b
            and bool(self.modelos_a)
        )


def cosseno(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def comparar(va: dict[str, np.ndarray], vb: dict[str, np.ndarray],
             modelos_a: tuple[str, ...] = (),
             modelos_b: tuple[str, ...] = (),
             *, limiar: float = LIMIAR) -> Relatorio:
    comuns = sorted(set(va) & set(vb))
    scores = [cosseno(va[i], vb[i]) for i in comuns]
    abaixo = tuple(i for i, s in zip(comuns, scores) if s <= limiar)
    return Relatorio(
        comuns=len(comuns),
        so_a=len(set(va) - set(vb)),
        so_b=len(set(vb) - set(va)),
        min_cosseno=min(scores) if scores else 0.0,
        med_cosseno=float(np.mean(scores)) if scores else 0.0,
        abaixo=abaixo,
        modelos_a=modelos_a,
        modelos_b=modelos_b,
    )


def _abrir(caminho, dim: int) -> tuple[Store, dict[str, np.ndarray], tuple[str, ...]]:
    store = Store(caminho, dim)
    estat = store.estatisticas()
    modelos = tuple(estat.get("modelos") or ())
    return store, store.vetores_por_id(), modelos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.sintetico.comparar")
    parser.add_argument("--a", required=True, help="primeiro índice (ex.: feito na GPU)")
    parser.add_argument("--b", required=True, help="segundo índice (ex.: CPU, ou o notebook)")
    parser.add_argument("--limiar", type=float, default=LIMIAR)
    args = parser.parse_args(argv)

    dim = MODELOS[MODELO].dim
    sa = sb = None
    try:
        sa, va, ma = _abrir(args.a, dim)
        sb, vb, mb = _abrir(args.b, dim)
        rel = comparar(va, vb, ma, mb, limiar=args.limiar)
    finally:
        if sa is not None:
            sa.fechar()
        if sb is not None:
            sb.fechar()

    log.info(
        "%s × %s · %d chunks em comum · só A %d · só B %d · "
        "cosseno min %.6f med %.6f · modelos A %s B %s",
        args.a, args.b, rel.comuns, rel.so_a, rel.so_b,
        rel.min_cosseno, rel.med_cosseno, rel.modelos_a, rel.modelos_b,
    )
    if rel.abaixo:
        log.error("%d chunks abaixo de %.4f: %s", len(rel.abaixo), args.limiar, ", ".join(rel.abaixo[:8]))
    if rel.modelos_a != rel.modelos_b:
        log.error("model_id diverge: %s vs %s", rel.modelos_a, rel.modelos_b)
    if not rel.passou:
        log.error("F3.6: índices não são o mesmo espaço — não copiar sem reembeddar")
        return 3
    log.info("ok: hardware não mudou os vetores (limiar %.4f)", args.limiar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
