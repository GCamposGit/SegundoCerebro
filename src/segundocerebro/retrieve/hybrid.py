"""Hybrid retrieval: dense + lexical, fused with RRF.

Reciprocal Rank Fusion combines rankings by position, not by score. That matters
here because the two scores are not comparable: cosine similarity lives in
[-1, 1] and SQLite's `bm25()` is an unbounded negative number whose scale
depends on the corpus. Normalising them against each other would need a
calibration that changes with every corpus; RRF needs none, which is why it is
the default in the literature and here.

    rrf(doc) = Σ  1 / (k + posição em cada ranking)

Two levels of result:

- `buscar_chunks` returns passages — what the MCP surface exposes, because a
  passage with provenance is what the client can cite.
- `search` collapses to documents, keeping each document's best passage. That is
  the level the golden set is written at, so it is what the F0 harness measures.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..index.embeddings import Embedder
from ..index.store import Store
from ..logger import get_logger
from .familias import chave_de_familia, colapsar
from .fonte import REUNIAO, grupo_de_fonte
from .glossario import Glossario
from .rerank import texto_para_rerank
from .nomes import RanqueadorDeNome

log = get_logger("retrieve.hybrid")

PESO_DENSO = 1.0
"""Peso cheio, escolhido pela varredura de 13/08/2026 (`docs/varredura-pesos-f1.md`).

Era 0,5, e antes disso o denso quase saiu da fusão: media 0,196 de recall@1
contra 0,431 do bm25. Aquele número era **artefato de defeito**, não medida do
modelo — o encoder truncava em 128 tokens e só 19,3% do texto chegava ao vetor
(`docs/truncagem-silenciosa.md`). Com o índice refeito e o `e5-large`, que é
treinado para recuperação, a ordem se inverte: MRR sobe monotonicamente com o
peso do denso em todos os níveis de peso de nome, e a linha `denso = 0` ocupa o
fundo da grade."""

PESO_LEXICAL = 0.25
"""Um quarto do denso — e era 1,0, o peso de referência da fusão.

A varredura de 37 pontos de 13/08/2026 mostrou o bm25 **custando** mais do que
rende quando o denso funciona: das cinco melhores configurações por MRR, quatro
têm `lexical ≤ 0,25`, e as com `lexical = 1` se agrupam no fundo da tabela. Ele
continua valendo o que sempre valeu — casamento exato de código de contrato e
sigla, que é o que resolve caso-armadilha — mas com voz plena afoga o denso nas
perguntas escritas em linguagem natural.

Não é para zerar: `lexical = 0` sobe o MRR (0,769) e derruba as armadilhas para
3 de 6. O peso baixo é o que mantém o sinal exato disponível sem deixá-lo
dominar."""

PESO_NOME = 0.5
"""Metade do denso — e era 1,0.

O nome de arquivo continua sendo sinal forte neste acervo, mas parte do que ele
carregava era compensação por um denso quebrado. Com o denso funcionando, o pico
de MRR sai de `nome = 1,0` para `nome = 0,5`: o sinal passou a ser parcialmente
redundante, e peso demais nele volta a derrubar os casos-armadilha."""

NOME_POR_FONTE = False
"""Se o peso do nome varia por tipo de documento candidato — `F4-P.1`.

**Desligado até a medição decidir.** O braço "antes" de uma ablação tem de ser o
padrão do produto; um padrão que já mudasse mediria a hipótese contra ela mesma.
Ligar isto é o commit de adoção, e ele só existe se o Δ pareado da fatia
`reunião` do corpus sintético alcançar o efeito mínimo declarado no `ROADMAP.md`
sem derrubar o piso do dourado real."""

PESO_NOME_POR_GRUPO = {REUNIAO: 0.0}
"""Peso do ranqueador de nome quando o **documento candidato** é de outro tipo.

Ligado por `nome_por_fonte`, e medido no `F4-P.1`
(`docs/ablacao-f4p1-nome-por-fonte.md`). O que não está aqui usa `peso_nome`.

A afirmação é **estrutural, e não deste acervo**: a transcrição de reunião tem no
nome o assunto e a data, nunca o identificador, porque é assim que gravador de
reunião nomeia arquivo — `Gravacao_2025-03-14_0930.vtt`. Um nome desses casa com
qualquer pergunta que repita a palavra do assunto, e o casamento não discrimina
nada. No documento de escritório é o contrário: o identificador **está** no nome,
e foi por isso que o peso 0,5 sobreviveu a três varreduras.

