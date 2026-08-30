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
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path

from ..census import Census, Config, FileEntry, iter_files, relatar_exclusoes
from ..config import ErroDeConfig, carregar
from ..ingest.chunking import CHUNKER_VERSION, Chunk, ChunkConfig, chunk_document
from ..ingest.ocr import VERSAO as OCR_VERSAO
from ..ingest.parsers import parser_version_for
from ..ingest.document import BlockKind, ParseResult, ParseStatus
from ..ingest.natureza import EXTENSOES_DE_TEXTO_BRUTO
from .prioridade import ONDAS, indexaveis, onda_de, ordenar as ordenar_fila
from .prioridade import pasta_de, vigentes as vigentes_de
from ..logger import get_logger
from .embeddings import Embedder
from .gpu_pool import EmbedFila, dispositivos_embed
from .comando import aguardar as aguardar_comando
from .comando import limpar as limpar_comando
from .esforco import ControleEsforco
from .esforco import aplicar as aplicar_esforco
from .esforco import limpar_pedido, na_bateria
from .calibracao import Calibracao, impressao_da_maquina, tipo_de
from .estimativa import CEGO, Cronometro, Estimador, Relogio, decompor, faixa_humana
from .isolamento import parse_isolado
from .orcamento import Recursos, ajustar_ao_vivo, derivar, medir
from .progresso import Publicador
from .progresso import ler as ler_progresso
from .reconciliar import reconciliar
from .cli import LIMITE_CHUNKS_PADRAO as LIMITE_CHUNKS_PADRAO
from .cli import LIMITE_TEXTO_MB_PADRAO as LIMITE_TEXTO_MB_PADRAO
from .cli import _extensoes, _limites_efetivos, construir_parser
from .repesca import STATUS_PARA_REPESCAR as STATUS_PARA_REPESCAR
from .repesca import _AlvoDoMapa, _parser_gravado, _precisa_indexar, _venenoso
from .resultado import PedidoDeParada as PedidoDeParada
from .resultado import Progresso
from .store import ChunkArmazenado, Store
from .trava import TravaDeIndice as TravaDeIndice
from .trava import TravaOcupada as TravaOcupada
from .travas import NOME_DA_TRAVA as NOME_DA_TRAVA  # reexport histórico: painel e testes o pedem daqui

log = get_logger("index.indexer")

LOTE_EMBEDDING = 32
INTERVALO_LOG = 25







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



def _parsear_um(
    path: str,
    limite_planilha_mb: float | None,
    limites_mb: dict[str, float] | None,
    ram_parse_mb: int | None = None,
    indice: str | None = None,
    ocr: bool = False,
):
    """Top-level so ThreadPoolExecutor can pickle it on Windows spawn later.

    Devolve também os segundos gastos: o parse roda em worker, então medir da
    thread principal mediria fila mais parse, e a fila não é custo do formato.
    Um coeficiente `p_parse` calibrado sobre tempo de fila mediria o tamanho do
    pool. Mede o `parse_isolado` inteiro, que é o que de fato custa desde a
    R1.4 — subprocesso incluído.
    """
    t0 = time.perf_counter()
    resultado = parse_isolado(
        path,
        retries=1,
        espera=0.5,
        limite_planilha_mb=limite_planilha_mb,
        limites_mb=limites_mb,
        ram_mb=ram_parse_mb,
        indice=Path(indice) if indice else None,
        ocr=ocr,
    )
    return resultado, time.perf_counter() - t0



def _restante_legivel(estimador: Estimador) -> str:
    """A linha de log do restante: faixa, rótulo de estado e decomposição.

    A decomposição existe porque a cauda domina e o usuário pode agir sobre
    ela: "3.100 pequenos + 3 grandes" diz onde está o tempo, e um número único
    esconde a única alavanca disponível.
    """
    faixa = estimador.restante()
    estado = estimador.estado(faixa)
    texto = faixa_humana(faixa, estado)
    detalhe = decompor(estimador, faixa)
    return f"{texto} — {detalhe}" if detalhe else texto


def _tokens_de(embedder: Embedder, chunks) -> int:  # noqa: ANN001
    """Tokens reais do que vai ao encoder — é a grandeza que custa.

    O tokenizador é nativo e a contagem sai em milissegundos; usar caracteres
    como proxy erraria por até 2× entre formatos (2,55 chars/token no CSV
    contra 3,85 no txt, medidos em 26/08/2026).
    """
    try:
        return sum(embedder.contar_tokens(c.embedding_text) for c in chunks)
    except Exception:  # noqa: BLE001 — contagem é para calibrar, não para indexar
        return sum(c.chars for c in chunks) // 4



def _chunk_de(arm: ChunkArmazenado) -> Chunk:
    trilha = tuple(p for p in arm.trilha.split(" > ") if p) if arm.trilha else ()
    kind = BlockKind(arm.kind) if arm.kind else BlockKind.TEXT
    return Chunk(
        id=arm.id,
        doc_path=arm.path,
        ordinal=arm.ordinal,
        heading_path=trilha,
        text=arm.texto,
        locator=arm.locator,
        kind=kind,
    )


