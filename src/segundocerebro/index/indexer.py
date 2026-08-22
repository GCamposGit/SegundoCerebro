"""Indexing: walk, parse (pipeline), chunk, embed, store — resumable per document.

Parse workers feed a queue. On CPU, embed and commit stay on the main thread
so a crash still loses at most one document. With SEGUNDOCEREBRO_PROVIDER=cuda
and ≥2 GPUs, each card gets its own process (ONNX will not split a session)
and the main process never loads the encoder — e5-large already fills one
6 GB 980 Ti.

    py -m segundocerebro.index.indexer --config census.toml --modelo minilm

Designed for a run that takes hours in the background and can be interrupted:

- Work is committed **per document**, so an interruption costs at most one
  document. Ctrl+C closes the run as `interrompida` and prints where it stopped.
- On resume, a document is skipped only when size, mtime, `model_id` and chunker
  version all match what the registry holds. Switching embedding model therefore
  re-embeds everything (correct — the vectors are incomparable) while a plain
  resume re-processes nothing that is already done.
- Reprocessing a document deletes its chunks and vectors first, so running twice
  never duplicates and never leaves orphans.

That is what makes the 39-hour e5-large run acceptable: it is a background job
in blocks, not an all-or-nothing batch.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..census import Config, iter_files
from ..config import ErroDeConfig, LimitesDeIndexacao, carregar
from ..ingest.chunking import CHUNKER_VERSION, ChunkConfig, chunk_document
from ..ingest.document import ParseResult, ParseStatus
from ..ingest.natureza import EXTENSOES_DE_TEXTO_BRUTO
from ..ingest.reader import parse_file
from ..logger import get_logger
from .embeddings import MODELOS, Embedder
from .gpu_pool import EmbedFila, contar_gpus, dispositivos_embed
from .esforco import PERFIS_DE_ESFORCO
from .comando import aguardar as aguardar_comando
from .comando import limpar as limpar_comando
from .esforco import aplicar as aplicar_esforco
from .esforco import na_bateria
from .estimativa import Estimador, Relogio, faixa_humana
from .progresso import Publicador
from .reconciliar import Reconciliacao, reconciliar
from .store import Store

log = get_logger("index.indexer")

NOME_DA_TRAVA = "indexacao.lock"
"""Nome do arquivo de trava, exportado porque o painel também precisa vê-lo —
medir enquanto o índice está sendo reescrito mede um alvo em movimento."""

LOTE_EMBEDDING = 32
INTERVALO_LOG = 25
LIMITE_TEXTO_MB_PADRAO = LimitesDeIndexacao().txt
"""Espelho de `LimitesDeIndexacao.txt`. A fonte é a config; isto documenta o CLI."""

LIMITE_CHUNKS_PADRAO = 800
"""Safety net for `.txt`/`.csv` that sneak under the byte cap and still explode.

