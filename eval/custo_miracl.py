"""Porta de custo do MIRACL — C5.a.

O dossiê manda um smoke de throughput **antes** de baixar qualquer coisa, e a
regra é binária: custo por modelo acima de ~12 h (uma noite) ⇒ o MIRACL sai da
ablacão, com a decisão registrada. Este módulo é essa porta.

Três coisas que a porta tem de pegar sozinha, e que baixar o dataset não pegaria:

1. **A língua tem de existir no dataset publicado.** MIRACL-PT é o recorte que o
   C5 nomeia. O corpus publicado (Zhang et al., TACL 2023, tabela 2) tem 18
   línguas e **não tem `pt`**. Descobrir isso depois de 16 GB de dump é o modo de
   falha que esta porta existe para impedir.
2. **A taxa é desta máquina, não do `ModelSpec`.** `chunks_por_segundo = 0,63` é
   o i7-1355U. Extrapolá-lo para as 980 Ti é o número que o dossiê já fez, e deu
   ~19 dias — proibitivo no notebook, não medido no desktop. A semente GPU
   versionada aqui veio de um run real neste desktop; o smoke (`--medir`) a
   substitui quando a GPU está ociosa.
3. **Não compete com indexação viva.** C5.a, item (2): nunca no CI, nunca contra
   o acervo real em curso. A trava do índice recusa o smoke; a semente não
   carrega encoder e por isso pode rodar com a passada no fundo.

Nada aqui vira `[[base]]` (invariante 7). Nada aqui baixa o HuggingFace. O
vocabulário das passagens sintéticas é o da VCE.
"""

from __future__ import annotations

import argparse
import os
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.logger import get_logger

log = get_logger("eval.custo_miracl")

REPO = Path(__file__).resolve().parent.parent

# Zhang et al., TACL 2023, Table 2; counts mirrored in
# https://github.com/project-miracl/miracl (corpora README). The two surprise
# languages (de, yo) are in the same table. Portuguese is not.
#
# Frozen on purpose: the gate must not download the dataset to learn the
# language list. If MIRACL ever publishes `pt`, this map is what changes, and
# the test that asserts `"pt" not in CORPUS_MIRACL` is what reopens C5.a.
CORPUS_MIRACL: dict[str, int] = {
    "ar": 2_061_414,
    "bn": 297_265,
    "en": 32_893_221,
    "es": 10_373_953,
    "fa": 2_207_172,
    "fi": 1_883_509,
    "fr": 14_636_953,
    "hi": 506_264,
    "id": 1_446_315,
    "ja": 6_953_614,
    "ko": 1_486_752,
    "ru": 9_543_918,
    "sw": 131_924,
    "te": 518_079,
    "th": 542_166,
    "zh": 4_934_368,
    "de": 15_866_222,
    "yo": 49_043,
}

LINGUA_ALVO = "pt"
"""O recorte que o C5 nomeia. Não está em `CORPUS_MIRACL`."""

N_COMPLETO = 1_000_000
"""Tamanho de planejamento do dossiê para MIRACL-PT, não uma contagem.

O dossiê arredonda «≈ 1M passagens». Sem split PT não há o que contar; este
número permanece como o *equivalente* contra o qual a porta de 12 h se aplica
a qualquer corpus PT futuro da mesma ordem (Wikipedia fatiada, mMARCO, …)."""

N_AMOSTRADO = 100_000
"""Fatia C5.a: queries dev + positivos dos qrels + ~100k distratoras."""

PORTA_HORAS = 12.0
"""Uma noite. `>` descarta; exatamente 12 h ainda cabe — a regra do dossiê é
estrita para o lado de cima, não para o empate na porta."""

N_MODELOS = 3
"""Candidatos de R3.1: o dossiê multiplica o custo por este fator. A porta é
*por modelo*; a linha ×3 é só para não surpreender quem for agendar a noite."""

# docs/estimativa-de-indexacao.md, semente GPU de 19/08/2026.
# Base empresas, e5-large, *uma* 980 Ti, parse em threads: 7.873 chunks em
# 637 s ativos. Inclui parse de Office — para Wikipedia já fatiada o encoder
# é o custo quase inteiro, então esta taxa é um **teto** de horas (a passada
# real de embed-only seria pelo menos tão rápida). Não dobra pelas duas
# placas: aquele run usou uma.
SEMENTE_GPU_CHUNKS = 7873
SEMENTE_GPU_SEGUNDOS = 637
ORIGEM_SEMENTE = "semente-gpu-2026-08-19"

