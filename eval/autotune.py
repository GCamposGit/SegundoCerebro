"""Auto-tuning de pesos de fusão por acervo (R6.1).

    py -m eval.autotune --base padrao
    py -m eval.autotune --base padrao --gravar --out docs/autotune-padrao.md

A regra de ouro (docs/regra-de-ouro.md): o sistema é para um leigo, na máquina dele,
apontando uma pasta que nunca vimos. Pesos globais fixos (1.0/0.25/0.5) nasceram do
acervo corporativo dev. Este pipeline trata esses valores como prior de fábrica e
calibra pesos por base a partir de perguntas amostradas do próprio acervo indexado.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import random
import re
from typing import Any

from segundocerebro.config import BASE_UNICA, Base, Config, Pesos, carregar
from segundocerebro.config_escrita import gravar as gravar_config
from segundocerebro.index.embeddings import Embedder, MODELO_PADRAO, MODELOS
from segundocerebro.index.store import Store
from segundocerebro.logger import get_logger
from segundocerebro.retrieve.hybrid import BuscaHibrida, K_RRF, rrf
from segundocerebro.retrieve.identificadores import extrair as extrair_ids

from .harness import Pergunta, carregar_perguntas

log = get_logger("eval.autotune")

PRIOR_DENSO = 1.0
PRIOR_LEXICAL = 0.25
PRIOR_NOME = 0.5
PESOS_CANONICOS = (0.0, 0.25, 0.5, 1.0)


def grade_rrf() -> list[tuple[float, float, float]]:
    """Triplos (denso, lexical, nome) canônicos: um representante por classe (max=1.0)."""
    return [
        (d, l, n)
        for d in PESOS_CANONICOS
        for l in PESOS_CANONICOS
        for n in PESOS_CANONICOS
        if max(d, l, n) == 1.0
    ]


@dataclass(frozen=True)
class PontoGrade:
    denso: float
    lexical: float
    nome: float
    mrr: float
    recall1: float


@dataclass(frozen=True)
class ResultadoAutotune:
    base_id: str
    pesos: Pesos
    prior: Pesos
    mrr_prior: float
    mrr_escolhido: float
    n_perguntas: int
    motivo: str
    grade: list[PontoGrade]
    ajustado: bool


def _limpar_nome(stem: str) -> str:
    s = re.sub(r"[_\-.]+", " ", stem)
    s = re.sub(r"\b(v\d+|final|\d{4}-\d{2}-\d{2})\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _extrair_frase_de_chunk(texto: str) -> str:
    linhas = [li.strip() for li in texto.splitlines() if len(li.strip()) > 30]
    candidato = re.sub(r"^#+\s*", "", linhas[0] if linhas else texto.strip())
    return candidato[:117] + "..." if len(candidato) > 120 else candidato


def amostrar_perguntas(store: Store, n_total: int = 60, semente: int = 42) -> list[Pergunta]:
    """Amostra ~N perguntas balanceadas diretamente do SQLite da base."""
    rng = random.Random(semente)
    docs_cursor = store.con.execute("SELECT path FROM documentos WHERE status = 'ok' ORDER BY path")
    todos_paths = [r[0] for r in docs_cursor.fetchall()]
    if not todos_paths:
        raise ValueError("Nenhum documento com status='ok' no índice.")

    cota_cada = max(1, n_total // 3)
    perguntas: list[Pergunta] = []
    vistos: set[str] = set()

    for gerador, args in (
        (_amostrar_identificadores, (store, todos_paths, cota_cada, rng)),
        (_amostrar_nomes, (todos_paths, cota_cada, rng)),
        (_amostrar_conteudos, (store, todos_paths, max(0, n_total - len(perguntas)), rng)),
    ):
        for p in gerador(*args):
            if p.pergunta not in vistos:
                vistos.add(p.pergunta)
                perguntas.append(p)
    return perguntas[:n_total]


def _amostrar_identificadores(
    store: Store, paths: list[str], cota: int, rng: random.Random
) -> list[Pergunta]:
    saida: list[Pergunta] = []
    shuffled = list(paths)
    rng.shuffle(shuffled)
    for p in shuffled:
        if len(saida) >= cota:
            break
        for c in store.chunks_de(p):
            for ident in extrair_ids(c.texto):
                saida.append(
                    Pergunta(
                        id=f"auto-id-{len(saida)+1:03d}",
                        tipo="exato",
                        pergunta=f"Documento referente a {ident.tipo} {ident.valor}",
                        fontes=(p,),
                        armadilha_fatia="identificador",
                        autoria="autotune",
                    )
                )
                if len(saida) >= cota:
                    break
            if len(saida) >= cota:
                break
    return saida


def _amostrar_nomes(paths: list[str], cota: int, rng: random.Random) -> list[Pergunta]:
    saida: list[Pergunta] = []
    shuffled = list(paths)
    rng.shuffle(shuffled)
    for p in shuffled:
        if len(saida) >= cota:
            break
        limpo = _limpar_nome(Path(p).stem)
        if len(limpo) >= 4 and not limpo.isdigit():
            saida.append(
                Pergunta(
                    id=f"auto-nome-{len(saida)+1:03d}",
                    tipo="exato",
                    pergunta=f"Documento {limpo}",
                    fontes=(p,),
                    armadilha_fatia="nome",
                    autoria="autotune",
                )
            )
    return saida


def _amostrar_conteudos(
    store: Store, paths: list[str], cota: int, rng: random.Random
) -> list[Pergunta]:
    saida: list[Pergunta] = []
    shuffled = list(paths)
    rng.shuffle(shuffled)
    for p in shuffled:
        if len(saida) >= cota:
            break
        chunks = store.chunks_de(p)
        if not chunks:
            continue
        c = rng.choice(chunks)
        frase = _extrair_frase_de_chunk(c.texto)
        if len(frase) >= 20:
            saida.append(
                Pergunta(
                    id=f"auto-sem-{len(saida)+1:03d}",
                    tipo="semantica",
                    pergunta=f"Trecho sobre {frase}",
                    fontes=(p,),
                    armadilha_fatia="conteudo",
                    autoria="autotune",
                )
            )
    return saida


@dataclass(frozen=True)
class CandidatosPergunta:
    pergunta: Pergunta
    denso_docs: list[str]
    lexical_docs: list[str]
    nome_scores: dict[str, float]


def _preparar_candidatos(
    base: Base,
    store: Store,
    embedder: Embedder,
    perguntas: list[Pergunta],
    candidatos_n: int = 100,
) -> list[CandidatosPergunta]:
    busca = BuscaHibrida.de_base(store, embedder, base)
    saida: list[CandidatosPergunta] = []
    for perg in perguntas:
        consulta = perg.pergunta
        vetor = embedder.embed_consulta(consulta)
        denso_acertos = store.buscar_denso(vetor, candidatos_n, model_id=embedder.model_id)
        denso_cids = [a.id for a in denso_acertos]
        chunks_denso_armazenados = store.chunks_por_id(denso_cids)
        denso_docs = _extrair_docs_distintos(denso_cids, chunks_denso_armazenados)

        lex_acertos = store.buscar_lexical(
            busca.glossario.expandir(consulta), candidatos_n, pesos_colunas=base.pesos.colunas_fts
        )
        lex_cids = [a.id for a in lex_acertos]
        chunks_lex_armazenados = store.chunks_por_id(lex_cids)
        lexical_docs = _extrair_docs_distintos(lex_cids, chunks_lex_armazenados)

        nome_scores = {
            rel: 1.0 / (K_RRF + pos)
            for pos, (rel, _) in enumerate(busca.ranqueador_nome.ranquear(consulta, candidatos_n), start=1)
        }
        saida.append(CandidatosPergunta(perg, denso_docs, lexical_docs, nome_scores))
    return saida


def _extrair_docs_distintos(cids: list[str], armazenados: dict[str, Any]) -> list[str]:
    docs: list[str] = []
    for cid in cids:
        if (arm := armazenados.get(cid)) and arm.path not in docs:
            docs.append(arm.path)
    return docs


def _avaliar_ponto(
    cand_perguntas: list[CandidatosPergunta], denso: float, lexical: float, nome: float, k_max: int = 10
) -> tuple[float, float]:
    rr_total, r1_total = 0.0, 0.0
    for cp in cand_perguntas:
        rankings, pesos = [], []
        if denso:
            rankings.append(cp.denso_docs)
            pesos.append(denso)
        if lexical:
            rankings.append(cp.lexical_docs)
            pesos.append(lexical)

        pontos = rrf(rankings, K_RRF, pesos) if rankings else {}
        if nome:
            for doc, sc in cp.nome_scores.items():
                pontos[doc] = pontos.get(doc, 0.0) + nome * sc

        ordenados = sorted(pontos.items(), key=lambda kv: (-kv[1], kv[0]))
        doc_ids = [doc for doc, _ in ordenados[:k_max]]
        fontes = set(cp.pergunta.fontes)

        rr = 0.0
        for pos, d in enumerate(doc_ids, start=1):
            if d in fontes:
                rr = 1.0 / pos
                break
        rr_total += rr
        if doc_ids and doc_ids[0] in fontes:
            r1_total += 1.0
    n = len(cand_perguntas) or 1
    return rr_total / n, r1_total / n


def autotunar(
    base: Base,
    store: Store,
    embedder: Embedder,
    perguntas: list[Pergunta] | None = None,
    n_perguntas: int = 60,
    semente: int = 42,
    gravar: bool = False,
    caminho_config: Path = Path("config.toml"),
    cfg: Config | None = None,
) -> ResultadoAutotune:
    """Executa a calibração de pesos de fusão com guarda-corpos anti-overfitting."""
    if perguntas is None:
        perguntas = amostrar_perguntas(store, n_perguntas, semente)
    if not perguntas:
        raise ValueError("Nenhuma pergunta disponível para autotune.")

    cands = _preparar_candidatos(base, store, embedder, perguntas)
    mrr_prior, r1_prior = _avaliar_ponto(cands, PRIOR_DENSO, PRIOR_LEXICAL, PRIOR_NOME)
    prior_pesos = Pesos(denso=PRIOR_DENSO, lexical=PRIOR_LEXICAL, nome=PRIOR_NOME)

    grade = [
        PontoGrade(d, l, n, *_avaliar_ponto(cands, d, l, n))
        for d, l, n in grade_rrf()
    ]

    amplitude = max(p.mrr for p in grade) - min(p.mrr for p in grade)
    if amplitude < 0.05 * (mrr_prior or 0.5):
        return _finalizar(base, prior_pesos, prior_pesos, mrr_prior, mrr_prior, len(perguntas),
                          "guarda_corpo_baixa_variacao", grade, False, gravar, caminho_config, cfg)

    melhor = max(
        grade,
        key=lambda p: (
            p.mrr, p.recall1,
            -(abs(p.denso - PRIOR_DENSO) + abs(p.lexical - PRIOR_LEXICAL) + abs(p.nome - PRIOR_NOME)),
        ),
    )

    if melhor.mrr <= mrr_prior + 0.005:
        return _finalizar(base, prior_pesos, prior_pesos, mrr_prior, mrr_prior, len(perguntas),
                          "prior_mantido", grade, False, gravar, caminho_config, cfg)

    vencedor = Pesos(
        denso=melhor.denso,
        lexical=melhor.lexical,
        nome=melhor.nome,
        fts_texto=base.pesos.fts_texto,
        fts_trilha=base.pesos.fts_trilha,
        fts_caminho=base.pesos.fts_caminho,
        ajustado_em=datetime.now(timezone.utc).isoformat(),
        n_perguntas=len(perguntas),
        mrr=round(melhor.mrr, 4),
    )
    return _finalizar(base, vencedor, prior_pesos, mrr_prior, melhor.mrr, len(perguntas),
                      "melhoria_comprovada", grade, True, gravar, caminho_config, cfg)


def _finalizar(
    base: Base,
    pesos: Pesos,
    prior: Pesos,
    mrr_prior: float,
    mrr_escolhido: float,
    n_perguntas: int,
    motivo: str,
    grade: list[PontoGrade],
    ajustado: bool,
    gravar: bool,
    caminho_config: Path,
    cfg: Config | None,
) -> ResultadoAutotune:
    res = ResultadoAutotune(
        base_id=base.id, pesos=pesos, prior=prior, mrr_prior=mrr_prior,
        mrr_escolhido=mrr_escolhido, n_perguntas=n_perguntas, motivo=motivo,
        grade=grade, ajustado=ajustado,
    )
    if gravar and caminho_config.exists():
        if cfg is None:
            cfg = carregar(caminho_config)
        novas = [replace(b, pesos=pesos) if b.id == base.id else b for b in cfg.bases]
        gravar_config(Config(bases=tuple(novas), maquina=cfg.maquina, indexacao=cfg.indexacao), caminho_config)
        log.info("Pesos gravados em %s para base '%s'", caminho_config, base.id)
    return res


def render_relatorio(res: ResultadoAutotune) -> str:
    linhas = [
        f"# Relatório de Autotune (R6.1) — Base `{res.base_id}`",
        "",
        f"- **Data de calibração:** `{res.pesos.ajustado_em or 'não ajustado'}`",
        f"- **Perguntas avaliadas:** {res.n_perguntas}",
        f"- **Veredito:** `{res.motivo}` (Ajustado: {'Sim' if res.ajustado else 'Não — Prior Preservado'})",
        f"- **MRR Prior ({PRIOR_DENSO:g}/{PRIOR_LEXICAL:g}/{PRIOR_NOME:g}):** {res.mrr_prior:.3f}",
        f"- **MRR Final ({res.pesos.denso:g}/{res.pesos.lexical:g}/{res.pesos.nome:g}):** {res.mrr_escolhido:.3f}",
        "",
        "## Grade de Calibração (Top 10)",
        "",
        "| denso | lexical | nome | MRR@10 | recall@1 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for p in sorted(res.grade, key=lambda x: -x.mrr)[:10]:
        m = " **← escolhido**" if (p.denso, p.lexical, p.nome) == (res.pesos.denso, res.pesos.lexical, res.pesos.nome) else ""
        linhas.append(f"| {p.denso:g} | {p.lexical:g} | {p.nome:g} | {p.mrr:.3f} | {p.recall1:.3f} |{m}")
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.autotune", description="Auto-tuning de pesos por base (R6.1)")
    parser.add_argument("--base", default=BASE_UNICA, help="Id da base")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="Caminho do config.toml")
    parser.add_argument("--n-perguntas", type=int, default=60, help="Número de perguntas a amostrar")
    parser.add_argument("--semente", type=int, default=42, help="Semente para amostragem")
    parser.add_argument("--dourado", type=Path, default=None, help="Usar arquivo de perguntas existente")
    parser.add_argument("--gravar", action="store_true", help="Persistir pesos vencedores no config.toml")
    parser.add_argument("--out", type=Path, default=None, help="Caminho do relatório Markdown de saída")
    args = parser.parse_args(argv)

    cfg = carregar(args.config) if args.config.exists() else Config(bases=(Base(id=args.base),))
    base = cfg.base(args.base)
    dim = MODELOS.get(base.modelo, MODELOS[MODELO_PADRAO]).dim
    store = Store(base.indice, dim)
    embedder = Embedder(base.modelo)

    try:
        perguntas = carregar_perguntas(args.dourado) if args.dourado else None
        res = autotunar(
            base=base, store=store, embedder=embedder, perguntas=perguntas,
            n_perguntas=args.n_perguntas, semente=args.semente, gravar=args.gravar,
            caminho_config=args.config, cfg=cfg,
        )
    finally:
        store.fechar()

    print(
        f"Base: {res.base_id} | Ajustado: {res.ajustado} ({res.motivo}) | "
        f"Pesos: d={res.pesos.denso:g} l={res.pesos.lexical:g} n={res.pesos.nome:g} | "
        f"MRR: {res.mrr_escolhido:.3f} (prior: {res.mrr_prior:.3f})"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_relatorio(res), encoding="utf-8")
        print(f"Relatório gravado em {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
