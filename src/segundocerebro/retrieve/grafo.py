"""Grafo derivado — constrói as menções e anda por elas.

    py -m segundocerebro.retrieve.grafo --base padrao            # constrói
    py -m segundocerebro.retrieve.grafo --base padrao --estado   # só relata

Este é o "substituto dos wikilinks" de `ARCHITECTURE.md`: o acervo não tem link
nenhum entre documentos, então a única ligação explícita é o identificador que
dois documentos citam. Sem isso, um plano de ação que termina em "certificação
ISO 42001" e a norma ISO 42001, em outra pasta, são dois documentos sem nada em
comum — nem nome, nem pasta, nem vocabulário.

## Passada separada, não dentro do laço do indexador

Duas razões, e as duas valem por si:

1. **O grafo é derivado do índice, não do disco.** Melhorar uma regex de
   identificador passa a custar segundos de releitura do SQLite em vez de uma
   reindexação de 39 h. Numa fase cujo trabalho *é* refinar regras de extração,
   essa diferença decide quantas iterações cabem.
2. O laço de `index/indexer.py` tem dono declarado em `docs/colaboracao.md`, e
   mexer nele exigiria um PR separado e coordenação. Não tocá-lo é de graça.

O custo é que o grafo pode ficar velho em relação ao índice. Fica registrado no
`progresso` do próprio grafo (contagem de documentos com menção contra
documentos com chunk), e é o que `--estado` mostra.

## O peso da aresta é a raridade do identificador

Sem isto a ferramenta é inútil, e não por pouco. O CNPJ da própria empresa
aparece em todo contrato do acervo; a ISO 9001 aparece em toda política. Ligar
por eles devolveria centenas de "documentos relacionados" que não têm relação
nenhuma — e com procedência correta, o que é o pior tipo de resposta errada.

Duas defesas, uma dura e uma graduada:

- **Teto duro** (`MAX_DOCUMENTOS_POR_ID`): identificador citado em mais de N
  documentos deixa de ser aresta e passa a ser taxonomia. Não entra.
- **Peso por raridade**: entre os que passam, um identificador em 2 documentos
  pesa mais que um em 30. É a mesma intuição do IDF, aplicada a aresta em vez de
  termo.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from ..logger import get_logger
from .identificadores import extrair

log = get_logger("retrieve.grafo")

MAX_DOCUMENTOS_POR_ID = 40
"""Acima disto o identificador não liga nada — é assunto do acervo, não aresta.

O número foi **medido**, e a primeira tentativa (25) estava errada do jeito mais
caro possível: cortava a `ISO 42001`, citada em 27 documentos, que é exatamente a
aresta que esta fase existe para construir. Cortar o caso motivador com um limite
escolhido no abstrato é o erro que a distribuição real desfaz.

Distribuição no acervo em 20/08/2026 (1.601 documentos, 7.109 identificadores):

    2-5 docs   363 identificadores   ← as arestas fortes
    6-10        30
    11-20       19
    21-30        9   ← ISO 42001 (27) mora aqui
    31-54       14   ← LGPD (54), ISO 27001 (49), CNPJ da empresa (48)
    55+          0

O corte em 40 separa duas famílias que a contagem revela e o nome confirma:
abaixo, norma **em discussão** num projeto; acima, certificação que a empresa
**tem** e cita em todo documento de ESG, mais o CNPJ dela própria. Não é
fronteira perfeita — `ISO 9001` (37) passa e é fraca —, e é por isso que o peso
por raridade continua sendo a defesa principal: 1/37 perde de longe para 1/2.

