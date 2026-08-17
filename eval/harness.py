"""Evaluation loop over the golden set.

The contract every retriever implements is one method — `search(consulta, k)`.
The F0 baseline, the hybrid search of F1 and the reranked pipeline of F2 all
plug in here, so their numbers land in the same table and stay comparable
across phases. That comparability is the whole point of building this first.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .metrics import MODO_QUALQUER, MODO_TODAS, media, ndcg_at_k, recall_at_k, reciprocal_rank

KS_PADRAO = (1, 3, 5, 10, 20)
K_MRR = 10
K_NDCG = 10


@dataclass(frozen=True)
class Hit:
    """One retrieved document. `path` is relative to the root, with '/'."""

    path: str
    score: float = 0.0
    trecho: str = ""


class Retriever(Protocol):
    nome: str

    def search(self, consulta: str, k: int) -> list[Hit]: ...


MOTIVOS_FORA_DE_ESCOPO = {
    "email": "fonte é email (.msg, ou MIME com extensão trocada) — parser de email é da F4",
    "ocr": "fonte é PDF digitalizado, imagem por página, zero texto extraível — OCR está fora da F1",
}
"""Por que uma pergunta não é mensurável nesta fase.

A anotação é **estática**, no conjunto dourado, e não derivada do estado do
índice. Derivar do índice seria cômodo e errado: um parser que quebrasse
excluiria sozinho as perguntas que passou a errar, e a métrica **subiria** com a
regressão. Aqui a exclusão é uma decisão de escopo, versionada e revisável em
diff; `verificar_escopo()` confere a anotação contra o índice e reclama das duas
divergências possíveis."""


@dataclass(frozen=True)
class Pergunta:
    id: str
    tipo: str
    pergunta: str
    fontes: tuple[str, ...]
    validada: bool = False
    notas: str = ""
    autoria: str = "rascunho"
    armadilha: bool = False
    fora_de_escopo: str = ""
    """Vazio = mensurável nesta fase. Senão, chave de `MOTIVOS_FORA_DE_ESCOPO`."""
    base: str = ""
    """A qual base esta pergunta pertence. Vazio = não declara.

    Isto **não** é a fronteira entre bases — a fronteira é o arquivo, um por base
    (`config.Base.dourado`). O campo existe para pegar o erro que a separação por
    arquivo ainda deixa passar: apontar o conjunto dourado errado. Vazio é
    legítimo e é o caso de hoje, com um acervo só."""

    @property
    def modo(self) -> str:
        """Multi-hop needs every source; anything else needs one of them."""
        return MODO_TODAS if self.tipo == "multihop" else MODO_QUALQUER

    @property
    def no_escopo(self) -> bool:
        return not self.fora_de_escopo


def carregar_perguntas(caminho: Path) -> list[Pergunta]:
    perguntas: list[Pergunta] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        perguntas.append(
            Pergunta(
                id=d["id"],
                tipo=d["tipo"],
                pergunta=d["pergunta"],
                fontes=tuple(d["fontes"]),
                validada=bool(d.get("validada")),
                notas=d.get("notas", ""),
                autoria=d.get("autoria", "rascunho"),
                armadilha=bool(d.get("armadilha")),
                fora_de_escopo=d.get("fora_de_escopo", ""),
                base=d.get("base", ""),
            )
        )
    desconhecidos = {p.fora_de_escopo for p in perguntas if p.fora_de_escopo} - set(MOTIVOS_FORA_DE_ESCOPO)
    if desconhecidos:
        raise ValueError(f"motivo de fora_de_escopo não catalogado: {sorted(desconhecidos)}")
    return perguntas


def conferir_base(perguntas: list[Pergunta], base_id: str) -> None:
    """Recusa medir uma base contra o conjunto dourado de outra.

    A separação é por arquivo, mas apontar o arquivo errado continua possível —
    por `--golden`, por `dourado` mal configurado, por cópia. O sintoma seria um
    relatório com números plausíveis sobre o acervo errado, que é pior que um
    erro: passa despercebido e vira referência.

    Pergunta sem `base` não afirma nada e não impede nada. É o caso do conjunto
    de hoje, escrito quando existia um acervo só.
    """
    alheias = sorted({p.base for p in perguntas if p.base and p.base != base_id})
    if alheias:
        quantas = sum(1 for p in perguntas if p.base in alheias)
        raise ValueError(
            f"o conjunto dourado tem {quantas} pergunta(s) da(s) base(s) {', '.join(alheias)}, "
            f"e a medição é da base '{base_id}' — métrica é por base, nunca agregada"
        )


@dataclass
class ResultadoPergunta:
    pergunta: Pergunta
    recuperados: list[str]
    posicao_primeiro_acerto: int | None
    recall: dict[int, float]
    mrr: float
    ndcg: float


@dataclass
class Resultado:
    retriever: str
    ks: tuple[int, ...]
    itens: list[ResultadoPergunta] = field(default_factory=list)

    def recall(self, k: int, tipo: str | None = None) -> float:
        return self.recall_de(self._filtrar(tipo), k)

    def mrr(self, tipo: str | None = None) -> float:
        return self.mrr_de(self._filtrar(tipo))

    def ndcg(self, tipo: str | None = None) -> float:
        return self.ndcg_de(self._filtrar(tipo))

    def _filtrar(self, tipo: str | None) -> list[ResultadoPergunta]:
        return [i for i in self.itens if tipo is None or i.pergunta.tipo == tipo]

    # Subgroup aggregates — used to separate questions written from file names
    # (biased in favour of a file-name baseline) from questions written from
    # memory. Without that split the baseline number flatters itself.
    @staticmethod
    def recall_de(itens: Sequence[ResultadoPergunta], k: int) -> float:
        return media(i.recall[k] for i in itens)

    @staticmethod
    def mrr_de(itens: Sequence[ResultadoPergunta]) -> float:
        return media(i.mrr for i in itens)

    @staticmethod
    def ndcg_de(itens: Sequence[ResultadoPergunta]) -> float:
        return media(i.ndcg for i in itens)

    def subgrupo(self, autoria: str | None = None, armadilha: bool | None = None) -> list[ResultadoPergunta]:
        return [
            i
            for i in self.itens
            if (autoria is None or i.pergunta.autoria == autoria)
            and (armadilha is None or i.pergunta.armadilha == armadilha)
        ]

    def restrito_ao_escopo(self) -> "Resultado":
        """Same result, keeping only the questions this phase can answer.

        Reported alongside the full set, never instead of it. A metric whose
        denominator moved without saying so is worse than no metric.
        """
        return Resultado(
            retriever=self.retriever,
            ks=self.ks,
            itens=[i for i in self.itens if i.pergunta.no_escopo],
        )

    @property
    def fora_do_escopo(self) -> list[ResultadoPergunta]:
        return [i for i in self.itens if not i.pergunta.no_escopo]

    @property
    def tipos(self) -> list[str]:
        return sorted({i.pergunta.tipo for i in self.itens})

    @property
    def sem_nenhum_acerto(self) -> list[ResultadoPergunta]:
        return [i for i in self.itens if i.posicao_primeiro_acerto is None]


def avaliar(retriever: Retriever, perguntas: Sequence[Pergunta], ks: tuple[int, ...] = KS_PADRAO) -> Resultado:
    k_max = max(max(ks), K_MRR, K_NDCG)
    resultado = Resultado(retriever=retriever.nome, ks=ks)

    for p in perguntas:
        hits = retriever.search(p.pergunta, k_max)
        recuperados = [h.path for h in hits]
        posicao = next((i for i, path in enumerate(recuperados, start=1) if path in p.fontes), None)
        resultado.itens.append(
            ResultadoPergunta(
                pergunta=p,
                recuperados=recuperados[:k_max],
                posicao_primeiro_acerto=posicao,
                recall={k: recall_at_k(recuperados, p.fontes, k, p.modo) for k in ks},
                mrr=reciprocal_rank(recuperados, p.fontes, K_MRR),
                ndcg=ndcg_at_k(recuperados, p.fontes, K_NDCG),
            )
        )
    return resultado


# --- consistência entre a anotação e o índice -------------------------------


@dataclass(frozen=True)
class Divergencia:
    """Uma discordância entre o que o conjunto dourado declara e o que o índice tem."""

    id: str
    especie: str
    """`silenciosa` (marcada no escopo, mas sem fonte alguma indexada) ou
    `anotacao_velha` (marcada fora de escopo, mas já indexável)."""
    detalhe: str


def verificar_escopo(
    perguntas: Sequence[Pergunta], indexados: set[str], *, universo_de_conteudo: bool = True
) -> list[Divergencia]:
    """Confere a anotação de escopo contra os documentos que o índice alcança.

    As duas direções importam, por motivos diferentes:

    - `silenciosa`: a pergunta se diz mensurável mas o índice não tem o que ela
      exige. Ela vai medir zero por falta de dado, não por falha de
      ranqueamento, e some no meio da média. É o modo de falha que essa
      verificação existe para pegar — um parser que quebra e ninguém vê.
    - `anotacao_velha`: a pergunta foi excluída por escopo mas já é indexável.
      Continuar excluindo esconderia um ganho real, o que também falseia a
      comparação entre fases.

    O que "exige" significa depende do modo: multi-hop pontua por `todas` as
    fontes, então **uma** ausente já trava a pergunta em zero; as demais pontuam
    por `qualquer`, e basta uma presente.

    `universo_de_conteudo=False` para recuperadores que ranqueiam sem ler o
    arquivo, como o baseline por nome. Para eles `indexados` é a lista de
    arquivos que existem no disco, e existir não é evidência de ser legível: o
    baseline alcança um `.msg` pelo nome sem nunca abri-lo, e acusar
    `anotacao_velha` aí seria confundir presença com extração de texto. A
    direção `silenciosa` continua valendo — ali a ausência significa arquivo
    movido ou apagado, que interessa aos dois.
    """
    divergencias: list[Divergencia] = []
    for p in perguntas:
        presentes = [f for f in p.fontes if f in indexados]
        bastante = len(presentes) == len(p.fontes) if p.modo == MODO_TODAS else bool(presentes)
        if p.no_escopo and not bastante:
            faltam = len(p.fontes) - len(presentes)
            divergencias.append(
                Divergencia(
                    p.id,
                    "silenciosa",
                    f"modo `{p.modo}`, {faltam} de {len(p.fontes)} fontes fora do índice",
                )
            )
        elif universo_de_conteudo and not p.no_escopo and len(presentes) == len(p.fontes):
            divergencias.append(
                Divergencia(p.id, "anotacao_velha", f"marcada como `{p.fora_de_escopo}`, mas já é indexável")
            )
    return divergencias


# --- relatório -------------------------------------------------------------


def render_markdown(resultado: Resultado, titulo: str, contexto: str = "") -> str:
    linhas: list[str] = []
    add = linhas.append

    no_escopo = resultado.restrito_ao_escopo()
    excluidas = resultado.fora_do_escopo

    add(f"# {titulo}")
    add("")
    if contexto:
        add(contexto)
        add("")
    add(f"- Recuperador: **{resultado.retriever}**")
    add(f"- Perguntas: **{len(no_escopo.itens)} no escopo**, de {len(resultado.itens)} no conjunto dourado")
    add(f"- MRR@{K_MRR} e nDCG@{K_NDCG}; recall com `qualquer` para pergunta comum e `todas` para multi-hop")
    add("")

    add("## Geral")
    add("")
    add("A linha de cima é a que vale para as portas da fase; a de baixo existe para")
    add("que a exclusão nunca passe despercebida. Toda tabela daqui para baixo é sobre")
    add("o subconjunto no escopo.")
    add("")
    cabecalho = " | ".join(f"recall@{k}" for k in resultado.ks)
    add(f"| Conjunto | n | {cabecalho} | MRR@{K_MRR} | nDCG@{K_NDCG} |")
    add("|---|---:|" + "---:|" * (len(resultado.ks) + 2))
    for rotulo, r in (("**no escopo da fase**", no_escopo), ("conjunto completo", resultado)):
        vals = " | ".join(f"{r.recall(k):.3f}" for k in r.ks)
        add(f"| {rotulo} | {len(r.itens)} | {vals} | {r.mrr():.3f} | {r.ndcg():.3f} |")
    add("")

    add(f"## Fora de escopo — {len(excluidas)} de {len(resultado.itens)}")
    add("")
    if excluidas:
        add("Excluídas por decisão de escopo declarada no conjunto dourado, não por resultado")
        add("ruim: a fonte que responderiam não existe em forma de texto para *nenhum*")
        add("recuperador desta fase. Ficam fora dos dois lados da comparação.")
        add("")
        add("| id | motivo | o que é | pergunta |")
        add("|---|---|---|---|")
        for i in sorted(excluidas, key=lambda x: x.pergunta.id):
            motivo = i.pergunta.fora_de_escopo
            add(
                f"| {i.pergunta.id} | `{motivo}` | {MOTIVOS_FORA_DE_ESCOPO.get(motivo, '?')} "
                f"| {i.pergunta.pergunta} |"
            )
    else:
        add("Nenhuma — todas as perguntas do conjunto dourado são mensuráveis nesta fase.")
    add("")

    add("## Por tipo de pergunta")
    add("")
    add("| Tipo | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | nDCG@{K_NDCG} |")
    add("|---|---:|" + "---:|" * (len(no_escopo.ks) + 2))
    for tipo in no_escopo.tipos:
        n = len(no_escopo._filtrar(tipo))
        vals = " | ".join(f"{no_escopo.recall(k, tipo):.3f}" for k in no_escopo.ks)
        add(f"| {tipo} | {n} | {vals} | {no_escopo.mrr(tipo):.3f} | {no_escopo.ndcg(tipo):.3f} |")
    add("")

    add("## Por origem da pergunta")
    add("")
    add("Perguntas escritas a partir dos nomes de arquivo favorecem, por construção, um")
    add("baseline que busca por nome. As escritas de memória pelo usuário não têm esse viés,")
    add("e são o número honesto para comparar com as fases seguintes.")
    add("")
    grupos: list[tuple[str, list[ResultadoPergunta]]] = [
        ("rascunho a partir de nomes", no_escopo.subgrupo(autoria="rascunho")),
        ("escritas pelo usuário", no_escopo.subgrupo(autoria="usuario")),
        ("casos-armadilha", no_escopo.subgrupo(armadilha=True)),
        ("sem armadilha", no_escopo.subgrupo(armadilha=False)),
    ]
    add("| Origem | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | nDCG@{K_NDCG} |")
    add("|---|---:|" + "---:|" * (len(no_escopo.ks) + 2))
    for rotulo, itens in grupos:
        if not itens:
            continue
        vals = " | ".join(f"{Resultado.recall_de(itens, k):.3f}" for k in no_escopo.ks)
        add(f"| {rotulo} | {len(itens)} | {vals} | {Resultado.mrr_de(itens):.3f} | {Resultado.ndcg_de(itens):.3f} |")
    add("")

    falhas = no_escopo.sem_nenhum_acerto
    add(f"## Sem nenhum acerto no top {max(no_escopo.ks)} — {len(falhas)} de {len(no_escopo.itens)} no escopo")
    add("")
    if falhas:
        add("| id | tipo | pergunta | fonte esperada |")
        add("|---|---|---|---|")
        for i in falhas:
            fonte = i.pergunta.fontes[0]
            add(f"| {i.pergunta.id} | {i.pergunta.tipo} | {i.pergunta.pergunta} | `{fonte}` |")
    else:
        add("Nenhuma.")
    add("")

    acertos = [i for i in no_escopo.itens if i.posicao_primeiro_acerto == 1]
    add(f"## Acertos na primeira posição — {len(acertos)}")
    add("")
    for i in acertos:
        add(f"- `{i.pergunta.id}` {i.pergunta.pergunta}")
    add("")

    return "\n".join(linhas)