ADOTAR = "adotar"
DESCARTAR = "descartar"
MOTIVO_LINGUA = "lingua_ausente"
MOTIVO_CUSTO = "custo"
MOTIVO_CABE = "cabe"

# ~65 whitespace tokens, in the MIRACL average-passage band (54–77 in Table 2
# for whitespace-delimited languages). VCE vocabulary only.
_PALAVRAS_VCE = (
    "A", "política", "vigente", "de", "inteligência", "artificial", "da",
    "Várzea", "Clara", "Energia", "foi", "revisada", "por", "GC", "em",
    "março", "de", "2026", "e", "substitui", "a", "minuta", "interna",
    "O", "contrato", "CT-VCE-2024-0142", "cobre", "licenciamento",
    "ambiental", "da", "faixa", "norte", "do", "reservatório", "Lagoa",
    "Norte", "sem", "mencionar", "software", "A", "ata", "de",
    "doze", "de", "março", "registra", "a", "troca", "de", "escopo",
    "do", "projeto", "e", "pede", "a", "política", "como", "anexo",
    "A", "proposta", "Aurora", "Técnica", "implanta", "o", "copiloto",
    "de", "contratos", "em", "noventa", "dias", "no", "mesmo", "edital",
    "que", "a", "Boreal", "Serviços", "descreve", "como", "gerativa",
)


def lingua_no_miracl(lingua: str) -> bool:
    """A língua tem split publicado? Sem download, contra a tabela congelada."""
    return lingua.strip().lower() in CORPUS_MIRACL


def taxa_semente() -> float:
    """chunks/s da semente GPU de 19/08/2026. Uma placa, e5-large."""
    return SEMENTE_GPU_CHUNKS / SEMENTE_GPU_SEGUNDOS


def horas(n_passagens: int, chunks_por_segundo: float) -> float:
    if chunks_por_segundo <= 0:
        raise ValueError("taxa tem de ser positiva — zero faria a porta parecer infinita")
    if n_passagens < 0:
        raise ValueError("número de passagens não pode ser negativo")
    return n_passagens / chunks_por_segundo / 3600.0


def decidir_custo(horas_por_modelo: float, *, porta: float = PORTA_HORAS) -> str:
    """`>` descarta. Empate na porta adota — a regra do dossiê é o lado de cima."""
    if horas_por_modelo > porta:
        return DESCARTAR
    return ADOTAR


@dataclass(frozen=True)
class Porta:
    """O que a porta viu, e o que ela decidiu — para o relatório não mentir."""

    lingua: str
    lingua_existe: bool
    taxa: float
    origem_taxa: str
    n_completo: int
    n_amostrado: int
    n_modelos: int
    porta_horas: float
    horas_completo: float
    horas_amostrado: float
    recorte_completo: str
    recorte_amostrado: str
    motivo_completo: str
    motivo_amostrado: str
    sai_da_ablacao: bool
    baixou: bool = False
    maquina: str = ""

    @property
    def horas_completo_n_modelos(self) -> float:
        return self.horas_completo * self.n_modelos

    @property
    def horas_amostrado_n_modelos(self) -> float:
        return self.horas_amostrado * self.n_modelos


def avaliar_porta(
    *,
    lingua: str = LINGUA_ALVO,
    taxa: float,
    origem_taxa: str,
    n_completo: int = N_COMPLETO,
    n_amostrado: int = N_AMOSTRADO,
    n_modelos: int = N_MODELOS,
    porta_horas: float = PORTA_HORAS,
    maquina: str = "",
) -> Porta:
    """Uma decisão por recorte. Língua ausente descarta os dois, antes do custo.

    A conta de horas roda mesmo assim: é o que o próximo corpus PT da mesma
    ordem vai encontrar, e escondê-la faria a porta de 12 h parecer não ter
    sido aplicada.
    """
    lingua = lingua.strip().lower()
    existe = lingua_no_miracl(lingua)
    h_completo = horas(n_completo, taxa)
    h_amostrado = horas(n_amostrado, taxa)

    if not existe:
        rec_c = rec_a = DESCARTAR
        motivo_c = motivo_a = MOTIVO_LINGUA
        sai = True
    else:
        rec_c = decidir_custo(h_completo, porta=porta_horas)
        rec_a = decidir_custo(h_amostrado, porta=porta_horas)
        motivo_c = MOTIVO_CUSTO if rec_c == DESCARTAR else MOTIVO_CABE
        motivo_a = MOTIVO_CUSTO if rec_a == DESCARTAR else MOTIVO_CABE
        sai = rec_c == DESCARTAR and rec_a == DESCARTAR

    return Porta(
        lingua=lingua,
        lingua_existe=existe,
        taxa=taxa,
        origem_taxa=origem_taxa,
        n_completo=n_completo,
        n_amostrado=n_amostrado,
        n_modelos=n_modelos,
        porta_horas=porta_horas,
        horas_completo=h_completo,
        horas_amostrado=h_amostrado,
        recorte_completo=rec_c,
        recorte_amostrado=rec_a,
        motivo_completo=motivo_c,
        motivo_amostrado=motivo_a,
        sai_da_ablacao=sai,
        baixou=False,
        maquina=maquina,
    )