Depende do tamanho do acervo, e por isso é argumento. Num acervo de 50
documentos, 40 é quase tudo.
"""

MAX_VIZINHOS = 10
"""Teto de vizinhos devolvidos. O cliente paga contexto por cada um."""


@dataclass(frozen=True)
class Ligacao:
    """Por que dois documentos estão ligados. O motivo é parte da resposta.

    `neighbors` sem motivo seria um oráculo: o cliente receberia uma lista de
    documentos "relacionados" e teria que confiar. Com o identificador e o
    trecho onde ele aparece, o modelo pode conferir — e descartar, se a ligação
    não servir para a pergunta dele.
    """

    tipo: str
    valor: str
    documentos: int
    """Em quantos documentos do acervo este identificador aparece."""
    chunk_id: str = ""
    """Onde o vizinho cita — para o cliente poder ler com `read_note`.

    Vazio significa que a menção veio do **nome do arquivo**, não do corpo: é o
    caso do PDF digitalizado, cujo único sinal é o nome. Ver `no_nome`."""

    @property
    def peso(self) -> float:
        """Raridade. Dois documentos citando o mesmo id valem mais que trinta."""
        return 1.0 / max(1, self.documentos)

    @property
    def no_nome(self) -> bool:
        """O identificador está no nome do arquivo, não no texto.

        A distinção decide a ordem, e foi o que consertou o resultado no acervo
        real: 27 documentos citam a `ISO 42001` e todos empatavam no mesmo peso,
        então o topo saía por ordem alfabética — exercícios de curso que mencionam
        a norma de passagem vinham antes do **próprio texto da norma**, que era o
        documento procurado.

        Nome e corpo não são o mesmo tipo de evidência. `ISO-420012023_-Web.pdf`
        **é** a norma; um plano que a cita **fala sobre** ela. Por isso a diferença
        entra como categoria e não como multiplicador inventado: não existe número
        justificável para "quantas vezes melhor" é ser o documento canônico.
        """
        return not self.chunk_id


@dataclass
class Vizinho:
    path: str
    ligacoes: list[Ligacao] = field(default_factory=list)

    @property
    def peso(self) -> float:
        """Soma dos pesos: dois identificadores raros em comum é sinal mais forte
        que um só. Soma e não máximo, porque acumular evidência independente é
        exatamente o que a fusão de ranqueadores desta pilha já faz."""
        return sum(l.peso for l in self.ligacoes)

    @property
    def canonico(self) -> bool:
        """Este documento **é** o assunto do identificador, e não só o cita.

        Verdadeiro quando alguma ligação vem do nome do arquivo. É o primeiro
        critério de ordenação, antes do peso, porque num empate de raridade — que
        é o caso comum quando 27 documentos citam a mesma norma — a pergunta
        "qual deles é a norma?" tem uma resposta certa, e não é a alfabética.
        """
        return any(l.no_nome for l in self.ligacoes)


def _texto_do_caminho(path: str) -> str:
    """O caminho como texto extraível.

    Separador e sublinhado viram espaço pela mesma razão que em
    `store.caminho_pesquisavel`: sem isso `ISO-420012023_-Web.pdf` não tem
    fronteira de palavra onde o extrator espera, e a extensão cola no número.
    """
    return " ".join(path.replace("/", " ").replace("\\", " ").replace("_", " ").split())


def construir(store, *, limite_por_chunk: int = 40) -> dict[str, int]:  # noqa: ANN001
    """Varre os chunks do índice e grava as menções. Idempotente.

    Percorre por documento e não por chunk para que a substituição em
    `registrar_mencoes` seja por documento — o que torna a passada retomável sem
    marcador: reprocessar um documento já processado dá o mesmo resultado.
    """
    # Todo documento do registro, não só os que têm chunk: o nome do arquivo é
    # fonte de identificador por si, e é a **única** fonte para PDF digitalizado.
    # Medido em 20/08/2026: a norma que a `g048` precisa é um PDF de 61 páginas
    # sem texto extraível (`status: vazio`), e o identificador dela está só no
    # nome — `ISO-420012023_-Web.pdf`. Varrer apenas quem tem chunk deixaria de
    # fora exatamente o documento que motivou a fase.
    # União, e não um-ou-o-outro: as duas fontes discordam nas duas direções.
    # Documento digitalizado está no registro e não tem chunk; e um índice cujo
    # registro esteja incompleto tem chunk sem linha de registro. Escrever
    # `registro or chunks` funcionava no acervo real por acidente — lá todo
    # documento com chunk também está no registro — e perdia silenciosamente
    # metade dos documentos em qualquer índice parcial.
    paths = sorted(set(store.paths_do_registro()) | set(store.paths_com_chunks()))
    total_mencoes = 0
    com_mencao = 0
    for path in paths:
        achados: dict[tuple[str, str], str] = {}
        # O caminho primeiro, para o `chunk_id` do corpo sobrescrever o vazio
        # quando as duas fontes citarem o mesmo identificador: com trecho é
        # melhor que sem, porque o cliente pode ler e conferir.
        for ident in extrair(_texto_do_caminho(path), limite=limite_por_chunk):
            achados[(ident.tipo, ident.valor)] = ""
        for chunk in store.chunks_de(path):
            for ident in extrair(chunk.texto, limite=limite_por_chunk):
                # Primeiro chunk que cita ganha o registro: é o mais provável de
                # ser a menção principal, e guardar todos multiplicaria linhas
                # sem acrescentar aresta — a aresta é por documento.
                if not achados.get((ident.tipo, ident.valor)):
                    achados[(ident.tipo, ident.valor)] = chunk.id
        if achados:
            com_mencao += 1
        total_mencoes += store.registrar_mencoes(
            path, [(t, v, c) for (t, v), c in achados.items()]
        )
    store.con.commit()
    resumo = {
        "documentos": len(paths),
        "com_mencao": com_mencao,
        "mencoes": total_mencoes,
    }
    log.info(
        "grafo: %d documentos varridos, %d com identificador, %d menções",
        resumo["documentos"],
        resumo["com_mencao"],
        resumo["mencoes"],
    )
    return resumo


def vizinhos(
    store,  # noqa: ANN001
    path: str,
    *,
    limite: int = MAX_VIZINHOS,
    max_documentos_por_id: int = MAX_DOCUMENTOS_POR_ID,
) -> list[Vizinho]:
    """Documentos ligados a `path` por identificador em comum, do mais forte ao
    mais fraco.

    Devolve lista vazia quando o documento não cita identificador nenhum — que é
    o caso honesto e comum, e não um erro. Um acervo em que `neighbors` sempre
    devolve algo é um acervo com o teto mal calibrado.
    """
    frequencias = {
        (tipo, valor): docs
        for tipo, valor, docs in store.frequencia_de_mencoes(path)
        # `docs <= 1` significa que só este documento cita: não há vizinho.
        if 1 < docs <= max_documentos_por_id
    }
    if not frequencias:
        return []

    por_path: dict[str, Vizinho] = {}
    for (tipo, valor), docs in frequencias.items():
        for outro, chunk_id in store.quem_cita(tipo, valor, excluir=path):
            vizinho = por_path.setdefault(outro, Vizinho(path=outro))
            vizinho.ligacoes.append(Ligacao(tipo, valor, docs, chunk_id))

    # **Peso primeiro, canônico como desempate** — e a ordem dos dois critérios é
    # o ponto. Ser o documento canônico de uma norma que meio acervo cita vale
    # menos que compartilhar um código de contrato que só dois documentos citam:
    # o segundo é evidência específica, o primeiro é evidência genérica. Inverter
    # os critérios põe a norma de qualidade acima do contrato irmão.
    #
    # O desempate importa porque o empate é o caso comum: quando N documentos
    # compartilham só um identificador, todos têm exatamente o mesmo peso, e sem
    # o critério de canonicidade a ordem sai alfabética. Foi o que aconteceu no
    # acervo real com 27 documentos citando a `ISO 42001`.
    #
    # `round` no peso porque o desempate depende de igualdade de float: somas dos
    # mesmos valores em ordens diferentes divergem no último bit, e aí a
    # canonicidade deixaria de ser consultada sem ninguém notar.
    ordenados = sorted(por_path.values(), key=lambda v: (-round(v.peso, 9), not v.canonico, v.path))
    for vizinho in ordenados:
        # Motivo mais forte primeiro: se o cliente ler só a primeira ligação,
        # que seja a mais informativa.
        vizinho.ligacoes.sort(key=lambda l: (not l.no_nome, -l.peso, l.tipo, l.valor))
    return ordenados[:limite]


def desatualizado(store) -> dict[str, int]:  # noqa: ANN001
    """Quanto o grafo está atrás do índice.

    Existe porque a passada é separada, e uma métrica de recuperação medida com
    grafo velho mediria a coisa errada sem avisar.
    """
    com_chunk = len(store.paths_com_chunks())
    com_mencao = len(store.paths_com_mencoes())
    return {"documentos_no_indice": com_chunk, "documentos_no_grafo": com_mencao}


def main(argv: list[str] | None = None) -> int:
    from ..config import ErroDeConfig, carregar
    from ..index.store import Store

    parser = argparse.ArgumentParser(
        prog="segundocerebro.retrieve.grafo",
        description="Constrói o grafo derivado a partir do índice já existente",
    )
    parser.add_argument("--base", help="qual base (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--indice", type=Path, help="diretório do índice, sobrepõe a base")
    parser.add_argument("--estado", action="store_true", help="só relata, não constrói")
    args = parser.parse_args(argv)

    try:
        conf = carregar(args.config)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    diretorio = args.indice or base.indice
    if not diretorio.exists():
        log.error("índice não encontrado em %s — indexe antes de construir o grafo", diretorio)
        return 2

    # A dimensão sai da tabela de modelos, **não** de um encoder carregado: o
    # grafo lê texto de chunk e não toca vetor nenhum, e carregar o `e5-large`
    # para isso custaria ~80 s por execução sem servir para nada. O `Store` pede
    # `dim` porque a tabela de vetores é aberta sob demanda — e aqui ela nunca é.
    from ..index.embeddings import MODELOS

    spec = MODELOS.get(base.modelo)
    if spec is None:
        log.error("modelo desconhecido na base: %s", base.modelo)
        return 2

    store = Store(diretorio, spec.dim)
    if args.estado:
        atraso = desatualizado(store)
        log.info(
            "grafo: %d de %d documentos do índice têm menção registrada",
            atraso["documentos_no_grafo"],
            atraso["documentos_no_indice"],
        )
        for chave, valor in store.estatisticas_do_grafo().items():
            log.info("  %s: %s", chave, valor)
        return 0

    construir(store)
    for chave, valor in store.estatisticas_do_grafo().items():
        log.info("  %s: %s", chave, valor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
