"""Run a retriever over the golden set and write the report.

    py -m eval.rodar --out docs/metricas-f0.md                 # baseline por nome
    py -m eval.rodar --retriever hibrido --out docs/metricas-f1.md
    py -m eval.rodar --retriever denso                          # ablação
    py -m eval.rodar --retriever bm25

Every configuration lands in the same table because they all implement the same
`Retriever` protocol. That comparability across phases is the reason the harness
was built before any retrieval existed.

Comparability has two conditions that the flags exist to enforce:

- **Mesmo universo de documentos.** `--prefixo` recorta o baseline para a mesma
  subárvore que o índice cobre. Sem ele o baseline enumera a raiz inteira do
  `census.toml` e a comparação mistura qualidade de ranqueamento com escala.
- **Mesmas perguntas.** O relatório separa o subconjunto no escopo da fase das
  perguntas cuja fonte nenhum recuperador desta fase consegue ler, e mostra os
  dois números.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from segundocerebro.config import ErroDeConfig, carregar
from segundocerebro.logger import get_logger
from segundocerebro.retrieve.glossario import Glossario
from segundocerebro.retrieve.hybrid import BuscaHibrida
from segundocerebro.retrieve.rerank import CANDIDATOS_PARA_RERANK

from .baselines import BuscaPorNomeDeArquivo
from .cobertura import medir as medir_cobertura
from .harness import (
    GOLDEN,
    avaliar,
    carregar_perguntas,
    conferir_base,
    entregar,
    render_markdown,
    resolver_dourado,
    verificar_escopo,
)
from .idioma import conferir as conferir_idioma
from .idioma import idiomas_das_fontes

log = get_logger("eval")

REPO = Path(__file__).resolve().parent.parent

PESO_RERANK_DA_FLAG = 0.25
"""Voz usada quando `--rerank` é pedido numa base que não configura o peso.

O valor medido em 16/08/2026 (`docs/ablacao-rerank.md`): o pico da grade.

**É a fonte deste 0,25**, e desde 30/08/2026 (`Q12`) o
`config.example.toml` é conferido contra ele por
`tests/test_config.py::test_o_rerank_sugerido_no_exemplo_bate_com_o_eval`. Não
virou constante de `config.py` de propósito: é peso de *sugestão*, não padrão do
produto — o padrão é desligado —, e o `Q12` aceita as duas saídas, "cada valor
num lugar só **ou** amarrado por teste"."""


