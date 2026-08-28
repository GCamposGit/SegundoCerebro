"""Watch a base's roots and reindex what changed.

A process apart from the indexer loop. Create/modify become
`indexar(..., prefixo=)` — the same call the CLI uses for a subtree. Delete
becomes `Store.esquecer_documento`. Pause and cancel stay `comando.txt`; the
bar stays `progresso.json`. No new IPC.

Two watchers on the same index refuse. That lock is `watcher.lock`, not
`indexacao.lock`: holding the indexer lock for the lifetime of this process
would make the inner `indexar` raise `TravaOcupada` against itself.

What changed while this process was off is a different class — that is the
USN Journal layer (`R5.1`), not this module. The honest recovery is one
`indexar` pass.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

from ..census import Config, caminho_estendido, is_cloud_only
from ..config import ErroDeConfig, carregar
from ..ingest.parsers import parser_for
from ..logger import get_logger
from .comando import CANCELAR, PAUSAR
from .comando import ler as ler_comando
from .indexer import TravaOcupada, indexar
from .store import Store

log = get_logger("index.watcher")

NOME_DA_TRAVA = "watcher.lock"
DEBOUNCE_PADRAO = 0.8


class ObservadorOcupado(RuntimeError):
    """Outro observador já está neste índice."""


class TravaDeObservador:
    """Exclusive lock so two watchers do not share an index.

    Same pid+criação protocol as `TravaDeIndice`. A different file, on purpose.
    """

    def __init__(self, diretorio: Path) -> None:
        self.caminho = Path(diretorio) / NOME_DA_TRAVA

    @staticmethod
    def _criacao(pid: int) -> float | None:
        try:
            import psutil

            return psutil.Process(pid).create_time()
        except Exception:  # noqa: BLE001 — psutil ausente: criação do PID desconhecida
            return None

    def marca(self) -> str:
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
        except Exception:  # noqa: BLE001 — PID recusado sem OSError: supor vivo
            return True
        if criacao is None:
            return True
        atual = self._criacao(pid)
        return atual is None or abs(atual - criacao) < 1.0

    def __enter__(self) -> "TravaDeObservador":
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid, criacao = self._dono()
            if self._vivo(pid, criacao):
                raise ObservadorOcupado(
                    f"outro observador (pid {pid}) já está em {self.caminho.parent}"
                ) from None
            log.warning("trava órfã do observador pid %s removida", pid or "?")
            self.caminho.unlink(missing_ok=True)
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(self.marca())
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.caminho.unlink(missing_ok=True)


class Observador:
    """Queue of paths whose debounce expired, drained into `indexar`."""

    def __init__(
        self,
        cfg: Config,
        store: Store,
        embedder: object,
        *,
        debounce_s: float = DEBOUNCE_PADRAO,
        indexar_fn: object | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.embedder = embedder
        self.debounce_s = debounce_s
        self._indexar = indexar_fn or indexar
        # path → (quando, acao). Last event wins so a Word atomic save
        # (delete + create in the same second) indexes the new file instead
        # of forgetting it.
        self._pendentes: dict[str, tuple[float, str]] = {}
        self._fila = threading.Lock()
        self._trava: TravaDeObservador | None = None

    def ocupar(self) -> None:
        self._trava = TravaDeObservador(self.store.diretorio)
        self._trava.__enter__()

    def soltar(self) -> None:
        if self._trava is not None:
            self._trava.__exit__(None, None, None)
            self._trava = None

    def prefixo_de(self, path: Path) -> str | None:
        """Relative path with `/`, or None if the file is outside every root."""
        try:
            alvo = path.resolve()
        except OSError:
            return None
        for root in self.cfg.roots:
            try:
                rel = alvo.relative_to(Path(root.path).resolve())
            except ValueError:
                continue
            return rel.as_posix()
        return None

    def candidato(self, path: Path) -> bool:
        """True when this event should become an index pass.

        Cloud placeholders are refused here, by `stat` attributes, so the
        watcher never opens them — `reader.py` would also refuse, but that
        still `stat`s after the event already woke us. Skipping first keeps
        the hydration trigger off the path.
        """
        nome = path.name
        if self.cfg.excluded_file(nome):
            return False
        if parser_for(path.suffix) is None:
            return False
        if self.prefixo_de(path) is None:
            return False
        try:
            st = os.stat(caminho_estendido(str(path)))
        except OSError:
            return False
        if is_cloud_only(getattr(st, "st_file_attributes", 0)):
            log.info("placeholder de nuvem, observador não abre: %s", path)
            return False
        if not os.path.isfile(caminho_estendido(str(path))):
            return False
        return True

    def enfileirar(self, path: Path) -> None:
        if not self.candidato(path):
            return
        with self._fila:
            self._pendentes[str(path)] = (time.monotonic(), "indexar")

    def enfileirar_apagado(self, path: Path) -> None:
        """Queue a path that left the disk. Never opens the file."""
        if self.cfg.excluded_file(path.name):
            return
        if parser_for(path.suffix) is None:
            return
        if self.prefixo_de(path) is None:
            return
        with self._fila:
            self._pendentes[str(path)] = (time.monotonic(), "esquecer")

    def drenar(self, agora: float | None = None) -> list[str]:
        """Index or forget paths whose debounce has elapsed. Returns the `prefixo` list."""
        agora = time.monotonic() if agora is None else agora
        with self._fila:
            maduros = [
                (Path(p), acao)
                for p, (quando, acao) in self._pendentes.items()
                if agora - quando >= self.debounce_s
            ]
            for path, _acao in maduros:
                self._pendentes.pop(str(path), None)
        feitos: list[str] = []
        for path, acao in maduros:
            prefixo = (
                self._esquecer(path) if acao == "esquecer" else self._indexar_um(path)
            )
            if prefixo:
                feitos.append(prefixo)
        return feitos

    def _esquecer(self, path: Path) -> str | None:
        prefixo = self.prefixo_de(path)
        if prefixo is None:
            return None
        # A save that looks like delete+create can land here after the new
        # file already exists. Index, don't forget.
        try:
            if os.path.isfile(caminho_estendido(str(path))):
                return self._indexar_um(path, via_esquecimento=True)
        except OSError:
            pass
        log.info("observador esquece %s", prefixo)
        try:
            self.store.esquecer_documento(prefixo)
            self.store.commit()
        except Exception as erro:  # noqa: BLE001 — esquecer documento não pode derrubar o observador
            log.warning("não consegui esquecer %s: %s", prefixo, erro)
            with self._fila:
                self._pendentes[str(path)] = (time.monotonic(), "esquecer")
            return None
        return prefixo

    def _indexar_um(self, path: Path, *, via_esquecimento: bool = False) -> str | None:
        prefixo = self.prefixo_de(path)
        if prefixo is None:
            return None
        if not self.candidato(path):
            # Vanished between the event and the drain: same class as on_deleted.
            try:
                existe = os.path.isfile(caminho_estendido(str(path)))
            except OSError:
                existe = False
            if not existe and not via_esquecimento:
                return self._esquecer(path)
            return None
        log.info("observador indexa %s", prefixo)
        try:
            self._indexar(
                self.cfg,
                self.store,
                self.embedder,
                prefixo=prefixo,
                reconciliar_ao_fim=False,
                publicar=True,
                parse_workers=1,
            )
        except TravaOcupada as erro:
            log.warning("índice em escrita, reenfileira %s: %s", prefixo, erro)
            with self._fila:
                self._pendentes[str(path)] = (time.monotonic(), "indexar")
            return None
        return prefixo

    def iniciar_watchdog(self):  # noqa: ANN201 — tipo do Observer, import tardio
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        observador = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event) -> None:  # noqa: ANN001
                if not event.is_directory:
                    observador.enfileirar(Path(event.src_path))

            def on_modified(self, event) -> None:  # noqa: ANN001
                if not event.is_directory:
                    observador.enfileirar(Path(event.src_path))

            def on_deleted(self, event) -> None:  # noqa: ANN001
                if not event.is_directory:
                    observador.enfileirar_apagado(Path(event.src_path))

            def on_moved(self, event) -> None:  # noqa: ANN001
                if event.is_directory:
                    return
                observador.enfileirar_apagado(Path(event.src_path))
                observador.enfileirar(Path(event.dest_path))

        observer = Observer()
        vistos: set[str] = set()
        for root in self.cfg.roots:
            alvo = str(Path(root.path).resolve())
            if alvo in vistos:
                continue
            vistos.add(alvo)
            observer.schedule(Handler(), alvo, recursive=True)
        observer.start()
        return observer

    def correr(self, *, intervalo: float = 0.2) -> None:
        """Block until cancel or Ctrl+C. Drain is what actually indexes."""
        observer = self.iniciar_watchdog()
        log.info(
            "observando %s raiz(es) · debounce %.1fs · índice em %s",
            len(self.cfg.roots),
            self.debounce_s,
            self.store.diretorio,
        )
        try:
            while True:
                cmd = ler_comando(self.store.diretorio)
                if cmd == CANCELAR:
                    log.info("observador cancelado por comando.txt")
                    return
                if cmd != PAUSAR:
                    self.drenar()
                time.sleep(intervalo)
        except KeyboardInterrupt:
            log.info("observador interrompido")
        finally:
            observer.stop()
            observer.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.index.watcher")
    parser.add_argument("--base", help="qual base observar (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument(
        "--debounce",
        type=float,
        default=DEBOUNCE_PADRAO,
        help="segundos de silêncio antes de indexar um arquivo que mudou",
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
        log.error("a base '%s' não declara nenhuma raiz — nada a observar", base.id)
        return 2

    from .cuda_runtime import aplicar_provider
    from .embeddings import Embedder

    aplicar_provider(conf.maquina.provider)
    threads = conf.maquina.threads_efetivos()
    embedder = Embedder(base.modelo, threads=threads)
    store = Store(args.indice or base.indice, embedder.dim)
    obs = Observador(cfg, store, embedder, debounce_s=args.debounce)
    try:
        obs.ocupar()
    except ObservadorOcupado as erro:
        log.error("%s", erro)
        store.fechar()
        return 4

    try:
        obs.correr()
    finally:
        obs.soltar()
        store.fechar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