def _cobertura(store: Store, model_id: str, totais: int) -> dict[str, object]:
    por = store.cobertura_modelos()
    com_chunks = sum(por.values())
    finais = por.get(model_id, 0)
    return {
        "com_chunks": com_chunks,
        "final": finais,
        "totais": totais,
        "busca_pct": round(100 * com_chunks / totais) if totais else 0,
        "final_pct": round(100 * finais / totais) if totais else 0,
        "por_modelo": por,
    }


def indexar(
    cfg: Config,
    store: Store,
    embedder: Embedder,
    *,
    chunk_cfg: ChunkConfig | None = None,
    limite: int | None = None,
    lote: int = LOTE_EMBEDDING,
    prefixo: str | None = None,
    so_extensao: frozenset[str] | None = None,
    reconciliar_ao_fim: bool = True,
    forcar_reconciliacao: bool = False,
    limite_planilha_mb: float | None = None,
    limite_texto_mb: float | None = None,
    limites_mb: dict[str, float] | None = None,
    limite_chunks: int | None = None,
    publicar: bool = True,
    esforco: dict[str, object] | None = None,
    parse_workers: int | None = None,
    apenas_onda: int | None = None,
    exigir_exclusoes: bool = False,
    dois_passes: bool = False,
    ram_parse_mb: int | None = None,
    recursos: Recursos | None = None,
    ocr: bool = False,
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
    controle: ControleEsforco | None = None
    if esforco and esforco.get("perfil"):
        controle = ControleEsforco(store.diretorio, str(esforco["perfil"]))
        esforco = controle.como_json()

    medido = recursos if recursos is not None else medir()
    orc = derivar(
        medido,
        str((esforco or {}).get("perfil") or (controle.perfil if controle else "normal")),
        lote_pedido=lote,
    )
    lote = min(max(1, int(lote)), orc.lote_embed)
    if ram_parse_mb is None:
        ram_parse_mb = orc.ram_parse_mb

    trava = TravaDeIndice(store.diretorio)
    execucao = store.iniciar_execucao(
        embedder.model_id,
        CHUNKER_VERSION,
        {"max_chars": chunk_cfg.max_chars, "modelo": embedder.spec.id, "dim": embedder.dim},
    )

    vistos: set[str] = set()

    # Pré-passada só de metadados, para o denominador. `iter_files` enumera o
    # mesmo universo do censo (e alimenta `vistos` para reconciliar). A fila de
    # trabalho — e o estimador — é o subconjunto com parser, na ordem de
    # `prioridade.ordenar`. Contar o bruto de novo reportaria JPEG como trabalho
    # e reabriria o erro dos 45% vs 91%.
    #
    # `--so-extensao` recorta a enumeração (não abre nem registra o que ficou
    # fora) e por isso também desliga a reconciliação, mais abaixo. `--apenas-onda`
    # **não** recorta `vistos`: a onda 4 continua no disco, e reconciliar como se
    # tivesse sumido apagaria o histórico da passada anterior.
    # O `sink` é o que permite conferir a exclusão **antes** de abrir arquivo:
    # sem contagem por regra, uma regra que não casa com nada corre a passada
    # inteira em silêncio e o resultado parece certo (26/08/2026, `F4-P.1`).
    censo_da_passada = Census(attributes_available=(os.name == "nt"))
    enumerados = [
        (
            root,
            [
                a
                for a in iter_files(root, cfg, sink=censo_da_passada)
                if (not prefixo or a.rel.startswith(prefixo))
                and (so_extensao is None or os.path.splitext(a.rel)[1].lower() in so_extensao)
            ],
        )
        for root in cfg.roots
    ]
    exclusoes = relatar_exclusoes(cfg, censo_da_passada)
    for aviso in exclusoes["inertes"]:
        log.warning("%s", aviso)
    if exclusoes["inertes"] and exigir_exclusoes:
        store.encerrar_execucao(execucao, 0, 0, "recusada")
        raise ErroDeConfig(
            "recusando indexar: "
            + str(len(exclusoes["inertes"]))
            + " exclusão(ões) declarada(s) não casou com nada. Corrija a regra ou rode "
            "sem --exigir-exclusoes para indexar com ela inerte"
        )
    if exclusoes["por_regra"]:
        log.info(
            "exclusões por regra: %s",
            " · ".join(f"{k} = {v}" for k, v in sorted(exclusoes["por_regra"].items())),
        )
    for _root, arquivos in enumerados:
        for arquivo in arquivos:
            vistos.add(arquivo.rel)
    trabalho = [
        (root, ordenar_fila(indexaveis(arquivos), apenas_onda=apenas_onda))
        for root, arquivos in enumerados
    ]
    vigentes_fila = vigentes_de([a for _, arquivos in trabalho for a in arquivos])

    # Tabela master: metade de máquina por `fingerprint`, metade de formato por
    # base. O `fingerprint` inclui `model_id` e o chunker de propósito — trocar
    # o encoder invalida os coeficientes do encoder, e reaproveitá-los em
    # silêncio é pior que não ter nenhum.
    gpus_ativas = list(controle.plano.gpu_ids_ativos) if controle is not None else []
    impressao = impressao_da_maquina(embedder.model_id, CHUNKER_VERSION, gpus=gpus_ativas)
    perfil_esforco = str((esforco or {}).get("perfil") or "maximo")
    calib = Calibracao(
        impressao, embedder.model_id, base_id=store.diretorio.name
    ).carregar()
    estimador = Estimador(calibracao=calib, perfil=perfil_esforco)
    estimador.declarar(
        (a.rel, a.size, a.mtime) for _, arquivos in trabalho for a in arquivos
    )
    relogio = Relogio()
    iniciado_em = time.time()
    previo = ler_progresso(store.diretorio) if publicar else None
    if previo and previo.get("status") in {"preparando", "indexando", "pausada", "travada"}:
        relogio.restaurar(
            ativo=float(previo.get("ativo_segundos") or 0),
            parado=float(previo.get("parado_segundos") or 0),
            suspensoes=int(previo.get("suspensoes") or 0),
        )
        if previo.get("iniciado_em"):
            iniciado_em = float(previo["iniciado_em"])
        if isinstance(previo.get("calibracao"), dict):
            estimador.restaurar(previo["calibracao"])
    publicador = (
        Publicador(store.diretorio, estimador, relogio, iniciado_em=iniciado_em)
        if publicar
        else None
    )
    if publicador is not None:
        # O esforço **aplicado**, não o pedido: a tela precisa poder dizer "pedi
        # leve e o sistema não deixou" em vez de mentir que está leve.
        publicador.anotar(
            indice=str(store.diretorio),
            modelo=embedder.model_id,
            esforco=esforco or {},
            recursos=(controle.plano.como_json() if controle else None),
            # A tela mostra o que a exclusão tirou, por regra. Total sozinho não
            # distingue "463 fora por papel" de "regra inerte e zero fora".
            exclusoes=exclusoes,
        )
        publicador.publicar("preparando", forcar=True)
        # O vigia sobe **antes** do primeiro documento: o primeiro embed já é um
        # ponto em que a thread principal pode não voltar por horas, e quem
        # publica não pode ser quem trabalha.
        publicador.iniciar_vigia()

    # O diagnóstico da base sai **sempre**, mesmo sem previsão de tempo: o mapa
    # é informação sobre o acervo e não depende de calibragem nenhuma. É também
    # o que mostra que dois arquivos podem carregar metade dos chunks.
    for linha in estimador.mapa.diagnostico():
        log.info("%s", linha)
    _faixa0 = estimador.restante()
    _estado0 = estimador.estado(_faixa0)
    if _estado0 == CEGO:
        log.info(
            "primeira indexação nesta máquina (%s): sem previsão de tempo até "
            "haver medição local",
            impressao,
        )
    else:
        log.info(
            "%d documentos a considerar · estimativa inicial %s · cobertura %.0f%%",
            estimador.documentos_totais,
            faixa_humana(_faixa0, _estado0),
            100 * estimador.cobertura,
        )
    estimador.abrir_previsao()

    mapa_limites: dict[str, float] = dict(limites_mb or {})
    if limite_texto_mb is not None:
        if limite_texto_mb > 0:
            mapa_limites[".txt"] = limite_texto_mb
        else:
            mapa_limites.pop(".txt", None)

    workers = parse_workers if parse_workers is not None else (
        min(controle.plano.parse_workers, orc.parse_workers) if controle else orc.parse_workers
    )
    workers = max(1, int(workers))
    fila: EmbedFila | None = None
    n_gpus = 0
    gpus: list[str] = []
    if os.environ.get("SEGUNDOCEREBRO_PROVIDER", "").lower() == "cuda":
        from .cuda_runtime import diagnosticar

        diag = diagnosticar(modelo=getattr(embedder.spec, "id", None))
        if not diag.ok:
            raise RuntimeError(diag.mensagem)
        if controle is not None:
            gpus = controle.plano.gpu_ids_ativos
            if not gpus:
                # Perfil deixou todas de fora: cai na CPU. Não deve acontecer
                # com 1 GPU (o plano usa essa placa em leve/normal).
                log.warning("plano de esforço sem GPU ativa; embed na CPU")
        else:
            perfil = str((esforco or {}).get("perfil") or "")
            gpus = dispositivos_embed(reservar_display=perfil == "leve")
        n_gpus = len(gpus)
        if n_gpus == 1:
            os.environ["CUDA_VISIBLE_DEVICES"] = gpus[0]
            log.info("embed na GPU %s (ritmo %.0f%%)", gpus[0], 100 * (
                controle.plano.duty_padrao if controle else 1.0
            ))
    if n_gpus >= 2:
        cache = getattr(embedder, "_cache_dir", Path("models"))
        fila = EmbedFila(gpus, modelo=embedder.spec.id, cache=cache)
        if controle is not None:
            fila.ajustar(
                {g.indice: g.duty for g in controle.plano.gpus},
                {g.indice: g.duty for g in controle.plano.gpus if g.ativo},
            )
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
                versao_parser = parser_version_for(os.path.splitext(arquivo.rel)[1])
                sha_conhecido = estado.sha256 if estado is not None else ""
                if store.deve_pular_quarentena(arquivo.rel, sha_conhecido):
                    progresso.quarentena += 1
                    progresso.registrar_falha("quarentena")
                    estimador.pular(arquivo.rel, arquivo.size)
                    if publicador is not None:
                        publicador.anotar(
                            falhas=progresso.falhas,
                            quarentena=progresso.quarentena,
                        )
                        publicador.publicar()
                    continue
                if (
                    dois_passes
                    and estado is not None
                    and estado.status == ParseStatus.OK.value
                    and estado.n_chunks > 0
                    and estado.chunker == CHUNKER_VERSION
                    and estado.parser == versao_parser
                    and estado.tamanho == arquivo.size
                    and abs(estado.mtime - arquivo.mtime) <= 1e-6
                ):
                    # Pass 1 already wrote FTS. Pass 2 re-embeds without opening the file.
                    continue
                if not _precisa_indexar(estado, arquivo, embedder.model_id, versao_parser):
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

        def _precisa_do_mapa(estado, item) -> bool:  # noqa: ANN001
            """Adaptador para `_precisa_indexar`, que é a regra de verdade.

            O mapa **não** reimplementa o critério: uma regra derivada duas
            vezes é uma regra derivada de dois jeitos, e neste repositório isso
            já produziu número menor e plausível.
            """
            return _precisa_indexar(
                estado,
                _AlvoDoMapa(item.rel, item.tamanho, item.mtime),
                embedder.model_id,
                parser_version_for(os.path.splitext(item.rel)[1]),
            )

        def ciclo() -> None:
            """Fronteira de ciclo: rededuz `restante = censo − registro`.

            Do zero, sempre. Entre ciclos a estimativa usa o último mapa —
            algumas dezenas de documentos desatualizado — e nenhum desvio se
            acumula, porque nada é decrementado.
            """
            if not estimador.mapa.vencido():
                return
            try:
                estimador.recalcular_mapa(store.estados(), _precisa_do_mapa)
            except Exception as erro:  # noqa: BLE001 — mapa velho é melhor que passada morta
                log.debug("mapa não recalculado: %s", erro)

        def registrar_obs(  # noqa: ANN001
            arquivo,
            crono,
            *,
            situacao: str,
            status: str,
            natureza=None,
            n_chunks: int = 0,
            tokens: int = 0,
        ) -> None:
            """Um único lugar onde a medição do documento entra na calibragem.

            Cinco call sites gravavam `perf_counter() - comeco` antes; a decisão
            de o que é tempo confiável, e o que é tipo, tem de morar num lugar
            só, senão a próxima situação nova reintroduz o defeito.
            """
            obs = crono.observacao(
                rel=arquivo.rel,
                tipo=tipo_de(
                    arquivo.rel,
                    digitalizado=getattr(natureza, "digitalizado", None),
                    tem_tabela=getattr(natureza, "tem_tabela", None),
                ),
                mb=max(0.0, arquivo.size / 1_048_576),
                n_chunks=n_chunks,
                tokens=tokens,
                perfil=perfil_esforco,
                situacao=situacao,
                status=status,
            )
            estimador.registrar(obs)
            try:
                store.gravar_medicao(
                    obs,
                    execucao=execucao,
                    fingerprint=impressao,
                    model_id=embedder.model_id,
                )
            except Exception as erro:  # noqa: BLE001 — medir não pode derrubar indexar
                log.debug("medição não gravada para %s: %s", arquivo.rel, erro)

        def gravar_ok(root, arquivo, estado, resultado, chunks, vetores, crono) -> None:  # noqa: ANN001
            store.limpar_quarentena(arquivo.rel)
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
                parser=_parser_gravado(resultado, arquivo.rel),
                natureza=resultado.natureza,
            )
            store.commit()
            crono.marcar("grava")
            progresso.indexados += 1
            if resultado.doc is not None and resultado.doc.meta.get("fonte") == "ocr":
                progresso.ocr += 1
            progresso.chunks += len(chunks)
            registrar_obs(
                arquivo,
                crono,
                situacao="novo" if estado is None else "mudado",
                status=ParseStatus.OK.value,
                natureza=resultado.natureza,
                n_chunks=len(chunks),
                tokens=_tokens_de(embedder, chunks),
            )
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
                    _restante_legivel(estimador),
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
                root, arquivo, estado, resultado, chunks, crono = pend_embed.pop(jid)
                gravar_ok(root, arquivo, estado, resultado, chunks, vetores, crono)
                return True

        def honrar_comando() -> None:
            nonlocal esforco, lote, orc
            pids = list(getattr(fila, "pids", []) or []) if fila is not None else []
            if controle is not None and controle.atualizar(pids=pids):
                esforco = controle.como_json()
                if fila is not None:
                    fila.ajustar(
                        {g.indice: (g.duty if g.ativo else 0.0) for g in controle.plano.gpus},
                        {g.indice: g.duty for g in controle.plano.gpus if g.ativo},
                    )
                if publicador is not None:
                    publicador.anotar(esforco=esforco, recursos=controle.plano.como_json())
                    publicador.publicar(forcar=True)
            fresco = medir()
            novo = ajustar_ao_vivo(orc, fresco)
            if novo.perfil != orc.perfil or novo.lote_embed != lote:
                aplicar_esforco(novo.perfil, pids=pids)
                lote = novo.lote_embed
                orc = novo
                if publicador is not None:
                    publicador.anotar(orcamento=novo.como_json())
            if aguardar_comando(
                store.diretorio,
                relogio=relogio,
                publicar=(
                    (lambda s: publicador.publicar(s, forcar=True)) if publicador is not None else None
                ),
            ):
                interrupcao.pedida = True
            else:
                relogio.fim_pausa()

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
                        onda=onda_de(arquivo, vigentes_rels=vigentes_fila),
                        ondas=ONDAS if apenas_onda is None else 1,
                        pasta=pasta_de(arquivo.rel) or "(raiz)",
                    )
                    publicador.publicar()
                fut = pool.submit(
                    _parsear_um,
                    str(arquivo.path),
                    limite_planilha_mb,
                    mapa_limites or None,
                    ram_parse_mb,
                    str(store.diretorio),
                )
                inflight[fut] = (root, arquivo, estado, time.perf_counter())

        def cancelar_resto() -> None:
            for fut in list(inflight):
                fut.cancel()
            inflight.clear()

        def aplicar(root, arquivo, estado, resultado, crono) -> None:  # noqa: ANN001
            # Guarda de tipo, não paranoia: até a v2 este parâmetro era o
            # `perf_counter()` de partida, e **dois** merges seguidos trouxeram
            # um call site novo passando float — o modo de dois passes e o OCR.
            # Sem isto o sintoma era `AttributeError: 'float' object has no
            # attribute 'marcar'` três quadros abaixo, no meio de uma passada.
            if not isinstance(crono, Cronometro):
                raise TypeError(
                    f"aplicar() espera Cronometro, recebeu {type(crono).__name__}. "
                    "Um call site novo está passando o `comeco` da v1: crie um "
                    "Cronometro(relogio) e credite as etapas nele."
                )
            relogio.tique()
            if resultado.status is not ParseStatus.OK or resultado.doc is None:
                if _venenoso(resultado):
                    item = store.registrar_quarentena(
                        arquivo.rel,
                        hash=resultado.sha256 or (estado.sha256 if estado else ""),
                        motivo=resultado.detail,
                    )
                    progresso.quarentena += 1
                    log.warning(
                        "quarentena (%s, tentativa %d): %s",
                        item.motivo or resultado.status.value,
                        item.tentativas,
                        arquivo.rel,
                    )
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
                    parser=_parser_gravado(resultado, arquivo.rel),
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.registrar_falha(resultado.status.value)
                # Documento que falhou custou tempo e **tem** que sair do
                # restante. Sem isto a barra trava perto do fim e nunca
                # fecha: no corpus real 143 dos 1.601 acabam aqui —
                # `sem_parser`, `vazio`, `travado`, `adiado`.
                crono.marcar("grava")
                registrar_obs(
                    arquivo,
                    crono,
                    situacao="erro",
                    status=ParseStatus.ERROR.value if resultado.status is ParseStatus.ERROR else resultado.status.value,
                    natureza=resultado.natureza,
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
                # O atalho reaproveita os chunks que já estão lá. Se o parser
                # mudou, são chunks de outro texto — reaproveitá-los anularia a
                # repesca e deixaria o documento repescando a cada passada, para
                # sempre, sem nunca mudar. Mixed PDFs are the trap: first wave
                # stores native pages as `ok` with the PDF parser; OCR of the
                # photo pages is a new parse of the same bytes.
                and estado.parser == _parser_gravado(resultado, arquivo.rel)
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
                    parser=_parser_gravado(resultado, arquivo.rel),
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.inalterados += 1
                crono.marcar("grava")
                registrar_obs(
                    arquivo,
                    crono,
                    situacao="revalidado",
                    status=ParseStatus.OK.value,
                    natureza=resultado.natureza,
                )
                if publicador is not None:
                    publicador.publicar()
                return

            outro = store.path_ok_por_sha256(
                resultado.sha256,
                embedder.model_id,
                CHUNKER_VERSION,
                parser_version_for(os.path.splitext(arquivo.rel)[1]),
            )
            if outro and outro != arquivo.rel:
                store.registrar_documento(
                    path=arquivo.rel,
                    raiz=root.name,
                    tamanho=arquivo.size,
                    mtime=arquivo.mtime,
                    sha256=resultado.sha256,
                    status=ParseStatus.DUPLICATE.value,
                    detalhe=f"mesmo conteúdo que {outro}",
                    n_chunks=0,
                    model_id=embedder.model_id,
                    chunker=CHUNKER_VERSION,
                    parser=_parser_gravado(resultado, arquivo.rel),
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.registrar_falha(ParseStatus.DUPLICATE.value)
                crono.marcar("grava")
                registrar_obs(
                    arquivo,
                    crono,
                    situacao="duplicado",
                    status=ParseStatus.DUPLICATE.value,
                    natureza=resultado.natureza,
                )
                if publicador is not None:
                    publicador.anotar(falhas=progresso.falhas, etapa=None, trecho=None, trechos=None)
                    publicador.publicar()
                return

            chunks = chunk_document(resultado.doc, arquivo.rel, chunk_cfg)
            crono.marcar("chunk")
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
                    parser=_parser_gravado(resultado, arquivo.rel),
                    natureza=resultado.natureza,
                )
                store.commit()
                progresso.registrar_falha(ParseStatus.DEFERRED.value)
                crono.marcar("grava")
                registrar_obs(
                    arquivo,
                    crono,
                    situacao="adiado",
                    status=ParseStatus.DEFERRED.value,
                    natureza=resultado.natureza,
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

            ritmo = controle.plano.duty_padrao if controle is not None else 1.0
            if dois_passes:
                store.limpar_quarentena(arquivo.rel)
                store.remover_documento(arquivo.rel)
                store.gravar_textos(chunks)
                store.registrar_documento(
                    path=arquivo.rel,
                    raiz=root.name,
                    tamanho=arquivo.size,
                    mtime=arquivo.mtime,
                    sha256=resultado.sha256,
                    status=ParseStatus.OK.value,
                    n_chunks=len(chunks),
                    model_id="",
                    chunker=CHUNKER_VERSION,
                    parser=_parser_gravado(resultado, arquivo.rel),
                    natureza=resultado.natureza,
                )
                store.commit()
                crono.marcar("grava")
                progresso.indexados += 1
                if resultado.doc is not None and resultado.doc.meta.get("fonte") == "ocr":
                    progresso.ocr += 1
                progresso.chunks += len(chunks)
                # Passe 1 gravou texto e **não** chegou ao encoder. Registrar
                # como caminho completo faria a calibragem aprender que
                # embeddar é grátis: `s_embed` fica nulo e a situação diz qual
                # caminho foi.
                registrar_obs(
                    arquivo,
                    crono,
                    situacao="texto",
                    status=ParseStatus.OK.value,
                    natureza=resultado.natureza,
                    n_chunks=len(chunks),
                )
                if publicador is not None:
                    publicador.anotar(
                        chunks=progresso.chunks,
                        falhas=progresso.falhas,
                        cobertura=_cobertura(store, embedder.model_id, estimador.documentos_totais),
                        etapa=None,
                    )
                    publicador.publicar()
                return
            if fila is not None:
                while len(pend_embed) >= max(1, len(controle.plano.gpu_ids_ativos) if controle else n_gpus):
                    fechar_um_embed(block=True)
                    if interrupcao.pedida:
                        return
                # O embed foi para outro processo: o tempo dele nao passa por
                # esta thread. Descartar o trecho corrente evita creditar
                # espera de fila como custo de encoder.
                crono.descartar()
                jid = fila.submit([c.embedding_text for c in chunks], lote)
                pend_embed[jid] = (root, arquivo, estado, resultado, chunks, crono)
                return
            try:
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks],
                    batch_size=lote,
                    ao_progresso=ao_embed,
                    ritmo=ritmo,
                )
            except TypeError as erro:
                if "ao_progresso" not in str(erro) and "ritmo" not in str(erro):
                    raise
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks], batch_size=lote
                )
            except PedidoDeParada:
                return
            crono.marcar("embed")
            gravar_ok(root, arquivo, estado, resultado, chunks, vetores, crono)

        # O encoder carrega na primeira vez que alguém o toca — e quem toca
        # primeiro é o `contar_tokens` do chunker, então os 9,3 s de carga do
        # `e5-large` iam para o `s_chunk` do **primeiro documento**: uma medição
        # 9.000× a mediana do tipo, atribuída a um arquivo de 52 bytes.
        #
        # Carregar aqui move o custo para fora de qualquer documento, que é onde
        # ele pertence — é custo da passada, não do arquivo.
        #
        # Via `contar_tokens` e não `embed_passagens`: as duas carregam o modelo,
        # mas só a segunda produz um embedding, e uma passada que não tem nada a
        # reprocessar não pode passar a chamar o encoder. E só se houver trabalho:
        # sem fila, nada precisa ser carregado.
        if pendentes:
            try:
                embedder.contar_tokens("aquecimento")
            except Exception as erro:  # noqa: BLE001 — reaparece no primeiro documento
                log.debug("carga antecipada do encoder falhou: %s", erro)

        # Antes de qualquer trabalho: o mapa restante sai do registro, agora que
        # a pré-passada já classificou tudo. Sem esta chamada a primeira
        # estimativa conta como restante o acervo inteiro, inclusive o que
        # acabou de ser pulado.
        ciclo()
        limpar_comando(store.diretorio)
        limpar_pedido(store.diretorio)
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
                root, arquivo, estado, _ = inflight.pop(fut)
                crono = Cronometro(relogio)
                try:
                    resultado, s_parse = fut.result()
                    crono.etapas["parse"] = s_parse
                except Exception as erro:  # noqa: BLE001 — laço de onda: parse hostil vira ERROR, a passada segue
                    log.error("parse falhou em %s: %s", arquivo.rel, erro)
                    resultado = ParseResult(
                        path=str(arquivo.path),
                        status=ParseStatus.ERROR,
                        detail=str(erro)[:500],
                    )
                aplicar(root, arquivo, estado, resultado, crono)
                ciclo()
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

        def embeber_um(path_rel: str) -> None:
            estado = store.estado_documento(path_rel)
            if estado is None or estado.n_chunks <= 0:
                return
            armazenados = store.chunks_de(path_rel)
            if not armazenados:
                return
            chunks = [_chunk_de(a) for a in armazenados]
            arquivo_mtime = estado.mtime

            def ao_embed(feitos: int, total: int) -> None:
                relogio.tique()
                if publicador is not None:
                    publicador.anotar(
                        arquivo=path_rel,
                        etapa="embed",
                        trecho=feitos,
                        trechos=total,
                    )
                    publicador.publicar()
                honrar_comando()
                if interrupcao.pedida:
                    raise PedidoDeParada()

            ritmo = controle.plano.duty_padrao if controle is not None else 1.0
            try:
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks],
                    batch_size=lote,
                    ao_progresso=ao_embed,
                    ritmo=ritmo,
                )
            except TypeError as erro:
                if "ao_progresso" not in str(erro) and "ritmo" not in str(erro):
                    raise
                vetores = embedder.embed_passagens(
                    [c.embedding_text for c in chunks], batch_size=lote
                )
            except PedidoDeParada:
                progresso.interrompido = True
                return
            store.substituir_vetores(chunks, vetores, arquivo_mtime, embedder.model_id)
            store.carimbar_modelo(path_rel, embedder.model_id)
            store.commit()
            if publicador is not None:
                publicador.anotar(
                    cobertura=_cobertura(store, embedder.model_id, estimador.documentos_totais),
                    etapa=None,
                )
                publicador.publicar()

        if ocr and not progresso.interrompido:
            from ..ingest.ocr import backend_disponivel

            if backend_disponivel() is None:
                log.info(
                    "OCR pedido mas nenhum motor disponível — pip install segundocerebro[ocr]"
                )
            else:
                for rel, raiz_nome in store.documentos_para_ocr(OCR_VERSAO):
                    honrar_comando()
                    if interrupcao.pedida:
                        progresso.interrompido = True
                        break
                    root = next((r for r in cfg.roots if r.name == raiz_nome), None)
                    if root is None and len(cfg.roots) == 1:
                        root = cfg.roots[0]
                    if root is None:
                        continue
                    abs_path = str(Path(root.path) / rel.replace("/", os.sep))
                    if not os.path.isfile(abs_path):
                        continue
                    st = os.stat(abs_path)
                    arquivo = FileEntry(
                        root=root,
                        path=abs_path,
                        rel=rel,
                        size=st.st_size,
                        mtime=st.st_mtime,
                        depth=rel.count("/"),
                        top_folder=rel.split("/")[0] if "/" in rel else "",
                        attrs=0,
                    )
                    if publicador is not None:
                        publicador.anotar(arquivo=rel, etapa="ocr", falhas=progresso.falhas)
                        publicador.publicar()
                    # O OCR roda **nesta** thread, não em worker: o
                    # cronômetro pode medir o parse direto. E é o parse mais
                    # caro do indexador, então é o que mais interessa medir.
                    crono_ocr = Cronometro(relogio)
                    resultado = parse_isolado(
                        abs_path,
                        retries=1,
                        espera=0.5,
                        limite_planilha_mb=limite_planilha_mb,
                        limites_mb=mapa_limites or None,
                        ram_mb=ram_parse_mb,
                        indice=store.diretorio,
                        ocr=True,
                    )
                    crono_ocr.marcar("parse")
                    aplicar(
                        root,
                        arquivo,
                        store.estado_documento(rel),
                        resultado,
                        crono_ocr,
                    )

        if dois_passes and not progresso.interrompido:
            for path_rel in store.pendentes_de_modelo(embedder.model_id):
                honrar_comando()
                if interrupcao.pedida:
                    progresso.interrompido = True
                    break
                embeber_um(path_rel)

    # A passada só vale para reconciliar se percorreu o escopo inteiro. Com
    # `--limite` ou interrupção, um caminho ausente de `vistos` significa "não
    # cheguei lá", e não "não existe mais".
    #
    # `so_extensao` entra na mesma conta, e é o caso mais perigoso dos três: um
    # recorte por extensão deixa fora de `vistos` todo documento do prefixo que
    # tem **outra** extensão, e reconciliar isso apagaria do índice tudo que a
    # passada não veio buscar. Filtro de escopo não é evidência de ausência.
    passada_completa = not progresso.interrompido and limite is None and so_extensao is None
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
        if dois_passes and consistencia["diferenca"] < 0:
            log.warning(
                "rascunho: %d trechos ainda sem vetor final — o passe 2 não terminou",
                -consistencia["diferenca"],
            )
        else:
            log.error(
                "ÍNDICE INCONSISTENTE: %d vetores para %d chunks (diferença %+d) — reindexar do zero",
                consistencia["vetores"],
                consistencia["chunks"],
                consistencia["diferenca"],
            )
    progresso.cobertura = store.cobertura_modelos()
    progresso.quarentena = max(progresso.quarentena, int(store.estatisticas().get("quarentena") or 0))
    if publicador is not None:
        publicador.anotar(
            quarentena=progresso.quarentena,
            cobertura=_cobertura(store, embedder.model_id, estimador.documentos_totais),
        )
    store.encerrar_execucao(
        execucao,
        progresso.indexados,
        progresso.chunks,
        "interrompida" if progresso.interrompido else "concluida",
    )

    # Autoteste de calibragem: compara o tempo ativo real com a faixa que foi
    # prevista no início. Sem isto a estimativa é a única parte do projeto sem
    # regressão medida — e a que mais errou.
    try:
        if not progresso.interrompido:
            estimador.fechar_previsao(relogio.ativo)
        removidas = store.podar_medicoes()
        store.commit()
        if removidas:
            log.debug("poda de medições: %d linhas", removidas)
        calib.fechar()
        m = calib.maquina
        log.info(
            "calibragem desta máquina: a_io %.3f s · c0 %.4f s/chunk · "
            "c1 %.5f s/token · g[%s] %.2f · %d observações",
            m.a_io, m.c0, m.c1, perfil_esforco, m.g(perfil_esforco), m.n_obs,
        )
    except Exception as erro:  # noqa: BLE001 — calibrar não pode invalidar a passada
        log.warning("calibragem não pôde ser fechada: %s", erro)
    return progresso


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
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

    from ..config import normalizar_perfil

    perfil = normalizar_perfil(args.perfil or conf.maquina.perfil)
    from .cuda_runtime import aplicar_provider

    aplicar_provider(conf.maquina.provider)
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
            so_extensao=_extensoes(args.so_extensao),
            limite_planilha_mb=args.pular_planilha_acima_de,
            limites_mb=_limites_efetivos(base.limites, args.pular_texto_acima_de),
            limite_chunks=(
                None if args.pular_acima_de_n_chunks <= 0 else args.pular_acima_de_n_chunks
            ),
            esforco=esforco,
            reconciliar_ao_fim=not args.sem_reconciliar,
            forcar_reconciliacao=args.forcar_reconciliacao,
            parse_workers=args.parse_workers,
            apenas_onda=args.apenas_onda,
            exigir_exclusoes=args.exigir_exclusoes,
            dois_passes=bool(args.dois_passes or args.modelo_rascunho or conf.indexacao.ativo),
            ocr=bool(args.ocr or conf.indexacao.ocr),
        )
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    finally:
        estat = store.estatisticas()
        store.fechar()

    log.info("%s", progresso.resumo())
    log.info("índice: %s documentos, %s chunks", estat["documentos"], estat["chunks"])
    if progresso.interrompido:
        log.warning("execução interrompida — rodar de novo retoma de onde parou")
        return 130
    if _deve_ativar_mcp(args):
        try:
            from ..mcp.registrar import ativar as ativar_mcp

            caminho_mcp = ativar_mcp(base, conf=conf)
            log.info(
                "MCP da base '%s' ativo em %s — recarregue o cliente para usar",
                base.id,
                caminho_mcp,
            )
        except Exception as erro:  # noqa: BLE001 — indexação já commitou; MCP é o degrau seguinte
            log.warning(
                "índice da base '%s' pronto, mas o MCP não foi registrado: %s",
                base.id,
                erro,
            )
    return 0


def _deve_ativar_mcp(args: argparse.Namespace) -> bool:
    """Passada completa: o índice é usável, então o cliente tem que enxergar a base.

    `--limite`, `--prefixo` e `--apenas-onda` são recortes. Registrar no meio
    faria o assistente buscar num acervo pela metade e parecer que a base
    'não acha nada'.
    """
    return args.limite is None and not args.prefixo and args.apenas_onda is None


if __name__ == "__main__":
    raise SystemExit(main())