def _montar(args, cfg):  # noqa: ANN001
    """Build the retriever, its document universe, and the line describing it."""
    if args.retriever == "baseline":
        retriever = BuscaPorNomeDeArquivo.a_partir_de(cfg.roots, cfg, prefixo=args.prefixo)
        recorte = f", recorte `{args.prefixo}`" if args.prefixo else ""
        contexto = (
            f"Corpus de {len(retriever.documentos)} documentos{recorte}.\n"
            "O baseline lê apenas nome de arquivo e caminho de pastas — nenhum conteúdo."
        )
        return retriever, "Métricas F0 — baseline", contexto, None, retriever.universo

    from segundocerebro.index.embeddings import Embedder
    from segundocerebro.index.store import IndiceEmEscrita, Store, recusar_se_indexando

    indice = args.indice or args.base_cfg.indice
    try:
        recusar_se_indexando(indice)
    except IndiceEmEscrita as erro:
        log.error("%s", erro)
        raise SystemExit(4) from erro
    embedder = Embedder(args.modelo or args.base_cfg.modelo, threads=args.threads)
    store = Store(indice, embedder.dim)
    estat = store.estatisticas()
    if not estat["chunks"]:
        log.error("índice vazio em %s — rodar o indexador primeiro", indice)
        raise SystemExit(2)

    # Pesos e reranker vêm da base quando a flag não os fixa, e é isso que faz o
    # número medido aqui ser o número que o servidor MCP roda.
    #
    # Até 17/08/2026 o reranker era exceção: só existia se `--rerank` fosse
    # passado. O efeito foi o defeito que o bloco A da F3.5 existe para impedir —
    # uma medição de confirmação rodou sem rerank contra uma configuração que o
    # tinha ligado, e os números batiam com a referência **errada**. A flag agora
    # sobrepõe o número de candidatos; ela não é mais a porta de entrada.
    reranker = BuscaHibrida.reranker_de(args.base_cfg)
    if args.sem_rerank:
        reranker = None
    elif args.rerank:
        from segundocerebro.retrieve.rerank import Reranker

        peso = args.base_cfg.busca.rerank or PESO_RERANK_DA_FLAG
        reranker = Reranker(candidatos=int(args.rerank), peso=peso, threads=args.threads)

    pesos = args.base_cfg.pesos
    # Uma variável só, porque o relatório também a imprime: em 16/08/2026 o
    # relatório da condição C saiu dizendo "None candidatos" enquanto a busca
    # rodava com 200. Número de configuração que aparece no relatório tem que ser
    # o mesmo objeto que foi para o recuperador, ou o documento mente sobre o
    # experimento que descreve.
    candidatos = args.candidatos if args.candidatos is not None else args.base_cfg.busca.candidatos
    retriever = BuscaHibrida(
        store,
        embedder,
        candidatos=candidatos,
        k_rrf=args.base_cfg.busca.k_rrf,
        usar_denso=args.retriever in ("hibrido", "denso"),
        usar_lexical=args.retriever in ("hibrido", "bm25"),
        usar_nome=not args.sem_nome and bool(pesos.nome),
        peso_denso=args.peso_denso if args.peso_denso is not None else pesos.denso,
        peso_lexical=pesos.lexical,
        peso_nome=args.peso_nome if args.peso_nome is not None else pesos.nome,
        nome_por_fonte=args.nome_por_fonte,
        glossario=Glossario.de_arquivo(args.glossario) if args.glossario else None,
        reranker=reranker,
    )
    universo = store.paths_com_chunks()
    contexto = (
        f"Índice com {estat['documentos']} documentos e {estat['chunks']} chunks, "
        f"{len(universo)} documentos alcançáveis pela busca, "
        f"modelo `{embedder.model_id}`, {candidatos} candidatos por ranking antes da fusão.\n"
        # O relatório tem que descrever o experimento que descreve. Um documento
        # que omite o reranker é indistinguível de um medido sem ele — foi assim
        # que uma medição de 17/08 passou por confirmação sem confirmar nada.
        f"Reranking: {reranker.id if reranker else '**desligado**'}.\n"
        f"Glossário de siglas: {args.glossario if args.glossario else '**nenhum**'}.\n"
        "As métricas são no nível de **documento**: o conjunto dourado aponta arquivos, "
        "e cada documento é ranqueado pelo seu melhor trecho."
    )
    if getattr(args, "entregue", False):
        from .entregue import CaminhoEntregue

        retriever = CaminhoEntregue(interno=retriever)
        contexto += (
            "\n**Caminho medido: o que o cliente MCP recebe** (`buscar_chunks`), e não"
            " o `search` de nível de documento que o resto da série usa. Os quatro sinais"
            " participam dos dois caminhos desde a `F4-P` (25/08/2026): o ranqueador de"
            " nome pontua **documento**, e `BuscaHibrida._nome_por_chunk` entrega essa"
            " contribuição a **um** trecho por documento — o melhor que a fusão já tem"
            " dele, ou o primeiro quando a fusão não tem nenhum. Ver `eval/entregue.py`"
            " e `retrieve/hybrid.py`."
        )

    if getattr(args, "com_grafo", False):
        from .com_grafo import ComSaltoNoGrafo

        estado = store.estatisticas_do_grafo()
        if not estado["mencoes"]:
            # Falhar alto em vez de medir zero: um grafo vazio produziria
            # exatamente os mesmos números do recuperador sem salto, e o relatório
            # diria "o grafo não acrescenta nada" quando o que houve foi não ter
            # grafo. É o modo de falha que mais engana num relatório de ablação.
            raise SystemExit(
                "--com-grafo pedido, mas o grafo desta base está vazio. "
                "Rode `py -m segundocerebro.retrieve.grafo --base <id>` antes."
            )
        retriever = ComSaltoNoGrafo(interno=retriever, store=store)
        contexto += (
            f"\nSalto no grafo: **ligado** — {estado['mencoes']} menções, "
            f"{estado['identificadores']} identificadores em {estado['documentos']} documentos."
        )

    return retriever, f"Métricas F1 — {retriever.nome}", contexto, store, set(universo)