~800 chunks × 1 800 chars is about 1,4 MB of text — a long report, not a dump.
Does not apply to PDF/DOCX/PPTX: those are the knowledge formats, and a cap
here would silently drop timetable-style PDFs on a rebuild."""


class PedidoDeParada(RuntimeError):
    """Cancel or Ctrl+C during embed — the document in flight is not committed."""


@dataclass
class Progresso:
    documentos: int = 0
    pulados: int = 0
    inalterados: int = 0
    indexados: int = 0
    chunks: int = 0
    falhas: dict[str, int] = field(default_factory=dict)
    segundos: float = 0.0
    interrompido: bool = False
    reconciliacao: Reconciliacao | None = None

    def registrar_falha(self, status: str) -> None:
        self.falhas[status] = self.falhas.get(status, 0) + 1

    def resumo(self) -> str:
        partes = [
            f"{self.documentos} documentos vistos",
            f"{self.pulados} já indexados",
            f"{self.inalterados} com conteúdo inalterado",
            f"{self.indexados} processados",
            f"{self.chunks} chunks",
        ]
        if self.falhas:
            partes.append("falhas: " + ", ".join(f"{k}={v}" for k, v in sorted(self.falhas.items())))
        if self.reconciliacao is not None and (self.reconciliacao.houve_mudanca or self.reconciliacao.recusada):
            partes.append(self.reconciliacao.resumo())
        partes.append(f"{self.segundos:.0f}s")
        return " · ".join(partes)


class TravaOcupada(RuntimeError):
    """Outro indexador já está escrevendo neste índice."""


class TravaDeIndice:
    """Exclusive lock on an index directory for the duration of a run.

    Two indexers against the same directory corrupt the vector table: SQLite in
    WAL mode tolerates the concurrency, LanceDB does not, and `remover + add`
    interleaved duplicates every vector — measured once as 13.458 vectors for
    7.214 chunks, with nothing raising an error. The lock is cheap and removes
    the whole class of failure.
    """

    def __init__(self, diretorio: Path) -> None:
        self.caminho = Path(diretorio) / NOME_DA_TRAVA

    @staticmethod
    def _criacao(pid: int) -> float | None:
        """Instante em que o processo nasceu, ou `None` se não dá para saber."""
        try:
            import psutil

            return psutil.Process(pid).create_time()
        except Exception:  # noqa: BLE001 — psutil ausente, processo morto, permissão
            return None

    def marca(self) -> str:
        """`pid,criacao` — o par que sobrevive a um reinício.

        **Só o PID não basta**, e o modo de falha é cruel: depois de reiniciar, o
        sistema recicla números, e `os.kill(pid, 0)` num PID reaproveitado
        responde "vivo". O usuário levaria "outro indexador está escrevendo" com
        nenhum indexador rodando, e o conserto — apagar um arquivo de trava que
        ele não sabe que existe — não se adivinha.

        Encontrado por leitura em 16/08/2026, ao especificar a retomada
        automática da F3.5 bloco D. Não tinha mordido ainda porque a máquina não
        havia reiniciado no meio de um run.
        """
        pid = os.getpid()
        criacao = self._criacao(pid)
        return f"{pid},{criacao:.3f}" if criacao is not None else str(pid)

    def _dono(self) -> tuple[int, float | None]:
        bruto = self.caminho.read_text(encoding="utf-8").strip()
        pid_texto, _, criacao_texto = bruto.partition(",")
        pid = int(pid_texto) if pid_texto.isdigit() else 0
        try:
            return pid, float(criacao_texto) if criacao_texto else None
        except ValueError:
            return pid, None

    def _vivo(self, pid: int, criacao: float | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except Exception:  # noqa: BLE001
            return True
        if criacao is None:
            # Trava do formato antigo, sem instante de criação: não há como
            # distinguir o dono de um PID reciclado, e supor "vivo" é o lado
            # seguro — o preço é uma trava a apagar à mão, e o outro lado seria
            # dois indexadores duplicando cada vetor.
            return True
        atual = self._criacao(pid)
        return atual is None or abs(atual - criacao) < 1.0

    def ocupada(self) -> bool:
        """Há um indexador **vivo** neste índice agora?

        Público porque a retomada precisa saber: base sendo indexada não é base
        pendente, e disparar um segundo indexador é o único jeito conhecido de
        corromper a tabela de vetores.
        """
        if not self.caminho.exists():
            return False
        return self._vivo(*self._dono())

    def __enter__(self) -> "TravaDeIndice":
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid, criacao = self._dono()
            if self._vivo(pid, criacao):
                raise TravaOcupada(
                    f"outro indexador (pid {pid}) está escrevendo em {self.caminho.parent}"
                ) from None
            log.warning("trava órfã do pid %s removida", pid or "?")
            self.caminho.unlink(missing_ok=True)
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(self.marca())
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.caminho.unlink(missing_ok=True)


class _Interrupcao:
    """Turns Ctrl+C into a flag so the current document finishes cleanly."""

    def __init__(self) -> None:
        self.pedida = False
        self._anterior = None

    def __enter__(self) -> "_Interrupcao":
        def tratar(signum, frame):  # noqa: ANN001, ARG001
            if self.pedida:  # segundo Ctrl+C: sai na hora
                raise KeyboardInterrupt
            self.pedida = True
            log.warning("interrupção pedida — encerrando após o documento atual (Ctrl+C de novo força)")

        try:
            self._anterior = signal.signal(signal.SIGINT, tratar)
        except ValueError:  # fora da thread principal
            self._anterior = None
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        if self._anterior is not None:
            signal.signal(signal.SIGINT, self._anterior)


class _FecharFila:
    """Always join GPU embed workers, including when a job raises."""

    def __init__(self, fila: EmbedFila | None) -> None:
        self.fila = fila

    def __enter__(self) -> EmbedFila | None:
        return self.fila

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        if self.fila is not None:
            self.fila.fechar()


STATUS_PARA_REPESCAR = frozenset(
    {
        ParseStatus.LOCKED.value,
        ParseStatus.CLOUD_ONLY.value,
        ParseStatus.ERROR.value,
        ParseStatus.UNSUPPORTED.value,
        ParseStatus.DEFERRED.value,
    }
)
"""Status cuja causa está fora do arquivo, e por isso pode ter mudado sozinha.