O zero não veio de busca. Veio de `docs/dourado-cobertura.md`, que já tinha
medido a fatia com o ranqueador desligado: MRR 0,459 contra 0,287. O orçamento do
pacote era de **uma** medição, e uma grade teria sido a segunda.

O grupo é o do **documento candidato**, que é o que se sabe em tempo de consulta
— não o da fonte esperada, que só o dourado conhece. Foi essa a diferença que
tornou otimista o teto de oráculo de +0,032 do `C3.a`."""

K_RRF = 60
"""Constant from the original RRF paper. Damps the weight of top positions so a
single ranker cannot dominate the fusion."""

AGRUPAR_FAMILIAS = True
"""Ligado por padrão desde 16/08/2026, e só depois de medido.

Ablação em `docs/ablacao-familias.md`, condição C: recall@1 0,600 → 0,644,
MRR@10 0,736 → 0,762, casos-armadilha 4 → **5 de 6**, e **zero regressões**. Com
isto a porta 3 da F1, que reprovava, passa.

Primeira entrega da F2, e a mais barata: nenhum modelo novo, nenhum download,
nenhum custo por consulta. O sinal que ela usa — data e número de versão — é
metadado, que nenhum peso de fusão alcançava."""

CANDIDATOS = 200
"""Candidatos por ranking antes da fusão.