def passagens_sinteticas(n: int, *, seed: int = 42, palavras: int = 65) -> list[str]:
    """Passagens determinísticas no comprimento médio do MIRACL. Vocabulário VCE."""
    if n < 0:
        raise ValueError("n não pode ser negativo")
    rng = random.Random(seed)
    pool = list(_PALAVRAS_VCE)
    saida: list[str] = []
    for i in range(n):
        rng.shuffle(pool)
        # The index keeps two calls with the same seed from collapsing: the
        # encoder would otherwise see n copies of one string and the rate
        # would describe cache behaviour, not throughput.
        saida.append(" ".join(pool[:palavras]) + f" [{i}]")
    return saida


def medir_throughput(
    embedder: object,
    *,
    n: int = 64,
    aquecimento: int = 8,
    batch_size: int = 32,
) -> float:
    """chunks/s do encoder, em passagens sintéticas. Não grava índice.

    O aquecimento é descartado: a primeira chamada carrega o ONNX e, no
    `e5-large`, isso leva dezenas de segundos que não descrevem a passada.
    """
    if n <= 0:
        raise ValueError("n do smoke tem de ser positivo")
    embed = getattr(embedder, "embed_passagens")
    textos = passagens_sinteticas(n + aquecimento)
    if aquecimento:
        embed(textos[:aquecimento], batch_size=batch_size)
    alvo = textos[aquecimento:]
    comecou = time.perf_counter()
    vetores = embed(alvo, batch_size=batch_size)
    dt = time.perf_counter() - comecou
    if dt <= 0:
        raise RuntimeError("smoke devolveu duração zero — o relógio não mediu nada")
    if len(vetores) != len(alvo):
        raise RuntimeError(
            f"encoder devolveu {len(vetores)} vetores para {len(alvo)} passagens"
        )
    return len(alvo) / dt


def conferir_indexacao(diretorios: Sequence[Path]) -> None:
    """Recusa o smoke se algum índice desta máquina está sendo escrito.

    Importa `store` aqui, não no topo: o módulo da porta tem de importar na
    suíte padrão sem puxar LanceDB além do que o `store` já puxa no eval, e
    principalmente sem puxar o encoder.
    """
    from segundocerebro.index.store import IndiceEmEscrita, indexacao_viva

    vivos = [Path(d) for d in diretorios if indexacao_viva(Path(d))]
    if not vivos:
        return
    raise IndiceEmEscrita(
        "indexação viva em "
        + ", ".join(str(d) for d in vivos)
        + " — o smoke do C5.a não compete com o acervo real. "
        "Rode `py -m eval.custo_miracl` (semente, sem GPU) ou espere a trava."
    )


def indices_das_bases(config: Path) -> list[Path]:
    """Índices declarados no config local. Caminhos não saem deste processo."""
    from segundocerebro.config import carregar

    conf = carregar(config, raiz=config.parent)
    return [Path(b.indice) for b in conf.bases]


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _fmt_horas(h: float) -> str:
    """`22,5 h` ou `18,4 d`. Vírgula, porque `22.5 h` lê-se as duas coisas."""
    if h >= 24:
        return f"{h / 24:,.1f} d".replace(",", " ").replace(".", ",")
    return f"{h:,.1f} h".replace(",", " ").replace(".", ",")


def _fmt_taxa(t: float) -> str:
    return f"{t:,.2f}".replace(",", " ").replace(".", ",")