def _conferir_idioma(perguntas, store) -> None:  # noqa: ANN001
    """A anotação de idioma contra o índice, quando há índice.

    As duas espécies são tratadas de forma diferente de propósito. `divergente`
    sai uma a uma, porque cada uma é uma pergunta na fatia errada. `sem_anotacao`
    sai como **contagem**: numa base recém-anotada elas são dezenas, e sessenta
    linhas de aviso idêntico treinam quem lê a ignorar o bloco inteiro — junto
    com a linha de `divergente` que estivesse no meio.

    O baseline por nome não abre índice e não confere nada. É o preço de a fatia
    ser anotação estática, e é o preço certo: a alternativa era o baseline não
    ter fatia nenhuma.
    """
    if store is None:
        return
    divergencias = conferir_idioma(perguntas, idiomas_das_fontes(store, perguntas))
    sem = [d for d in divergencias if d.especie == "sem_anotacao"]
    for d in divergencias:
        if d.especie == "divergente":
            log.error("idioma/divergente: %s — %s", d.id, d.detalhe)
    if sem:
        log.warning(
            "idioma/sem_anotacao: %d perguntas ficam fora da fatia cross-lingual — "
            "`py -m eval.idioma --base <id> --escrever` anota",
            len(sem),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.rodar", description="Avalia um recuperador sobre o conjunto dourado")
    parser.add_argument("--base", help="qual base avaliar (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração; aceita o census.toml legado")
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--out", type=Path, help="grava o relatório markdown")
    parser.add_argument(
        "--retriever",
        default="baseline",
        choices=("baseline", "hibrido", "denso", "bm25"),
        help="baseline por nome de arquivo, ou busca sobre o índice",
    )
    # Sobreposições com default None: `None` é "a base decide". Um default
    # concreto aqui venceria o config.toml em silêncio, e o eval passaria a medir
    # uma configuração que o servidor não roda — que é justamente o que este
    # acoplamento existe para impedir.
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", help="sobrepõe o modelo da base")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--candidatos", type=int, help="sobrepõe os candidatos da base")
    parser.add_argument("--peso-denso", type=float, help="sobrepõe o peso denso da base")
    parser.add_argument(
        "--peso-nome",
        type=float,
        help="peso do ranqueador de nome na fusão — reproduz um ponto de `eval.varredura`",
    )
    parser.add_argument(
        "--rerank",
        nargs="?",
        const=str(CANDIDATOS_PARA_RERANK),
        metavar="N",
        help="sobrepõe o número de candidatos reranqueados (padrão %(const)s). "
        "Sem a flag, vale o que a base configurar",
    )
    parser.add_argument(
        "--sem-rerank",
        action="store_true",
        help="desliga o reranking mesmo que a base o configure — é o braço de ablação",
    )
    parser.add_argument(
        "--nome-por-fonte",
        action="store_true",
        help="peso do ranqueador de nome por tipo do documento candidato — zera na "
        "transcrição de reunião. `F4-P.1`, ver `retrieve/fonte.py`",
    )
    parser.add_argument(
        "--entregue",
        action="store_true",
        help="mede `buscar_chunks` (o que o MCP entrega) em vez de `search` (o que a "
        "série histórica mede). Aditivo: não substitui a série",
    )
    parser.add_argument(
        "--com-grafo",
        action="store_true",
        help="acrescenta um salto de `neighbors` depois da busca — mede o alcance do grafo (F4)",
    )
    parser.add_argument(
        "--sem-nome",
        action="store_true",
        help="desliga o ranqueador por nome de arquivo, deixando só o sinal de conteúdo — "
        "é o braço que mostra quanto do resultado vem do índice e quanto vem do nome",
    )
    parser.add_argument(
        "--glossario",
        type=Path,
        help="expande a consulta por um glossário de siglas antes do bm25 e do ranqueador "
        "de nome — o denso não recebe a expansão, ver `retrieve.glossario`",
    )
    parser.add_argument(
        "--prefixo",
        help="restringe o baseline à mesma subárvore que o índice — sem isso, os dois "
        "ranqueiam universos de tamanho diferente e a comparação mistura escala com qualidade",
    )
    args = parser.parse_args(argv)

    try:
        conf = carregar(args.config, raiz=REPO)
        args.base_cfg = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    cfg = args.base_cfg.censo()
    implicito = args.golden is None and args.base_cfg.dourado is None
    try:
        dourado, aviso = resolver_dourado(args.golden or args.base_cfg.dourado or GOLDEN, implicito=implicito)
    except FileNotFoundError as erro:
        log.error("%s", erro)
        return 2
    if aviso:
        log.warning("%s", aviso)
    perguntas = carregar_perguntas(dourado)
    try:
        conferir_base(perguntas, args.base_cfg.id)
    except ValueError as erro:
        log.error("%s", erro)
        return 2
    retriever, titulo, contexto, store, universo = _montar(args, cfg)

    no_escopo = [p for p in perguntas if p.no_escopo]
    log.info(
        "recuperador: %s | %d perguntas no escopo, de %d",
        retriever.nome,
        len(no_escopo),
        len(perguntas),
    )
    for d in verificar_escopo(perguntas, universo, universo_de_conteudo=store is not None):
        nivel = log.error if d.especie == "silenciosa" else log.warning
        nivel("escopo/%s: %s — %s", d.especie, d.id, d.detalhe)
    _conferir_idioma(perguntas, store)
    # O universo do baseline por nome é o disco, e o do híbrido é o que tem
    # trecho indexado. Os dois são cobertura, mas não a mesma: existir não é ser
    # legível, e o relatório diz qual dos dois mediu.
    cobertura = medir_cobertura(universo, perguntas, de_conteudo=store is not None)
    log.info(
        "cobertura: %.1f%% do universo por pasta, %.1f%% como fonte esperada (%d documentos)",
        100 * cobertura.alcance,
        100 * cobertura.fracao_de_fontes,
        cobertura.universo,
    )

    try:
        resultado = avaliar(retriever, perguntas)
    finally:
        if store is not None:
            store.fechar()

    relatorio = render_markdown(resultado, titulo, contexto, cobertura=cobertura)

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
