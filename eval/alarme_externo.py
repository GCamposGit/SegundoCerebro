"""Camada 3 — alarme externo depois do MIRACL (C5.c).

O C5.a fechou o MIRACL-PT: língua ausente, sem download. Esta porta congela o
sucessor **antes** de baixar o próximo dump, com a mesma conta de 12 h.

Nada aqui baixa HuggingFace. Nada vira `[[base]]`. O smoke de encoder é o do
`eval.custo_miracl` e recusa trava viva.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from eval.custo_miracl import (
    ADOTAR,
    DESCARTAR,
    MOTIVO_CABE,
    MOTIVO_CUSTO,
    MOTIVO_LINGUA,
    PORTA_HORAS,
    decidir_custo,
    horas,
    taxa_semente,
)

CAMADA_3 = "quati-50k"
CANARIO_CROSSLINGUAL = "pira-2"

MOTIVO_TRADUCAO = "traducao"
MOTIVO_LICENCA = "licenca"
MOTIVO_DOMINIO = "dominio_estreito"
MOTIVO_ESCALA = "n_queries"


@dataclass(frozen=True)
class Artefato:
    id: str
    n_passagens: int
    n_queries: int
    nativo: bool
    licenca_aberta: bool
    papel: str
    motivo_se_fora: str = ""
    hf: str = ""


# Frozen on purpose: the gate must not download to learn sizes. Sources in
# docs/alarme-externo.md. If a count changes, this map is what the test sees.
ARTEFATOS: dict[str, Artefato] = {
    "quati-50k": Artefato(
        id="quati-50k",
        n_passagens=50_000,
        n_queries=50,
        nativo=True,
        licenca_aberta=True,
        papel="alarme",
        hf="unicamp-dl/quati",
    ),
    "quati-1m": Artefato(
        id="quati-1m",
        n_passagens=1_000_000,
        n_queries=50,
        nativo=True,
        licenca_aberta=True,
        papel="fora",
        motivo_se_fora=MOTIVO_CUSTO,
        hf="unicamp-dl/quati",
    ),
    "quati-10m": Artefato(
        id="quati-10m",
        n_passagens=10_000_000,
        n_queries=50,
        nativo=True,
        licenca_aberta=True,
        papel="fora",
        motivo_se_fora=MOTIVO_CUSTO,
        hf="unicamp-dl/quati",
    ),
    "mmarco-pt": Artefato(
        id="mmarco-pt",
        n_passagens=8_841_823,
        n_queries=6_980,
        nativo=False,
        licenca_aberta=False,
        papel="fora",
        motivo_se_fora=MOTIVO_TRADUCAO,
        hf="unicamp-dl/mmarco",
    ),
    "pira-2": Artefato(
        id="pira-2",
        n_passagens=4_074,
        n_queries=2_258,
        nativo=True,
        licenca_aberta=True,
        papel="canario",
        hf="paulopirozelli/pira",
    ),
    "juristcu": Artefato(
        id="juristcu",
        n_passagens=16_045,
        n_queries=150,
        nativo=True,
        licenca_aberta=True,
        papel="fora",
        motivo_se_fora=MOTIVO_DOMINIO,
        hf="LeandroRibeiro/JurisTCU",
    ),
    "miracl-pt": Artefato(
        id="miracl-pt",
        n_passagens=1_000_000,
        n_queries=0,
        nativo=False,
        licenca_aberta=True,
        papel="fora",
        motivo_se_fora=MOTIVO_LINGUA,
        hf="miracl/miracl",
    ),
}


@dataclass(frozen=True)
class Veredito:
    artefato: Artefato
    horas: float
    recorte: str
    motivo: str
    baixou: bool = False


def avaliar(artefato: Artefato, *, taxa: float | None = None) -> Veredito:
    """Uma decisão. Língua/tradução/licença antes do custo — igual ao C5.a."""
    taxa = taxa_semente() if taxa is None else taxa
    h = horas(artefato.n_passagens, taxa)

    if artefato.motivo_se_fora == MOTIVO_LINGUA:
        return Veredito(artefato, h, DESCARTAR, MOTIVO_LINGUA)
    if not artefato.nativo:
        return Veredito(artefato, h, DESCARTAR, MOTIVO_TRADUCAO)
    if not artefato.licenca_aberta:
        return Veredito(artefato, h, DESCARTAR, MOTIVO_LICENCA)
    if artefato.papel == "fora":
        motivo = artefato.motivo_se_fora or MOTIVO_DOMINIO
        if motivo == MOTIVO_CUSTO and decidir_custo(h) == ADOTAR:
            motivo = MOTIVO_DOMINIO
        if motivo == MOTIVO_CUSTO:
            return Veredito(artefato, h, DESCARTAR, MOTIVO_CUSTO)
        return Veredito(artefato, h, DESCARTAR, motivo)

    recorte = decidir_custo(h)
    motivo = MOTIVO_CUSTO if recorte == DESCARTAR else MOTIVO_CABE
    return Veredito(artefato, h, recorte, motivo)


def camada_3() -> Veredito:
    return avaliar(ARTEFATOS[CAMADA_3])


def render(vereditos: list[Veredito]) -> str:
    linhas = [
        "# Alarme externo — C5.c",
        "",
        f"Camada 3: **`{CAMADA_3}`**. Canário cross-lingual: **`{CANARIO_CROSSLINGUAL}`**.",
        "Baixou dataset: **não**. Índice: diretório descartável, nunca `[[base]]`.",
        "",
        "| Artefato | Passagens | Queries | h / modelo | Papel | Veredito | Motivo |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for v in vereditos:
        a = v.artefato
        h = f"{v.horas:,.1f} h".replace(",", " ").replace(".", ",")
        n = f"{a.n_passagens:,}".replace(",", " ")
        q = f"{a.n_queries:,}".replace(",", " ")
        linhas.append(
            f"| `{a.id}` | {n} | {q} | {h} | {a.papel} | **{v.recorte}** | `{v.motivo}` |"
        )
    linhas += [
        "",
        "mMARCO-pt fica fora: tradução, licença de pesquisa não comercial da MS MARCO,",
        "e o e5 já treinou na família — o alarme não dispararia.",
        "Quati-1M/10M ficam fora pela porta de 12 h. JurisTCU é domínio estreito,",
        "pacote à parte se um dia for alarme jurídico.",
    ]
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C5.c — sucessor do MIRACL, sem download")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    vereditos = [avaliar(a) for a in ARTEFATOS.values()]
    texto = render(vereditos)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(texto, encoding="utf-8")
    else:
        print(texto, end="")
    escolhido = camada_3()
    return 0 if escolhido.recorte == ADOTAR else 1


if __name__ == "__main__":
    raise SystemExit(main())
