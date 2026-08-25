"""Evaluation loop over the golden set.

The contract every retriever implements is one method — `search(consulta, k)`.
The F0 baseline, the hybrid search of F1 and the reranked pipeline of F2 all
plug in here, so their numbers land in the same table and stay comparable
across phases. That comparability is the whole point of building this first.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .fonte import GRUPOS, grupo_de_pergunta
from .estatistica import N_MINIMO, ic_da_media
from .idioma import CROSS_LINGUAL, EN, FATIAS, INDEFINIDO, MESMA_LINGUA, MISTO, NAO_DECLARADO, PT, detectar
from .idioma import fatia as fatia_de
from .metrics import MODO_QUALQUER, MODO_TODAS, media, ndcg_at_k, recall_at_k, reciprocal_rank

KS_PADRAO = (1, 3, 5, 10, 20)
K_MRR = 10
KS_NDCG = (5, 10)
"""nDCG em dois cortes, e os dois são declarados em algum critério de saída.

O @5 é o que a F2 pede (`ROADMAP.md`, saída da fase); o @10 é o que toda a
medição anterior usou, e tirá-lo tornaria as tabelas da F0 e da F1
incomparáveis com as de agora. Comparabilidade entre fases é a razão de o
harness existir antes dos recuperadores."""
K_NDCG = KS_NDCG[-1]
"""Corte histórico, mantido para quem chama `ndcg()` sem dizer qual."""

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "eval" / "golden" / "perguntas.jsonl"
GOLDEN_EXEMPLO = REPO / "eval" / "golden" / "perguntas.example.jsonl"


def resolver_dourado(caminho: Path, *, implicito: bool) -> tuple[Path, str | None]:
    """Which golden file to load, and an optional warning.

    An explicit path that is missing is an error: substituting the example
    would measure the wrong corpus and look valid. The implicit default
    (`perguntas.jsonl`) may fall back to the committed example so a fresh
    clone still has a ruler.
    """
    if caminho.exists():
        return caminho, None
    # Só o default canônico cai no exemplo. Qualquer outro caminho ausente —
    # `--golden`, `dourado` da base — é erro: substituir mediria o acervo errado.
    if implicito and caminho.resolve() == GOLDEN.resolve() and GOLDEN_EXEMPLO.exists():
        return GOLDEN_EXEMPLO, (
            f"{caminho} ausente — medindo o conjunto sintético de exemplo "
            f"({GOLDEN_EXEMPLO.as_posix()}). Isso não avalia o acervo real. "
            "Ver eval/golden/README.md."
        )
    raise FileNotFoundError(
        f"conjunto dourado não encontrado: {caminho}. "
        "Sem perguntas não há régua (invariante 4). "
        "Escreva o arquivo no formato de eval/golden/README.md, "
        "ou meça o exemplo: --config config.sintetico.toml --base sintetico."
    )


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
    "ocr": "fonte é PDF digitalizado, imagem por página, zero texto extraível — OCR está fora da F1",
}
"""Por que uma pergunta não é mensurável nesta fase.