Precisa ser generoso porque a métrica é no nível de **documento**: vários chunks
do mesmo arquivo ocupam posições seguidas, então 50 chunks podem colapsar em
poucos documentos distintos e recall@20 fica limitado pelo tamanho do poço, não
pela qualidade do ranqueamento. Custa pouco: LanceDB e FTS5 respondem em
milissegundos."""


@dataclass(frozen=True)
class ChunkAcerto:
    chunk_id: str
    path: str
    score: float
    trilha: str
    locator: str
    texto: str
    origem: str
    """Which rankers found it: `denso`, `lexical` or `denso+lexical`."""
    antes: str = ""
    depois: str = ""
    """Vizinhos do mesmo documento, quando o cliente pede contexto.

    Ficam **fora** de `texto` de propósito. O chunk que casou com a consulta é o
    que tem procedência — id, seção e localizador apontam para ele. Misturar o
    vizinho no mesmo campo faria o cliente citar como achado um texto que o
    ranqueador nunca pontuou."""


def rrf(
    rankings: list[list[str]], k: int = K_RRF, pesos: Sequence[float] | None = None
) -> dict[str, float]:
    """Fuse rankings of ids by position. Absent from a ranking = no contribution.

    Weights exist because equal voice is not neutral — it is a choice, and it was
    the wrong one. Measured on the dev corpus: BM25 alone reached recall@1 = 0,431
    and the dense ranker 0,196; fusing them **unweighted** produced 0,275, worse
    than the better ranker alone. Every position the weak ranker occupies at the
    top is a position stolen from the strong one.
    """
    if pesos is None:
        pesos = [1.0] * len(rankings)
    if len(pesos) != len(rankings):
        raise ValueError(f"{len(rankings)} rankings e {len(pesos)} pesos")

    pontos: dict[str, float] = {}
    for ranking, peso in zip(rankings, pesos):
        if not peso:
            continue
        for posicao, item in enumerate(ranking, start=1):
            pontos[item] = pontos.get(item, 0.0) + peso / (k + posicao)
    return pontos


class BuscaHibrida:
    """Implements the `Retriever` protocol of the F0 harness."""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        *,
        candidatos: int = CANDIDATOS,
        k_rrf: int = K_RRF,
        usar_denso: bool = True,
        usar_lexical: bool = True,
        usar_nome: bool = True,
        peso_denso: float = PESO_DENSO,
        peso_lexical: float = PESO_LEXICAL,
        peso_nome: float = PESO_NOME,
        pesos_fts: tuple[float, float, float] | None = None,
        agrupar_familias: bool = AGRUPAR_FAMILIAS,
        nome_por_fonte: bool = NOME_POR_FONTE,
        glossario: Glossario | None = None,
        reranker=None,  # noqa: ANN001 — `rerank.Reranker`, opcional
    ) -> None:
        if not (usar_denso or usar_lexical or usar_nome):
            raise ValueError("é preciso pelo menos um ranqueador ativo")
        self.store = store
        self.embedder = embedder
        self.candidatos = candidatos
        self.k_rrf = k_rrf
        self.usar_denso = usar_denso
        self.usar_lexical = usar_lexical
        self.usar_nome = usar_nome
        self.peso_denso = peso_denso
        self.peso_lexical = peso_lexical
        self.peso_nome = peso_nome
        # Pesos de coluna do bm25 (`texto`, `trilha`, `caminho`). `None` = padrão
        # 1/1/1 do FTS5, que é o SQL medido de F1 a F4. Ver `C3.a` em
        # `Store.buscar_lexical` e `config.Pesos.colunas_fts`.
        self.pesos_fts = pesos_fts
        self.agrupar_familias = agrupar_familias
        self.nome_por_fonte = nome_por_fonte
        # O denso **não** recebe a expansão de propósito: acrescentar sinônimo ao
        # texto move o vetor da consulta para a média dos termos, e o embedding
        # assimétrico do e5 já resolve sinônimo sozinho. Quem precisa da expansão
        # é quem casa termo com termo — o bm25 e o nome de arquivo.
        self.glossario = glossario or Glossario.vazio()
        self.reranker = reranker
        self._ranqueador_nome: RanqueadorDeNome | None = None
        self._mtimes: dict[str, float] | None = None

    @property
    def _quantos_buscar(self) -> int:
        """Quantos itens montar antes do corte, para o reranker ter o que reordenar."""
        return self.reranker.candidatos if self.reranker is not None else 0

    @property
    def mtimes(self) -> dict[str, float]:
        if self._mtimes is None:
            self._mtimes = self.store.mtimes()
        return self._mtimes

    @classmethod
    def de_base(cls, store: Store, embedder: Embedder, base) -> "BuscaHibrida":  # noqa: ANN001
        """Build from a `config.Base`, so one place decides the weights.

        `base` is duck-typed on purpose: importing `config` here would tie the
        retrieval core to a configuration format it does not need to know. What
        it needs is `.pesos` and `.busca`.

        A weight of zero disables its ranker rather than adding a zero-weighted
        one — `rrf` already skips those, but keeping the flags in agreement is
        what makes `nome` (the property) report the truth.
        """
        return cls(
            store,
            embedder,
            candidatos=base.busca.candidatos,
            k_rrf=base.busca.k_rrf,
            usar_denso=bool(base.pesos.denso),
            usar_lexical=bool(base.pesos.lexical),
            usar_nome=bool(base.pesos.nome),
            peso_denso=base.pesos.denso,
            peso_lexical=base.pesos.lexical,
            peso_nome=base.pesos.nome,
            pesos_fts=getattr(base.pesos, "colunas_fts", None),
            agrupar_familias=getattr(base, "agrupar_familias", AGRUPAR_FAMILIAS),
            glossario=cls.glossario_de(base),
            reranker=cls.reranker_de(base),
        )

    @staticmethod
    def glossario_de(base) -> Glossario:  # noqa: ANN001
        """Glossário da base, ou vazio quando ela não aponta nenhum.

        Ler aqui e não no servidor é o que faz o eval medir o que o servidor
        entrega — a mesma razão pela qual `reranker_de` mora nesta classe.
        """
        caminho = getattr(base, "glossario", None)
        return Glossario.de_arquivo(caminho) if caminho else Glossario.vazio()

    @staticmethod
    def reranker_de(base):  # noqa: ANN001, ANN205
        """Cross-encoder como quarto ranqueador, quando a base o pede.

        Construir é de graça — o modelo abre na primeira consulta, não aqui. É o
        que permite ao eval e ao servidor MCP compartilharem esta porta sem que
        um `--retriever baseline` pague 1 GB de carga por nada.
        """
        peso = getattr(getattr(base, "busca", None), "rerank", None)
        if not peso:
            return None
        from .rerank import Reranker

        return Reranker(candidatos=base.busca.rerank_candidatos, peso=peso)

    @property
    def ranqueador_nome(self) -> RanqueadorDeNome:
        """Built from the paths that have chunks — what search can actually return."""
        if self._ranqueador_nome is None:
            self._ranqueador_nome = RanqueadorDeNome(self.store.paths_com_chunks())
        return self._ranqueador_nome

    @property
    def nome(self) -> str:
        partes = [
            f"{p}×{peso:g}"
            for p, ativo, peso in (
                ("denso", self.usar_denso, self.peso_denso),
                ("bm25", self.usar_lexical, self.peso_lexical),
                ("nome", self.usar_nome, self.peso_nome),
            )
            if ativo and peso
        ]
        sufixo = " (RRF)" if len(partes) > 1 else ""
        return f"{'+'.join(partes)}{sufixo} · {self.embedder.spec.id}"

    def _rankings_de_chunk(self, consulta: str) -> tuple[list[list[str]], list[float], set[str], set[str]]:
        rankings: list[list[str]] = []
        pesos: list[float] = []
        de_denso: set[str] = set()
        de_lexical: set[str] = set()

        if self.usar_denso:
            vetor = self.embedder.embed_consulta(consulta)
            acertos = self.store.buscar_denso(vetor, self.candidatos, model_id=self.embedder.model_id)
            rankings.append([a.id for a in acertos])
            pesos.append(self.peso_denso)
            de_denso = {a.id for a in acertos}

        if self.usar_lexical:
            acertos = self.store.buscar_lexical(
                self.glossario.expandir(consulta), self.candidatos, self.pesos_fts
            )
            rankings.append([a.id for a in acertos])
            pesos.append(self.peso_lexical)
            de_lexical = {a.id for a in acertos}

        return rankings, pesos, de_denso, de_lexical

    def peso_do_nome(self, caminho: str) -> float:
        """Quanto o ranqueador de nome vale para **este** documento candidato.

        Sem `nome_por_fonte` é o mesmo número para todos, que é o que o produto
        fez de F0 a F4 — e o que as três varreduras de peso mediram.
        """
        if not self.nome_por_fonte:
            return self.peso_nome
        return PESO_NOME_POR_GRUPO.get(grupo_de_fonte(caminho), self.peso_nome)

    def _nome_por_doc(self, consulta: str) -> dict[str, float]:
        """A contribuição RRF do ranqueador de nome, por documento — fonte única.

        Os dois caminhos de recuperação consomem isto: `search` soma direto ao
        seu ranking de documentos, e `_nome_por_chunk` reparte para trechos. Era
        código duplicado até a `F4-P.1`, e duplicado é como o sinal de nome ficou
        cinco fases faltando num dos dois lados sem ninguém reparar
        (`eval/entregue.py`). Uma origem, dois consumidores — o mesmo desenho que
        `retrieve/fonte.py` recebeu no mesmo pacote.

        Somar aqui em vez de passar mais um ranking para `rrf` é o que permite
        **peso por item**: `rrf` pondera um ranking inteiro, e o `F4-P.1` precisa
        ponderar cada documento pelo grupo dele. A conta é idêntica à do `rrf`
        (`peso / (k + posição)`), então com `nome_por_fonte` desligado o número
        não muda — e há teste que exige isso.
        """
        if not (self.usar_nome and self.peso_nome):
            return {}

        expandida = self.glossario.expandir(consulta)
        pontos: dict[str, float] = {}
        for posicao, (rel, _) in enumerate(
            self.ranqueador_nome.ranquear(expandida, self.candidatos), start=1
        ):
            peso = self.peso_do_nome(rel)
            if not peso:
                continue
            pontos[rel] = peso / (self.k_rrf + posicao)
        return pontos

    def _nome_por_chunk(self, consulta: str, do_poco: dict[str, float]) -> dict[str, float]:
        """O ranqueador de nome trazido para o nível de trecho — um trecho por documento.

        O nome pontua **documento**, e era por isso que `search` era o único
        caminho onde ele participava: em `buscar_chunks` não havia posição de
        trecho honesta para dar a ele (`eval/entregue.py`). A consequência estava
        medida — o peso do nome é inerte no caminho que o cliente executa, e três
        das doze perguntas cross-lingual do dourado nunca são alcançadas por ele.

        Espalhar a contribuição por **todos** os trechos do documento seria a
        tradução ingênua, e está errada: o documento com mais trechos ganharia
        mais voz, quando o que o nome diz é a posição do documento e nada sobre o
        tamanho dele.

        A regra aqui é o espelho exato da que `search` usa para colapsar. Lá o
        documento fica com a posição do seu melhor trecho; aqui o documento
        entrega **um** trecho — o melhor que a fusão já tem dele, e o primeiro do
        documento quando a fusão não tem nenhum. Esse segundo caso é justamente o
        que o pacote existe para consertar: o documento que só o nome alcança. O
        primeiro trecho é onde estão o cabeçalho e o título, que é o que um
        casamento por nome de arquivo está de fato afirmando.
        """
        pontos: dict[str, float] = {}
        for rel, contribuicao in self._nome_por_doc(consulta).items():
            ids = self.store.ids_de_chunks(rel)
            if not ids:
                # Documento no registro sem nenhum chunk: invisível para a fusão,
                # e o nome não é passe para entrar sem conteúdo indexado.
                continue
            no_poco = [c for c in ids if c in do_poco]
            representante = max(no_poco, key=do_poco.__getitem__) if no_poco else ids[0]
            pontos[representante] = pontos.get(representante, 0.0) + contribuicao
        return pontos

    def expandir_contexto(self, acertos: list[ChunkAcerto], janela: int) -> list[ChunkAcerto]:
        """Anexa os vizinhos de cada acerto — "a resposta estava no parágrafo seguinte".

        O chunker corta por estrutura, e estrutura não coincide com raciocínio: um
        trecho termina no meio de uma enumeração, e a linha que responde está no
        chunk seguinte. Devolver só o trecho que casou obriga o cliente a uma
        segunda chamada para descobrir isso — quando ele desconfia. Quando não
        desconfia, responde com metade.

        Vizinho que já é outro acerto da mesma resposta é omitido: repeti-lo
        gastaria contexto do cliente dizendo duas vezes a mesma coisa, e faria
        parecer que há mais fontes do que há.
        """
        if janela <= 0 or not acertos:
            return acertos

        ja_presentes = {a.chunk_id for a in acertos}
        saida: list[ChunkAcerto] = []
        for acerto in acertos:
            vizinhos = self.store.vizinhos(acerto.chunk_id, janela)
            antes, depois, passou = [], [], False
            for v in vizinhos:
                if v.id == acerto.chunk_id:
                    passou = True
                    continue
                if v.id in ja_presentes:
                    continue
                (depois if passou else antes).append(v.texto)
            saida.append(
                replace(acerto, antes="\n".join(antes).strip(), depois="\n".join(depois).strip())
            )
        return saida

    def buscar_chunks(self, consulta: str, k: int, contexto: int = 0) -> list[ChunkAcerto]:
        rankings, pesos, de_denso, de_lexical = self._rankings_de_chunk(consulta)
        pontos = rrf(rankings, self.k_rrf, pesos)

        # O nome entra **depois** da fusão do poço, e não como mais um ranking:
        # ele precisa saber qual trecho de cada documento a fusão já elegeu para
        # não duplicar o documento no ranking de trechos.
        de_nome = self._nome_por_chunk(consulta, pontos)
        for chunk_id, ponto in de_nome.items():
            pontos[chunk_id] = pontos.get(chunk_id, 0.0) + ponto

        ordenados = sorted(pontos.items(), key=lambda kv: (-kv[1], kv[0]))

        descartados = self._irmaos_superados(ordenados) if self.agrupar_familias else {}
        ordenados = [(c, s) for c, s in ordenados if c not in descartados]
        ordenados = ordenados[: max(k, self._quantos_buscar)]

        saida: list[ChunkAcerto] = []
        for chunk_id, score in ordenados:
            armazenado = self.store.chunk(chunk_id)
            if armazenado is None:  # índice e registro fora de sincronia
                log.warning("chunk %s está no vetorial mas não no registro", chunk_id)
                continue
            origem = "+".join(
                p
                for p, s in (("denso", de_denso), ("lexical", de_lexical), ("nome", de_nome))
                if chunk_id in s
            )
            saida.append(
                ChunkAcerto(
                    chunk_id=chunk_id,
                    path=armazenado.path,
                    score=score,
                    trilha=armazenado.trilha,
                    locator=armazenado.locator,
                    texto=armazenado.texto,
                    origem=origem,
                )
            )

        if self.reranker is not None:
            saida = self.reranker.reordenar(
                consulta, saida, lambda a: texto_para_rerank(a.path, a.trilha, a.texto)
            )
        # Expandir **depois** do corte: buscar vizinho de candidato descartado
        # seria trabalho de banco jogado fora.
        return self.expandir_contexto(saida[:k], contexto)

    def _irmaos_superados(self, ordenados: Sequence[tuple[str, float]]) -> set[str]:
        """Chunks de versões antigas **quando a vigente também foi recuperada**.

        Sem isto, o ganho medido em `search` não chegaria à superfície MCP, que
        devolve passagens e não documentos — seria medir uma coisa e entregar
        outra, que é exatamente o acoplamento que a F3.5 existe para impedir.

        A condição importa: só descarta o irmão antigo se o vigente estiver no
        mesmo ranking. Quando só a versão velha casou com a consulta, devolvê-la
        é melhor que devolver nada — e a procedência dirá que há uma mais nova.
        """
        por_familia: dict[str, list[str]] = {}
        do_chunk: dict[str, str] = {}
        for chunk_id, _ in ordenados:
            armazenado = self.store.chunk(chunk_id)
            if armazenado is None:
                continue
            chave = chave_de_familia(armazenado.path)
            do_chunk[chunk_id] = armazenado.path
            if armazenado.path not in por_familia.setdefault(chave, []):
                por_familia[chave].append(armazenado.path)

        superados: set[str] = set()
        for chave, membros in por_familia.items():
            if len(membros) < 2:
                continue
            vigente = colapsar(membros, self.mtimes)[0][0]
            superados.update(p for p in membros if p != vigente)
        return {c for c, path in do_chunk.items() if path in superados}

    def search(self, consulta: str, k: int) -> list:
        """Documents ranked by fusion at the document level.

        Each chunk ranking is collapsed to documents first (a document takes its
        best chunk's position), then those rankings are fused and the file-name
        contribution (`_nome_por_doc`) is added on top.

        This used to be the *only* path where the file-name ranker participated,
        for the reason stated in `eval/entregue.py`: it scores documents, and
        there was no honest chunk position to give it. `_nome_por_chunk` now
        supplies one — a single chunk per document, mirroring this collapse — so
        the signal exists on the path the MCP client actually executes. This
        method stays the historical series (F0 → F4 was measured here).
        """
        from eval.harness import Hit

        rankings_chunk, pesos, _, _ = self._rankings_de_chunk(consulta)

        rankings_doc: list[list[str]] = []
        pesos_doc: list[float] = []
        melhor_chunk: dict[str, str] = {}

        for ranking, peso in zip(rankings_chunk, pesos):
            documentos: list[str] = []
            for chunk_id in ranking:
                armazenado = self.store.chunk(chunk_id)
                if armazenado is None:
                    continue
                if armazenado.path not in documentos:
                    documentos.append(armazenado.path)
                melhor_chunk.setdefault(armazenado.path, chunk_id)
            rankings_doc.append(documentos)
            pesos_doc.append(peso)

        pontos = rrf(rankings_doc, self.k_rrf, pesos_doc)

        # A mesma origem que `buscar_chunks` consome, somada aqui em vez de
        # entrar como mais um ranking em `rrf`. A conta é a que `rrf` faria; o
        # que muda é poder ponderar **por documento**, que é o que o `F4-P.1`
        # precisa e que um peso de ranking inteiro não expressa.
        for rel, contribuicao in self._nome_por_doc(consulta).items():
            pontos[rel] = pontos.get(rel, 0.0) + contribuicao
        ordenados = sorted(pontos.items(), key=lambda kv: (-kv[1], kv[0]))

        if self.agrupar_familias:
            # Antes do corte em k, e é aí que está o ganho: colapsar depois só
            # esvaziaria o top-k, enquanto colapsar antes promove o vigente para
            # a posição que o irmão antigo tinha conquistado.
            colapsado, _ = colapsar([p for p, _ in ordenados], self.mtimes)
            por_path = dict(ordenados)
            ordenados = [(p, por_path[p]) for p in colapsado]

        ordenados = ordenados[: max(k, self._quantos_buscar)]

        if self.reranker is not None:
            # Reranquear **depois** do colapso de famílias: o cross-encoder não
            # tem como saber qual de cinco cópias é a vigente — isso é metadado —
            # e gastar candidatos com irmãs idênticas desperdiça o orçamento caro.
            def _texto(par: tuple[str, float]) -> str:
                chunk_id = melhor_chunk.get(par[0])
                armazenado = self.store.chunk(chunk_id) if chunk_id else None
                if armazenado is None:
                    # Documento que entrou só pelo ranqueador de nome: não tem
                    # chunk no poço. O nome é o que existe, e é sinal legítimo.
                    return texto_para_rerank(par[0], "", "")
                return texto_para_rerank(armazenado.path, armazenado.trilha, armazenado.texto)

            ordenados = self.reranker.reordenar(consulta, ordenados, _texto)

        ordenados = ordenados[:k]

        saida = []
        for path, score in ordenados:
            chunk_id = melhor_chunk.get(path)
            armazenado = self.store.chunk(chunk_id) if chunk_id else None
            saida.append(Hit(path=path, score=score, trecho=(armazenado.texto[:300] if armazenado else "")))
        return saida
