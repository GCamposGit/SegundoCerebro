"""Compara duas configurações pergunta a pergunta — a porta 5 da F1.

    py -m eval.comparar --antes baseline --depois hibrido --out docs/regressao-f1.md

A porta 5 do ROADMAP é **orçamento de regressão**, não regressão zero: "nenhuma
regressão em caso crítico, no máximo 3 perguntas caindo do 1º lugar, e cada uma
inspecionada individualmente". Isso não é avaliável a partir de duas médias — é
preciso saber *quais* perguntas se moveram e para onde.

O motivo de a porta ser assim, e não "zero regressão": uma mudança que melhora
trinta perguntas e piora uma seria reprovada, o que é o trade-off errado. Mas o
oposto — olhar só a média — deixa passar a mudança que sobe 0,02 no agregado
escondendo que a pergunta mais difícil do conjunto deixou de ser respondida.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from segundocerebro.census import load_config
from segundocerebro.index.embeddings import MODELO_PADRAO
from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import CANDIDATOS

from .harness import Resultado, ResultadoPergunta, avaliar, carregar_perguntas

log = get_logger("eval.comparar")

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"

MAX_QUEDAS_DO_PRIMEIRO = 3
"""Orçamento da porta 5. Acima disso a mudança não entra sem justificativa caso a caso."""


@dataclass(frozen=True)
class Movimento:
    id: str
    tipo: str
    pergunta: str
    armadilha: bool
    autoria: str
    antes: int | None
    """Posição do primeiro acerto, ou None se não achou em nenhuma posição."""
    depois: int | None

    @property
    def delta(self) -> str:
        def rot(p: int | None) -> str:
            return str(p) if p else "—"

        return f"{rot(self.antes)} → {rot(self.depois)}"

    @property
    def melhorou(self) -> bool:
        return _rank(self.depois) < _rank(self.antes)

    @property
    def piorou(self) -> bool:
        return _rank(self.depois) > _rank(self.antes)

    @property
    def caiu_do_primeiro(self) -> bool:
        return self.antes == 1 and self.depois != 1

    @property
    def perdeu_de_vez(self) -> bool:
        """Estava em alguma posição e sumiu do ranking inteiro."""
        return self.antes is not None and self.depois is None


def _rank(posicao: int | None) -> float:
    """Sem acerto vale infinito, para comparar sem tratar None caso a caso."""
    return float("inf") if posicao is None else float(posicao)


def comparar(antes: Resultado, depois: Resultado) -> list[Movimento]:
    por_id: dict[str, ResultadoPergunta] = {i.pergunta.id: i for i in antes.itens}
    movimentos: list[Movimento] = []
    for d in depois.itens:
        a = por_id.get(d.pergunta.id)
        if a is None:
            continue
        movimentos.append(
            Movimento(
                id=d.pergunta.id,
                tipo=d.pergunta.tipo,
                pergunta=d.pergunta.pergunta,
                armadilha=d.pergunta.armadilha,
                autoria=d.pergunta.autoria,
                antes=a.posicao_primeiro_acerto,
                depois=d.posicao_primeiro_acerto,
            )
        )
    return movimentos


def render(movimentos: list[Movimento], nome_antes: str, nome_depois: str, contexto: str) -> str:
    pioraram = [m for m in movimentos if m.piorou]
    melhoraram = [m for m in movimentos if m.melhorou]
    quedas = [m for m in movimentos if m.caiu_do_primeiro]
    perdidas = [m for m in movimentos if m.perdeu_de_vez]
    criticas = [m for m in pioraram if m.armadilha]

    passou = not criticas and len(quedas) <= MAX_QUEDAS_DO_PRIMEIRO

    linhas = [
        "# Regressão pergunta a pergunta — porta 5 da F1",
        "",
        contexto,
        "",
        f"- **antes:** {nome_antes}",
        f"- **depois:** {nome_depois}",
        f"- posição do primeiro acerto; `—` significa não achado em nenhuma posição",
        "",
        "## Veredito",
        "",
        f"| Critério | Limite | Medido | |",
        "|---|---:|---:|:--:|",
        f"| regressão em caso-armadilha | 0 | {len(criticas)} | {'✅' if not criticas else '❌'} |",
        f"| perguntas caindo do 1º lugar | {MAX_QUEDAS_DO_PRIMEIRO} | {len(quedas)} "
        f"| {'✅' if len(quedas) <= MAX_QUEDAS_DO_PRIMEIRO else '❌'} |",
        f"| perguntas que sumiram do ranking | — | {len(perdidas)} | |",
        "",
        f"**Porta 5: {'passa' if passou else 'não passa'}.** "
        f"{len(melhoraram)} perguntas melhoraram, {len(pioraram)} pioraram, "
        f"{len(movimentos) - len(melhoraram) - len(pioraram)} ficaram iguais.",
        "",
    ]

    for titulo, grupo, vazio in (
        ("Pioraram", sorted(pioraram, key=lambda m: (-_rank(m.depois), m.id)), "Nenhuma."),
        ("Melhoraram", sorted(melhoraram, key=lambda m: (_rank(m.depois), m.id)), "Nenhuma."),
    ):
        linhas.append(f"## {titulo} — {len(grupo)}")
        linhas.append("")
        if not grupo:
            linhas.append(vazio)
            linhas.append("")
            continue
        linhas.append("| id | tipo | posição | marcas | pergunta |")
        linhas.append("|---|---|---:|---|---|")
        for m in grupo:
            marcas = " ".join(
                x
                for x in (
                    "**armadilha**" if m.armadilha else "",
                    "usuário" if m.autoria == "usuario" else "",
                    "sumiu" if m.perdeu_de_vez else "",
                )
                if x
            )
            linhas.append(f"| {m.id} | {m.tipo} | {m.delta} | {marcas} | {m.pergunta} |")
        linhas.append("")

    return "\n".join(linhas)


def _montar(nome: str, args, cfg):  # noqa: ANN001
    """Um recuperador a partir do nome curto usado na linha de comando."""
    from .rodar import _montar as montar_rodar

    class Args:
        retriever = nome
        prefixo = args.prefixo
        indice = args.indice
        modelo = args.modelo
        threads = args.threads
        candidatos = args.candidatos
        sem_nome = False
        peso_denso = args.peso_denso
        peso_nome = args.peso_nome

    return montar_rodar(Args(), cfg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.comparar", description="Compara duas configurações")
    parser.add_argument("--antes", default="baseline", choices=("baseline", "hibrido", "denso", "bm25"))
    parser.add_argument("--depois", default="hibrido", choices=("baseline", "hibrido", "denso", "bm25"))
    parser.add_argument("--config", type=Path, default=REPO / "census.toml")
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--indice", type=Path, default=REPO / "index")
    parser.add_argument("--modelo", default=MODELO_PADRAO)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--candidatos", type=int, default=CANDIDATOS)
    parser.add_argument("--peso-denso", type=float, default=None)
    parser.add_argument("--peso-nome", type=float, default=None)
    parser.add_argument(
        "--prefixo",
        help="recorta o baseline para a mesma subárvore do índice — obrigatório para "
        "comparar contra baseline sem misturar escala com qualidade",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    from segundocerebro.retrieve.hybrid import PESO_DENSO, PESO_NOME

    if args.peso_denso is None:
        args.peso_denso = PESO_DENSO
    if args.peso_nome is None:
        args.peso_nome = PESO_NOME

    if not args.config.exists():
        log.error("configuração não encontrada: %s", args.config)
        return 2

    cfg = load_config(args.config)
    perguntas = [p for p in carregar_perguntas(args.golden) if p.no_escopo]
    log.info("%d perguntas no escopo", len(perguntas))

    resultados = {}
    contexto_partes = []
    for papel, nome in (("antes", args.antes), ("depois", args.depois)):
        retriever, _, contexto, store, _ = _montar(nome, args, cfg)
        try:
            resultados[papel] = avaliar(retriever, perguntas)
        finally:
            if store is not None:
                store.fechar()
        log.info("%s: %s", papel, retriever.nome)
        contexto_partes.append(f"**{papel}** — {contexto.splitlines()[0]}")

    movimentos = comparar(resultados["antes"], resultados["depois"])
    relatorio = render(
        movimentos,
        resultados["antes"].retriever,
        resultados["depois"].retriever,
        f"{len(perguntas)} perguntas no escopo.\n\n" + "\n\n".join(contexto_partes),
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(relatorio, encoding="utf-8")
        log.info("relatório gravado em %s", args.out)
    else:
        sys.stdout.write(relatorio + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