Sem isto o documento é pulado para sempre: `_precisa_indexar` compara tamanho,
mtime, modelo e chunker, e um arquivo que estava aberto no Word passa nos quatro.
O ROADMAP promete o oposto — "registrar status `travado` e reindexar na próxima
passada, nunca descartar em silêncio" — e a promessa não estava implementada.
Encontrado em 13/08/2026, com um `.docx` travado durante a reconstrução.

- `travado`: o Word fechou desde então
- `placeholder`: o arquivo pode ter sido hidratado
- `erro`: leitura rasgada é transitória; corrupção de verdade custa uma tentativa
  por passada, e é preço baixo para não abandonar documento em silêncio
- `sem_parser`: quase sempre custo zero, porque o despachante recusa pela
  extensão antes de ler byte — e é o que faz um parser novo alcançar o que ficou
  para trás, já que `CHUNKER_VERSION` não cobre versão de parser

`vazio` fica de fora de propósito: é determinístico dados os mesmos bytes e o
mesmo parser, e repescar custaria reprocessar 12 PDFs digitalizados de até 61
páginas a cada passada, sem nada a ganhar até existir OCR."""


def _precisa_indexar(estado, arquivo, model_id: str) -> bool:  # noqa: ANN001
    if estado is None:
        return True
    if estado.status in STATUS_PARA_REPESCAR:
        return True
    if estado.model_id != model_id or estado.chunker != CHUNKER_VERSION:
        return True
    if estado.tamanho != arquivo.size or abs(estado.mtime - arquivo.mtime) > 1e-6:
        return True
    return False


def _parse_workers_padrao() -> int:
    """CUDA: parse while the GPU embeds. CPU: keep the old sequential loop.

    The encoder must not load in a parse worker — on this desktop that would
    put CUDA into a thread that never uses it and can NaN MiniLM-Q. Workers
    only call `parse_file`. Chunk + embed stay on the main thread.
    """
    if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        n = os.cpu_count() or 4
        return max(2, min(8, n // 2))
    return 1


def _limites_efetivos(
    limites: LimitesDeIndexacao,
    pular_texto_acima_de: float | None,
) -> dict[str, float]:
    """Mapa extensão → MB. A flag de CLI, se vier, só cobre .txt/.csv."""
    mapa = dict(limites.como_mapa())
    if pular_texto_acima_de is None:
        return mapa
    if pular_texto_acima_de <= 0:
        mapa.pop(".txt", None)
        mapa.pop(".csv", None)
        return mapa
    mapa[".txt"] = pular_texto_acima_de
    mapa[".csv"] = pular_texto_acima_de
    return mapa


def _parsear_um(
    path: str,
    limite_planilha_mb: float | None,
    limites_mb: dict[str, float] | None,
):
    """Top-level so ThreadPoolExecutor can pickle it on Windows spawn later."""
    return parse_file(
        path,
        retries=1,
        espera=0.5,
        limite_planilha_mb=limite_planilha_mb,
        limites_mb=limites_mb,
    )


def indexar(
    cfg: Config,
    store: Store,
    embedder: Embedder,
    *,
    chunk_cfg: ChunkConfig | None = None,
    limite: int | None = None,
    lote: int = LOTE_EMBEDDING,
    prefixo: str | None = None,
    reconciliar_ao_fim: bool = True,
    forcar_reconciliacao: bool = False,
    limite_planilha_mb: float | None = None,
    limite_texto_mb: float | None = None,
    limites_mb: dict[str, float] | None = None,
    limite_chunks: int | None = None,
    publicar: bool = True,
    esforco: dict[str, object] | None = None,
    parse_workers: int | None = None,
) -> Progresso:
    """Index the corpus. `prefixo` restricts to a subtree by **filtering**.

    Filtering, not re-rooting: the stored path has to stay relative to the root
    configured in census.toml, because that is what the golden set references.
    Re-rooting silently shifted every path by one folder and made every expected
    source unmatchable — the eval would report zero recall and the blame would
    land on the retriever.
    """
    chunk_cfg = chunk_cfg or ChunkConfig()
    if chunk_cfg.max_tokens is None:
        # o orçamento real vem do tokenizador do modelo, não de caracteres
        chunk_cfg = replace(
            chunk_cfg, max_tokens=embedder.orcamento_tokens, contar_tokens=embedder.contar_tokens
        )
    progresso = Progresso()
    inicio = time.perf_counter()

    trava = TravaDeIndice(store.diretorio)
    execucao = store.iniciar_execucao(
        embedder.model_id,
        CHUNKER_VERSION,
        {"max_chars": chunk_cfg.max_chars, "modelo": embedder.spec.id, "dim": embedder.dim},
    )

    vistos: set[str] = set()

    # Pré-passada só de metadados, para o denominador. É o **mesmo** `iter_files`
    # que o laço consome, e é essa igualdade que impede o erro que custou dois
    # relatórios em 15/08/2026: o censo conta 3.154 arquivos, o indexador processa
    # 1.601, e usar a contagem bruta reporta 45% quando o real é 91%. Contar duas
    # vezes é como as duas contas divergem.
    #
    # Custa segundos e nenhuma abertura de arquivo — `iter_files` já lê só
    # metadado, o que também é o que impede hidratar placeholder de nuvem.
    trabalho = [
        (root, [a for a in iter_files(root, cfg) if not prefixo or a.rel.startswith(prefixo)])
        for root in cfg.roots
    ]
    estimador = Estimador()
    estimador.declarar((a.rel, a.size) for _, arquivos in trabalho for a in arquivos)
    relogio = Relogio()
    publicador = Publicador(store.diretorio, estimador, relogio) if publicar else None
    if publicador is not None:
        # O esforço **aplicado**, não o pedido: a tela precisa poder dizer "pedi
        # leve e o sistema não deixou" em vez de mentir que está leve.
        publicador.anotar(
            indice=str(store.diretorio), modelo=embedder.model_id, esforco=esforco or {}
        )
        publicador.publicar("preparando", forcar=True)
    log.info(
        "%d documentos a considerar · estimativa inicial %s",
        estimador.documentos_totais,
        faixa_humana(estimador.restante()),
    )

    mapa_limites: dict[str, float] = dict(limites_mb or {})
    if limite_texto_mb is not None:
        if limite_texto_mb > 0:
            mapa_limites[".txt"] = limite_texto_mb
            mapa_limites[".csv"] = limite_texto_mb
        else:
            mapa_limites.pop(".txt", None)
            mapa_limites.pop(".csv", None)

    workers = parse_workers if parse_workers is not None else _parse_workers_padrao()
    workers = max(1, int(workers))
    fila: EmbedFila | None = None
    n_gpus = 0
    if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        if getattr(embedder.spec, "id", None) == "minilm":
            raise RuntimeError(
                "MiniLM quantizado (onnx-Q) devolve NaN no CUDA deste hardware. "
                "Use --modelo e5-large; o provider não entra em model_id"
            )
        perfil = str((esforco or {}).get("perfil") or "")
        reservar = perfil == "leve"
        gpus = dispositivos_embed(reservar_display=reservar)
        n_gpus = len(gpus)
        if n_gpus == 1:
            # One selected card: pin ORT to it. With two cards in `leve` this
            # is the one without a monitor; with a single card it is that card,
            # display or not.
            os.environ["CUDA_VISIBLE_DEVICES"] = gpus[0]
            log.info("embed na GPU %s", gpus[0])
    if n_gpus >= 2:
        # Main must not load the encoder: e5-large already fills one 6 GB card.
        cache = getattr(embedder, "_cache_dir", Path("models"))
        fila = EmbedFila(gpus, modelo=embedder.spec.id, cache=cache)
        chunk_cfg = replace(chunk_cfg, contar_tokens=None)
        log.info("pipeline: %d parse worker(s) · %d GPUs de embed (%s)", workers, n_gpus, ",".join(gpus))
    else:
        log.info("pipeline: %d parse worker(s) · embed na thread principal", workers)

    pend_embed: dict = {}

    with (
        _FecharFila(fila),
        trava,
        _Interrupcao() as interrupcao,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        pendentes: list[tuple] = []
        for root, arquivos in trabalho:
            for arquivo in arquivos:
                # Registrado antes de qualquer decisão de pular: a reconciliação
                # pergunta "este caminho existe em disco?", e a resposta é sim
                # mesmo quando o documento já estava indexado e íntegro.
                vistos.add(arquivo.rel)
                progresso.documentos += 1
                estado = store.estado_documento(arquivo.rel)
                if not _precisa_indexar(estado, arquivo, embedder.model_id):
                    progresso.pulados += 1
                    # Sai do restante sem entrar na calibragem: pular é grátis, e
                    # deixar isso ensinar a vazão faria a estimativa prometer um
                    # ritmo que só existe enquanto há documentos já indexados.
                    estimador.pular(arquivo.rel, arquivo.size)
                    if publicador is not None:
                        publicador.publicar()
                    continue
                pendentes.append((root, arquivo, estado))

        inflight: dict = {}
        proximo = 0
        teto_fila = max(workers * 2, 2)

        def gravar_ok(root, arquivo, estado, resultado, chunks, vetores, comeco) -> None:  # noqa: ANN001
            store.remover_documento(arquivo.rel)
            store.gravar_chunks(chunks, vetores, arquivo.mtime, embedder.model_id)
            store.registrar_documento(
                path=arquivo.rel,
                raiz=root.name,
                tamanho=arquivo.size,
                mtime=arquivo.mtime,
                sha256=resultado.sha256,
                status=ParseStatus.OK.value,
                n_chunks=len(chunks),
                model_id=embedder.model_id,
                chunker=CHUNKER_VERSION,
                natureza=resultado.natureza,
            )
            store.commit()
            progresso.indexados += 1
            progresso.chunks += len(chunks)
            estimador.registrar(arquivo.rel, arquivo.size, time.perf_counter() - comeco)
            if publicador is not None:
                publicador.anotar(
                    chunks=progresso.chunks,
                    falhas=progresso.falhas,
                    etapa=None,
                    trecho=None,
                    trechos=None,
                )
                publicador.publicar()
            if progresso.indexados % INTERVALO_LOG == 0:
                decorrido = time.perf_counter() - inicio
                ritmo = progresso.chunks / decorrido if decorrido else 0
                log.info(
                    "%d documentos, %d chunks, %.1f chunks/s · faltam %s",
                    progresso.indexados,
                    progresso.chunks,
                    ritmo,
                    faixa_humana(estimador.restante()),
                )

        def fechar_um_embed(*, block: bool) -> bool:
            if fila is None or not pend_embed:
                return False
            while True:
                got = fila.receber(timeout=2.0 if block else 0.05)
                if got is None:
                    if not block:
                        return False
                    relogio.tique()
                    if publicador is not None:
                        publicador.anotar(etapa="embed")
                        publicador.publicar()
                    honrar_comando()
                    if interrupcao.pedida:
                        return False
                    continue
                jid, vetores = got
                root, arquivo, estado, resultado, chunks, comeco = pend_embed.pop(jid)
                gravar_ok(root, arquivo, estado, resultado, chunks, vetores, comeco)
                return True

        def honrar_comando() -> None:
            if aguardar_comando(
                store.diretorio,
                relogio=relogio,
                publicar=(
                    (lambda s: publicador.publicar(s, forcar=True)) if publicador is not None else None
                ),
            ):
                interrupcao.pedida = True

        def preencher() -> None:
            nonlocal proximo
            honrar_comando()
            while (
                proximo < len(pendentes)
                and len(inflight) < teto_fila
                and not interrupcao.pedida
                and (limite is None or progresso.indexados < limite)
            ):
                root, arquivo, estado = pendentes[proximo]
                proximo += 1
                if publicador is not None:
                    publicador.anotar(
                        arquivo=arquivo.rel,
                        etapa="parse",
                        trecho=None,
                        trechos=None,
                        falhas=progresso.falhas,
                    )
                    publicador.publicar()
                fut = pool.submit(
                    _parsear_um,
                    str(arquivo.path),
                    limite_planilha_mb,
                    mapa_limites or None,
                )
                inflight[fut] = (root, arquivo, estado, time.perf_counter())

        def cancelar_resto() -> None:
            for fut in list(inflight):
                fut.cancel()
            inflight.clear()

        def aplicar(root, arquivo, estado, resultado, comeco) -> None:  # noqa: ANN001
            relogio.tique()
            if resultado.status is not ParseStatus.OK or resultado.doc is None:
                store.remover_documento(arquivo.rel)
                store.registrar_documento(
                    path=arquivo.rel,
                    raiz=root.name,
                    tamanho=arquivo.size,
                    mtime=arquivo.mtime,
                    sha256=resultado.sha256,
                    status=resultado.status.value,
                    detalhe=resultado.detail[:500],
                    model_id=embedder.model_id,
                    chunker=CHUNKER_VERSION,
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.registrar_falha(resultado.status.value)
                # Documento que falhou custou tempo e **tem** que sair do
                # restante. Sem isto a barra trava perto do fim e nunca
                # fecha: no corpus real 143 dos 1.601 acabam aqui —
                # `sem_parser`, `vazio`, `travado`, `adiado`.
                estimador.registrar(
                    arquivo.rel, arquivo.size, time.perf_counter() - comeco
                )
                if publicador is not None:
                    publicador.anotar(falhas=progresso.falhas, etapa=None, trecho=None, trechos=None)
                    publicador.publicar()
                return

            # conteúdo idêntico com mtime novo (sincronização, restauração,
            # cópia de volta): reembeddar seria pagar o caro por nada
            if (
                estado is not None
                and estado.sha256
                and estado.sha256 == resultado.sha256
                and estado.status == ParseStatus.OK.value
                and estado.model_id == embedder.model_id
                and estado.chunker == CHUNKER_VERSION
            ):
                store.registrar_documento(
                    path=arquivo.rel,
                    raiz=root.name,
                    tamanho=arquivo.size,
                    mtime=arquivo.mtime,
                    sha256=resultado.sha256,
                    status=ParseStatus.OK.value,
                    n_chunks=estado.n_chunks,
                    model_id=embedder.model_id,
                    chunker=CHUNKER_VERSION,
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.inalterados += 1
                estimador.registrar(
                    arquivo.rel, arquivo.size, time.perf_counter() - comeco
                )
                if publicador is not None:
                    publicador.publicar()
                return

            chunks = chunk_document(resultado.doc, arquivo.rel, chunk_cfg)
            ext = os.path.splitext(arquivo.rel)[1].lower()
            if (
                limite_chunks is not None
                and ext in EXTENSOES_DE_TEXTO_BRUTO
                and len(chunks) > limite_chunks
            ):
                store.remover_documento(arquivo.rel)
                store.registrar_documento(
                    path=arquivo.rel,
                    raiz=root.name,
                    tamanho=arquivo.size,
                    mtime=arquivo.mtime,
                    sha256=resultado.sha256,
                    status=ParseStatus.DEFERRED.value,
                    detalhe=(
                        f"{len(chunks)} trechos, acima do limite de {limite_chunks} para {ext}"
                    )[:500],
                    model_id=embedder.model_id,
                    chunker=CHUNKER_VERSION,
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.registrar_falha(ParseStatus.DEFERRED.value)
                estimador.registrar(
                    arquivo.rel, arquivo.size, time.perf_counter() - comeco
                )
                if publicador is not None:
                    publicador.anotar(falhas=progresso.falhas, etapa=None, trecho=None, trechos=None)
                    publicador.publicar()
                log.info(
                    "adiado: %s gerou %d trechos (limite %d)",
                    arquivo.rel,
                    len(chunks),
                    limite_chunks,
                )
                return

            def ao_embed(feitos: int, total: int) -> None:
                relogio.tique()
                if publicador is not None:
                    publicador.anotar(
                        arquivo=arquivo.rel,
                        etapa="embed",
                        trecho=feitos,
                        trechos=total,
                    )
                    publicador.publicar()
                honrar_comando()
                if interrupcao.pedida:
                    raise PedidoDeParada()

            if fila is not None:
                while len(pend_embed) >= n_gpus:
                    fechar_um_embed(block=True)
                    if interrupcao.pedida:
                        return
                jid = fila.submit([c.embedding_text for c in chunks], lote)
                pend_embed[jid] = (root, arquivo, estado, resultado, chunks, comeco)
                return
            try:
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks],
                    batch_size=lote,
                    ao_progresso=ao_embed,
                )
            except TypeError as erro:
                if "ao_progresso" not in str(erro):
                    raise
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks], batch_size=lote
                )
            except PedidoDeParada:
                return
            gravar_ok(root, arquivo, estado, resultado, chunks, vetores, comeco)

        limpar_comando(store.diretorio)
        preencher()
        while inflight:
            concluidos, _ = wait(inflight, timeout=2.0, return_when=FIRST_COMPLETED)
            relogio.tique()
            if publicador is not None:
                publicador.publicar()
            honrar_comando()
            if interrupcao.pedida:
                progresso.interrompido = True
                cancelar_resto()
                break
            if not concluidos:
                continue
            for fut in concluidos:
                root, arquivo, estado, comeco = inflight.pop(fut)
                try:
                    resultado = fut.result()
                except Exception as erro:  # noqa: BLE001
                    log.error("parse falhou em %s: %s", arquivo.rel, erro)
                    resultado = ParseResult(
                        path=str(arquivo.path),
                        status=ParseStatus.ERROR,
                        detail=str(erro)[:500],
                    )
                aplicar(root, arquivo, estado, resultado, comeco)
                fechar_um_embed(block=False)
                honrar_comando()
                if limite is not None and progresso.indexados >= limite:
                    cancelar_resto()
                    break
                if interrupcao.pedida:
                    progresso.interrompido = True
                    cancelar_resto()
                    break
            if interrupcao.pedida or (limite is not None and progresso.indexados >= limite):
                break
            preencher()
        if interrupcao.pedida:
            progresso.interrompido = True
        while pend_embed and not progresso.interrompido:
            fechar_um_embed(block=True)
            if interrupcao.pedida:
                progresso.interrompido = True
                break

    # A passada só vale para reconciliar se percorreu o escopo inteiro. Com
    # `--limite` ou interrupção, um caminho ausente de `vistos` significa "não
    # cheguei lá", e não "não existe mais".
    passada_completa = not progresso.interrompido and limite is None
    progresso.reconciliacao = reconciliar(
        store,
        vistos,
        prefixo=prefixo,
        completa=passada_completa and reconciliar_ao_fim,
        forcar=forcar_reconciliacao,
    )

    progresso.segundos = time.perf_counter() - inicio
    if publicador is not None:
        relogio.tique()
        # O arquivo **fica** com o estado final: apagá-lo faria "terminou às
        # 02:46" virar indistinguível de "nunca rodou".
        publicador.anotar(arquivo=None, resumo=progresso.resumo())
        publicador.encerrar("interrompida" if progresso.interrompido else "concluida")
    consistencia = store.verificar_consistencia()
    if consistencia["diferenca"]:
        log.error(
            "ÍNDICE INCONSISTENTE: %d vetores para %d chunks (diferença %+d) — reindexar do zero",
            consistencia["vetores"],
            consistencia["chunks"],
            consistencia["diferenca"],
        )
    store.encerrar_execucao(
        execucao,
        progresso.indexados,
        progresso.chunks,
        "interrompida" if progresso.interrompido else "concluida",
    )
    return progresso


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.index.indexer")
    parser.add_argument("--base", help="qual base indexar (ver config.toml)")
    parser.add_argument(
        "--config",
        type=Path,
        help="arquivo de configuração; aceita config.toml e o census.toml legado. "
        "Ausente: procura config.toml, depois census.toml",
    )
    # As sobreposições abaixo têm default None de propósito: `None` é "a base
    # decide", e um default concreto aqui venceria silenciosamente o arquivo.
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", choices=sorted(MODELOS), help="sobrepõe o modelo da base")
    parser.add_argument("--limite", type=int, help="para depois de N documentos processados")
    parser.add_argument("--max-chars", type=int, help="sobrepõe o chunking da base")
    parser.add_argument("--threads", type=int, help="sobrepõe as threads da máquina")
    parser.add_argument(
        "--perfil",
        choices=PERFIS_DE_ESFORCO,
        help="nível de esforço; sobrepõe o [maquina] perfil. 'leve' cede a vez ao "
        "que está em primeiro plano e recusa rodar na bateria",
    )
    parser.add_argument(
        "--parse-workers",
        type=int,
        dest="parse_workers",
        help="threads de parse. Padrão: 1 na CPU, metade dos núcleos (2–8) com "
        "SEGUNDOCEREBRO_PROVIDER=cuda. Com 2+ GPUs o embed sai da principal "
        "(um processo por placa); senão fica na thread principal",
    )
    parser.add_argument("--prefixo", help="indexa só caminhos que começam com este prefixo")
    parser.add_argument(
        "--pular-planilha-acima-de",
        type=float,
        metavar="MB",
        help="adia planilhas cujo XML de abas passe deste tamanho, em MB. O preditor é o XML "
        "descompactado, não o tamanho em disco: 17,9 MB comprimidos podem esconder 124 MB em 69 "
        "abas e custar duas horas. Fica registrado como `adiado` e é repescado numa passada sem o limite",
    )
    parser.add_argument(
        "--pular-texto-acima-de",
        type=float,
        metavar="MB",
        default=None,
        help=(
            "adia .txt/.csv maiores que isto, em MB, sem abrir o arquivo. "
            "Ausente: vale o [base.limites] (padrão 2 MB). 0 desliga. Fica como "
            "`adiado` e é repescado numa passada sem o limite"
        ),
    )
    parser.add_argument(
        "--pular-acima-de-n-chunks",
        type=int,
        metavar="N",
        default=LIMITE_CHUNKS_PADRAO,
        help=(
            f"adia .txt/.csv que gerem mais de N trechos (padrão: {LIMITE_CHUNKS_PADRAO}). "
            "0 desliga. O teto de megabytes pega o caso comum; este é a rede de segurança. "
            "Não se aplica a PDF/DOCX/PPTX"
        ),
    )
    parser.add_argument(
        "--sem-reconciliar",
        action="store_true",
        help="não remove do índice os documentos que sumiram do disco; deixa fantasma para trás",
    )
    parser.add_argument(
        "--forcar-reconciliacao",
        action="store_true",
        help="reconcilia mesmo quando a proporção a remover passa da trava de segurança — "
        "use só depois de conferir que a raiz e o prefixo estão certos",
    )
    args = parser.parse_args(argv)

    try:
        conf = carregar(args.config)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    cfg = base.censo()
    if not cfg.roots:
        log.error("a base '%s' não declara nenhuma raiz — nada a indexar", base.id)
        return 2

    indice = args.indice or base.indice
    threads = args.threads if args.threads is not None else conf.maquina.threads_efetivos()
    max_chars = args.max_chars if args.max_chars is not None else base.chunking.max_chars

    perfil = args.perfil or conf.maquina.perfil
    esforco = aplicar_esforco(perfil)
    if perfil == "leve" and na_bateria():
        # Quem escolheu "leve" escolheu não sentir a indexação, e 39 h de
        # trabalho na bateria queimam a carga e esquentam o notebook.
        log.warning("perfil leve na bateria: ligue na tomada, ou use --perfil normal")
        return 3

    embedder = Embedder(args.modelo or base.modelo, threads=threads)
    store = Store(indice, embedder.dim)
    log.info(
        "base '%s' | modelo %s (%d dim) | índice em %s | %d threads",
        base.id,
        embedder.model_id,
        embedder.dim,
        indice,
        threads,
    )

    try:
        progresso = indexar(
            cfg,
            store,
            embedder,
            chunk_cfg=ChunkConfig(
                max_chars=max_chars,
                min_chars=base.chunking.min_chars,
                overlap_chars=base.chunking.overlap_chars,
            ),
            limite=args.limite,
            lote=conf.maquina.lote,
            prefixo=args.prefixo,
            limite_planilha_mb=args.pular_planilha_acima_de,
            limites_mb=_limites_efetivos(base.limites, args.pular_texto_acima_de),
            limite_chunks=(
                None if args.pular_acima_de_n_chunks <= 0 else args.pular_acima_de_n_chunks
            ),
            esforco=esforco,
            reconciliar_ao_fim=not args.sem_reconciliar,
            forcar_reconciliacao=args.forcar_reconciliacao,
            parse_workers=args.parse_workers,
        )
    finally:
        estat = store.estatisticas()
        store.fechar()

    log.info("%s", progresso.resumo())
    log.info("índice: %s documentos, %s chunks", estat["documentos"], estat["chunks"])
    if progresso.interrompido:
        log.warning("execução interrompida — rodar de novo retoma de onde parou")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