O catálogo **encurta** quando a capacidade entra. `email` (".msg, ou MIME com
extensão trocada — parser de email é da F4") saiu em 21/08/2026, junto com o
parser: motivo que sobrevive à própria correção é desculpa disponível, e
`carregar_perguntas` passa a **recusar** um conjunto dourado que ainda anote uma
pergunta como fora de escopo por ser email. É a garantia forte de que nenhuma
anotação velha atravesse a fase em silêncio.

A anotação é **estática**, no conjunto dourado, e não derivada do estado do
índice. Derivar do índice seria cômodo e errado: um parser que quebrasse
excluiria sozinho as perguntas que passou a errar, e a métrica **subiria** com a
regressão. Aqui a exclusão é uma decisão de escopo, versionada e revisável em
diff; `verificar_escopo()` confere a anotação contra o índice e reclama das duas
divergências possíveis."""


IDIOMAS_ACEITOS = (PT, EN, MISTO, INDEFINIDO)
"""O que `idioma` e `idioma_fonte` aceitam.

`misto` e `indefinido` são anotações legítimas e não sinônimos de vazio: vazio é
"ninguém olhou", `indefinido` é "olhou-se e não há evidência". A fatia trata os
três igual, mas o diff da anotação distingue os dois primeiros — e é o diff que
diz se a cobertura da fatia está crescendo ou parada."""


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
    idioma: str = ""
    """Idioma da **pergunta**. Vazio = detectar do texto (`eval.idioma`).

    A anotação existe para o caso que o detector não resolve e não deveria
    fingir que resolve: consulta curta feita de sigla e número, sem palavra
    funcional nenhuma. São 2 das 62 perguntas do acervo corporativo. Declarar é
    melhor que baixar o limiar — baixar o limiar acerta essas duas e passa a
    errar as outras sessenta em silêncio."""

    idioma_fonte: str = ""
    """Idioma da(s) **fonte(s)** esperada(s). Vazio = não declarado.

    Este campo **não** tem detecção de reserva, e a assimetria é deliberada: o
    texto da pergunta está aqui, o do documento não. Derivá-lo do índice na hora
    do relatório custaria o que mais importa neste harness — o baseline por nome
    não abre o índice, e a fatia deixaria de existir justamente no lado F0 da
    comparação entre fases.

    Quem preenche é `py -m eval.idioma --base X --escrever`, que lê o índice uma
    vez e grava a anotação. Depois disso ela é estática, versionada e conferível
    em diff, como `fora_de_escopo`. `eval.rodar` reconfere contra o índice e
    reclama quando as duas divergem."""

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

    @property
    def idioma_efetivo(self) -> str:
        """O idioma anotado, ou o detectado do texto da pergunta."""
        return self.idioma or detectar(self.pergunta)

    @property
    def fatia(self) -> str:
        """`mesma-língua`, `cross-lingual` ou `não declarado`."""
        return fatia_de(self.idioma_efetivo, self.idioma_fonte)

    @property
    def grupo_de_fonte(self) -> str:
        """`escritório`, `reunião`, `email` ou `misto` — derivado de `fontes`.

        Derivado e não anotado, ao contrário de `idioma_fonte`: o caminho da
        fonte está aqui, então não há o que envelhecer. Ver `eval.fonte`."""
        return grupo_de_pergunta(self.fontes)


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
                idioma=d.get("idioma", ""),
                idioma_fonte=d.get("idioma_fonte", ""),
                base=d.get("base", ""),
            )
        )
    desconhecidos = {p.fora_de_escopo for p in perguntas if p.fora_de_escopo} - set(MOTIVOS_FORA_DE_ESCOPO)
    if desconhecidos:
        raise ValueError(f"motivo de fora_de_escopo não catalogado: {sorted(desconhecidos)}")
    # `idioma: "pt-BR"` ou `idioma_fonte: "ingles"` não casariam com nada e a
    # pergunta cairia calada em `não declarado` — o mesmo modo de falha que a
    # fatia existe para acabar. Vocabulário fechado, erro alto.
    codigos = {c for p in perguntas for c in (p.idioma, p.idioma_fonte) if c} - set(IDIOMAS_ACEITOS)
    if codigos:
        raise ValueError(
            f"código de idioma não reconhecido: {sorted(codigos)} — "
            f"use um de {sorted(IDIOMAS_ACEITOS)}"
        )
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
    ndcg: dict[int, float]


@dataclass
class Resultado:
    retriever: str
    ks: tuple[int, ...]
    itens: list[ResultadoPergunta] = field(default_factory=list)

    def recall(self, k: int, tipo: str | None = None) -> float:
        return self.recall_de(self._filtrar(tipo), k)

    def mrr(self, tipo: str | None = None) -> float:
        return self.mrr_de(self._filtrar(tipo))

    def ndcg(self, tipo: str | None = None, k: int = K_NDCG) -> float:
        return self.ndcg_de(self._filtrar(tipo), k)

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
    def ndcg_de(itens: Sequence[ResultadoPergunta], k: int = K_NDCG) -> float:
        return media(i.ndcg[k] for i in itens)

    def subgrupo(
        self,
        autoria: str | None = None,
        armadilha: bool | None = None,
        fatia: str | None = None,
        grupo_de_fonte: str | None = None,
    ) -> list[ResultadoPergunta]:
        return [
            i
            for i in self.itens
            if (autoria is None or i.pergunta.autoria == autoria)
            and (armadilha is None or i.pergunta.armadilha == armadilha)
            and (fatia is None or i.pergunta.fatia == fatia)
            and (grupo_de_fonte is None or i.pergunta.grupo_de_fonte == grupo_de_fonte)
        ]

    def por_fatia(self) -> list[tuple[str, list[ResultadoPergunta]]]:
        """As três fatias de idioma, **inclusive as vazias**.

        Fatia com n=0 aparece na tabela com o zero à mostra em vez de sumir. É a
        diferença entre "medimos e não há par cross-lingual neste acervo" e "a
        fatia não foi calculada", que um relatório sem a linha não distingue —
        e a segunda é exatamente a lacuna que C4.5 existe para fechar."""
        return [(f, self.subgrupo(fatia=f)) for f in FATIAS]

    def por_grupo_de_fonte(self) -> list[tuple[str, list[ResultadoPergunta]]]:
        """Os quatro grupos de fonte, **inclusive os vazios**.

        Mesmo argumento de `por_fatia`: grupo com n=0 aparece com o zero à
        mostra. "Este acervo não tem email no dourado" e "o recorte por fonte
        não foi calculado" são diagnósticos diferentes, e uma linha ausente não
        os distingue."""
        return [(g, self.subgrupo(grupo_de_fonte=g)) for g in GRUPOS]

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

    @staticmethod
    def serie_de(itens: Sequence[ResultadoPergunta], metrica: str, k: int = K_NDCG) -> dict[str, float]:
        """Valor por pergunta, **indexado pelo id** — a entrada do bootstrap.

        Indexado pelo id e não uma lista por uma razão de correção: o teste de
        `E5` é pareado, e parear por ordem de iteração quebraria em silêncio no
        dia em que um dos braços deixasse uma pergunta de fora (fonte que saiu do
        índice, filtro de escopo diferente). `estatistica.alinhar()` casa pelo id
        e devolve quantas sobraram."""
        if metrica == "recall":
            return {i.pergunta.id: i.recall[k] for i in itens}
        if metrica == "mrr":
            return {i.pergunta.id: i.mrr for i in itens}
        if metrica == "ndcg":
            return {i.pergunta.id: i.ndcg[k] for i in itens}
        raise ValueError(f"métrica desconhecida: {metrica}")

    def serie(self, metrica: str, k: int = K_NDCG) -> dict[str, float]:
        return self.serie_de(self.itens, metrica, k)


def avaliar(retriever: Retriever, perguntas: Sequence[Pergunta], ks: tuple[int, ...] = KS_PADRAO) -> Resultado:
    k_max = max(max(ks), K_MRR, *KS_NDCG)
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
                ndcg={k: ndcg_at_k(recuperados, p.fontes, k) for k in KS_NDCG},
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


CABECALHO_NDCG = " | ".join(f"nDCG@{k}" for k in KS_NDCG)


def _alinhamento(ks: tuple[int, ...]) -> str:
    """Uma coluna por recall, uma de MRR e uma por corte de nDCG."""
    return "|---|---:|" + "---:|" * (len(ks) + 1 + len(KS_NDCG))


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
    add(f"- MRR@{K_MRR} e {CABECALHO_NDCG}; recall com `qualquer` para pergunta comum e `todas` para multi-hop")
    add("")

    add("## Geral")
    add("")
    add("A linha de cima é a que vale para as portas da fase; a de baixo existe para")
    add("que a exclusão nunca passe despercebida. Toda tabela daqui para baixo é sobre")
    add("o subconjunto no escopo.")
    add("")
    cabecalho = " | ".join(f"recall@{k}" for k in resultado.ks)
    add(f"| Conjunto | n | {cabecalho} | MRR@{K_MRR} | {CABECALHO_NDCG} |")
    add(_alinhamento(resultado.ks))
    for rotulo, r in (("**no escopo da fase**", no_escopo), ("conjunto completo", resultado)):
        vals = " | ".join(f"{r.recall(k):.3f}" for k in r.ks)
        ndcgs = " | ".join(f"{r.ndcg(k=k):.3f}" for k in KS_NDCG)
        add(f"| {rotulo} | {len(r.itens)} | {vals} | {r.mrr():.3f} | {ndcgs} |")
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
    add("| Tipo | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | {CABECALHO_NDCG} |")
    add(_alinhamento(no_escopo.ks))
    for tipo in no_escopo.tipos:
        n = len(no_escopo._filtrar(tipo))
        vals = " | ".join(f"{no_escopo.recall(k, tipo):.3f}" for k in no_escopo.ks)
        ndcgs = " | ".join(f"{no_escopo.ndcg(tipo, k=k):.3f}" for k in KS_NDCG)
        add(f"| {tipo} | {n} | {vals} | {no_escopo.mrr(tipo):.3f} | {ndcgs} |")
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
    add("| Origem | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | {CABECALHO_NDCG} |")
    add(_alinhamento(no_escopo.ks))
    for rotulo, itens in grupos:
        if not itens:
            continue
        vals = " | ".join(f"{Resultado.recall_de(itens, k):.3f}" for k in no_escopo.ks)
        ndcgs = " | ".join(f"{Resultado.ndcg_de(itens, k):.3f}" for k in KS_NDCG)
        add(f"| {rotulo} | {len(itens)} | {vals} | {Resultado.mrr_de(itens):.3f} | {ndcgs} |")
    add("")

    add("## Por idioma — mesma-língua contra cross-lingual")
    add("")
    add("O acervo é bilíngue e a arquitetura aposta em uma ponte só: o ranqueador denso")
    add("é multilíngue e alinhado entre idiomas, enquanto o bm25 é cego a idioma por")
    add("construção — FTS5 não casa `contrato` com `agreement`. Sem este recorte, uma")
    add("regressão que quebrasse **só** a ponte PT↔EN passaria com a média agregada")
    add("intacta, porque o lado mesma-língua é maioria e a esconderia.")
    add("")
    add("`não declarado` é o par cujo idioma de pergunta ou de fonte não foi decidido —")
    add("anotação ausente, ou texto sem evidência de idioma. Ele **não** é somado a")
    add("nenhuma das duas fatias; aparece com o n para a cobertura ficar visível.")
    add("")
    add("| Fatia | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | {CABECALHO_NDCG} |")
    add(_alinhamento(no_escopo.ks))
    for rotulo, itens in no_escopo.por_fatia():
        if not itens:
            add(f"| {rotulo} | 0 | " + " | ".join("—" for _ in no_escopo.ks) + " | — | " + " | ".join("—" for _ in KS_NDCG) + " |")
            continue
        vals = " | ".join(f"{Resultado.recall_de(itens, k):.3f}" for k in no_escopo.ks)
        ndcgs = " | ".join(f"{Resultado.ndcg_de(itens, k):.3f}" for k in KS_NDCG)
        add(f"| {rotulo} | {len(itens)} | {vals} | {Resultado.mrr_de(itens):.3f} | {ndcgs} |")
    add("")
    mesma = no_escopo.subgrupo(fatia=MESMA_LINGUA)
    cross = no_escopo.subgrupo(fatia=CROSS_LINGUAL)
    if mesma and cross:
        base_recall = Resultado.recall_de(mesma, 5)
        razao = Resultado.recall_de(cross, 5) / base_recall if base_recall else 0.0
        # Ponto e não vírgula decimal: a tabela logo acima usa `{:.3f}`, e o
        # relatório inteiro é assim. Uma frase com vírgula embaixo de uma coluna
        # com ponto lê como duas medições diferentes.
        add(
            f"Razão cross-lingual / mesma-língua em recall@5: **{razao:.2f}**. "
            "O critério de aceite de `C4.5` é **>= 0.80**."
        )
    else:
        add(
            "Sem as duas fatias povoadas não há razão a calcular. "
            "`py -m eval.idioma --base <id> --escrever` anota `idioma_fonte` a partir do índice."
        )
    add("")

    add("## Por tipo de fonte — onde o nome do arquivo ajuda e onde atrapalha")
    add("")
    add("Medido em 24/08/2026 e o motivo de o recorte existir: nas perguntas de reunião,")
    add("**desligar o ranqueador de nome sobe o MRR 60%**, enquanto no conjunto inteiro ele")
    add("continua se pagando. No documento de escritório o identificador **está** no nome;")
    add("na transcrição o nome só tem assunto e data, e casa com qualquer pergunta que")
    add("repita a palavra do assunto. Média agregada some com a troca inteira.")
    add("")
    add("O grupo é **derivado** do caminho da fonte (`eval/fonte.py`), não anotado — o")
    add("dourado já carrega `fontes`, então não há anotação a envelhecer. `misto` é a")
    add("pergunta cujas fontes caem em grupos diferentes: ela mede a **ponte** entre eles")
    add("e não é somada a nenhum dos lados.")
    add("")
    add("| Grupo | n | " + " | ".join(f"recall@{k}" for k in no_escopo.ks) + f" | MRR@{K_MRR} | {CABECALHO_NDCG} |")
    add(_alinhamento(no_escopo.ks))
    for rotulo, itens in no_escopo.por_grupo_de_fonte():
        if not itens:
            add(f"| {rotulo} | 0 | " + " | ".join("—" for _ in no_escopo.ks) + " | — | " + " | ".join("—" for _ in KS_NDCG) + " |")
            continue
        vals = " | ".join(f"{Resultado.recall_de(itens, k):.3f}" for k in no_escopo.ks)
        ndcgs = " | ".join(f"{Resultado.ndcg_de(itens, k):.3f}" for k in KS_NDCG)
        add(f"| {rotulo} | {len(itens)} | {vals} | {Resultado.mrr_de(itens):.3f} | {ndcgs} |")
    add("")

    add("## Ruído — o que este n consegue distinguir")
    add("")
    add("Intervalo de percentil por bootstrap (`eval/estatistica.py`, 1.000 reamostragens,")
    add("semente fixa). Ele responde a pergunta que uma tabela de médias não responde:")
    add("**um ganho deste tamanho seria distinguível de sorte neste conjunto?**")
    add("")
    add("Ler com duas ressalvas, e as duas importam:")
    add("")
    add("1. Este é o intervalo de **um braço isolado**, e ele é largo de propósito —")
    add("   ignora a correlação entre duas configurações que respondem as mesmas")
    add("   perguntas. **Dois intervalos que se sobrepõem não provam empate.** Para")
    add("   comparar dois braços use o Δ pareado de `py -m eval.comparar`, que é")
    add("   sempre mais estreito e é o que a regra de adoção de `E5.2` consulta.")
    add(f"2. Fatia com n < {N_MINIMO} vai marcada com `⚠`. O intervalo dela não está errado —")
    add("   está honesto, e larguíssimo. É o piso que dimensiona as perguntas do `E1`.")
    add("")
    add(f"| Recorte | n | recall@1 | IC95 | MRR@{K_MRR} | IC95 | largura |")
    add("|---|---:|---:|:---:|---:|:---:|---:|")

    def _linha_de_ruido(rotulo: str, itens: list[ResultadoPergunta]) -> None:
        if not itens:
            add(f"| {rotulo} | 0 | — | — | — | — | — |")
            return
        marca = " ⚠" if len(itens) < N_MINIMO else ""
        r1 = Resultado.recall_de(itens, 1)
        rb, ra = ic_da_media([i.recall[1] for i in itens])
        m = Resultado.mrr_de(itens)
        mb, ma = ic_da_media([i.mrr for i in itens])
        add(
            f"| {rotulo}{marca} | {len(itens)} | {r1:.3f} | [{rb:.3f}, {ra:.3f}] "
            f"| {m:.3f} | [{mb:.3f}, {ma:.3f}] | {ma - mb:.3f} |"
        )

    _linha_de_ruido("**conjunto no escopo**", no_escopo.itens)
    for rotulo, itens in no_escopo.por_fatia():
        _linha_de_ruido(f"idioma · {rotulo}", itens)
    for rotulo, itens in no_escopo.por_grupo_de_fonte():
        _linha_de_ruido(f"fonte · {rotulo}", itens)
    add("")
    estreitas = [
        (rot, itens)
        for rot, itens in (*no_escopo.por_fatia(), *no_escopo.por_grupo_de_fonte())
        if itens and len(itens) < N_MINIMO
    ]
    if estreitas:
        pior = max(estreitas, key=lambda p: (lambda b, a: a - b)(*ic_da_media([i.mrr for i in p[1]])))
        b, a = ic_da_media([i.mrr for i in pior[1]])
        add(
            f"A fatia mais frágil é **{pior[0]}** com n={len(pior[1])}: o MRR dela cabe em "
            f"{a - b:.3f} de intervalo, então qualquer Δ menor que isso, medido só nela, "
            "é indistinguível de ruído."
        )
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


def entregar(relatorio: str, out: Path | None) -> None:
    """Grava o relatório no arquivo, ou no stdout — os dois em UTF-8.

    Existe por um defeito medido em 24/08/2026: `py -m eval.latencia --porta`
    rodou as três rodadas inteiras, montou o relatório e **morreu ao imprimir**,
    com `UnicodeEncodeError` num `→`. O `--out` sempre declarou
    `encoding="utf-8"`; o stdout não, e no console do Windows ele nasce em
    cp1252. Todo relatório daqui usa `→`, `≥` e `×`, então a porta que existe
    para barrar regressão não conseguia relatar nada — e o modo de falha é o pior
    possível: a medição custou minutos e o processo cai depois dela, com traceback
    de codec em vez de número.

    O `.mcp.json` já resolvia isso para o servidor com `PYTHONIOENCODING=utf-8`,
    e é por isso que o defeito nunca apareceu ali. Não vale exigir a variável de
    quem roda o eval à mão: a régua tem de funcionar do jeito que o `README`
    manda rodar.

    Escreve em `sys.stdout.buffer` em vez de reconfigurar o `sys.stdout` do
    processo — reconfigurar é estado global e afetaria quem mais escrevesse ali.
    O `flush` antes evita que o texto já bufferizado saia depois dos bytes.
    """
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(relatorio, encoding="utf-8")
        return
    texto = relatorio + "\n"
    fluxo = getattr(sys.stdout, "buffer", None)
    if fluxo is None:
        # stdout capturado (pytest, notebook): já é unicode, não há codec no meio.
        sys.stdout.write(texto)
        return
    sys.stdout.flush()
    fluxo.write(texto.encode("utf-8"))
    fluxo.flush()