def render(porta: Porta) -> str:
    """Relatório em português. O que a porta decidiu, e o que ela não fez."""
    existe = "sim" if porta.lingua_existe else "**não**"
    n_linguas = len(CORPUS_MIRACL)
    linhas = [
        "# Porta de custo do MIRACL — C5.a",
        "",
        f"Língua alvo: `{porta.lingua}`. Existe no corpus publicado ({n_linguas} línguas): {existe}.",
        f"Taxa: **{_fmt_taxa(porta.taxa)} chunks/s** ({porta.origem_taxa}"
        + (f", máquina `{porta.maquina}`" if porta.maquina else "")
        + ").",
        f"Porta: **{porta.porta_horas:.0f} h** por modelo. Baixou o MIRACL: "
        f"{'sim' if porta.baixou else '**não**'}.",
        "",
        "| Recorte | Passagens | h / modelo | ×"
        f"{porta.n_modelos} modelos | Veredito | Motivo |",
        "|---|---:|---:|---:|---|---|",
        (
            f"| completo | {_fmt_int(porta.n_completo)} | {_fmt_horas(porta.horas_completo)} | "
            f"{_fmt_horas(porta.horas_completo_n_modelos)} | "
            f"**{porta.recorte_completo}** | `{porta.motivo_completo}` |"
        ),
        (
            f"| amostrado | {_fmt_int(porta.n_amostrado)} | {_fmt_horas(porta.horas_amostrado)} | "
            f"{_fmt_horas(porta.horas_amostrado_n_modelos)} | "
            f"**{porta.recorte_amostrado}** | `{porta.motivo_amostrado}` |"
        ),
        "",
    ]
    if porta.sai_da_ablacao:
        linhas += [
            "**MIRACL sai da ablação.** A camada 3 (alarme anti-endogamia) precisa",
            "de outro artefato — esta porta não escolhe qual.",
            "",
        ]
    else:
        linhas += [
            "MIRACL **não** sai da ablação por esta porta: pelo menos um recorte cabe.",
            "Continua alarme, nunca decisão (E3). Índice em diretório descartável,",
            "nunca `[[base]]`.",
            "",
        ]
    if not porta.lingua_existe:
        linhas += [
            f"A conta de horas acima é o equivalente de {_fmt_int(porta.n_completo)} passagens",
            "num corpus PT da mesma ordem — não um split do MIRACL, que não tem",
            f"`{porta.lingua}`. Serve para o próximo candidato bater na mesma porta.",
            "",
        ]
    linhas += [
        "Nada disto criou `[[base]]`, nada disto gravou vetor, nada disto baixou",
        "dataset. O smoke (`--medir`) recusa se houver `indexacao.lock` vivo.",
    ]
    return "\n".join(linhas) + "\n"


def _resolver_indices(args: argparse.Namespace) -> list[Path]:
    if args.indice:
        return [Path(p) for p in args.indice]
    config = args.config
    if config is None:
        candidato = Path("config.toml")
        config = candidato if candidato.is_file() else None
    if config is None:
        return []
    return indices_das_bases(Path(config))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Porta de custo do MIRACL (C5.a). Sem --medir usa a semente GPU "
            "e não carrega encoder — pode rodar com a indexação no fundo."
        )
    )
    parser.add_argument("--lingua", default=LINGUA_ALVO)
    parser.add_argument("--medir", action="store_true", help="smoke real; recusa com trava viva")
    parser.add_argument("--n", type=int, default=64, help="passagens do smoke, depois do aquecimento")
    parser.add_argument("--modelo", default="e5-large")
    parser.add_argument("--config", type=Path, help="para achar os índices e recusar trava viva")
    parser.add_argument(
        "--indice",
        action="append",
        default=[],
        help="diretório de índice a conferir (repetível); substitui --config",
    )
    parser.add_argument("--maquina", default="")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.medir:
        from segundocerebro.index.store import IndiceEmEscrita

        diretorios = _resolver_indices(args)
        if not diretorios:
            log.error(
                "--medir recusa sem --config/--indice: não dá para saber se a "
                "indexação está viva, e o C5.a não compete com ela no escuro"
            )
            return 2
        try:
            conferir_indexacao(diretorios)
        except IndiceEmEscrita as erro:
            log.error("%s", erro)
            return 4

        from segundocerebro.index.embeddings import Embedder

        embedder = Embedder(args.modelo, threads=os.cpu_count() or 4, lazy=True)
        taxa = medir_throughput(embedder, n=args.n)
        origem = "smoke"
        log.info("smoke: %.2f chunks/s em %d passagens sintéticas", taxa, args.n)
    else:
        taxa = taxa_semente()
        origem = ORIGEM_SEMENTE
        log.info(
            "semente GPU %s: %.2f chunks/s (não carregou encoder)",
            ORIGEM_SEMENTE,
            taxa,
        )

    porta = avaliar_porta(
        lingua=args.lingua,
        taxa=taxa,
        origem_taxa=origem,
        maquina=args.maquina,
    )
    relatorio = render(porta)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(relatorio, encoding="utf-8")
        log.info("relatório gravado em %s", args.out)
    else:
        print(relatorio, end="")

    if porta.sai_da_ablacao:
        log.info("veredito: MIRACL sai da ablação (%s/%s)", porta.motivo_completo, porta.motivo_amostrado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
