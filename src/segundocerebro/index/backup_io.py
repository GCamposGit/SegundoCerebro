"""Cópia consistente: SQLite backup API, LanceDB após trava, destino exclusivo."""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..census import caminho_estendido
from .backup_manifesto import BackupRecusado
from .trava import TravaDeIndice, TravaOcupada


def recusar_sobreposto(indice: Path, destino: Path) -> None:
    origem, alvo = indice.resolve(), destino.resolve()
    if origem == alvo or origem in alvo.parents or alvo in origem.parents:
        raise BackupRecusado(
            "O destino do backup não pode ficar dentro do índice (nem o inverso).",
            "destino_sobreposto",
            "Escolha uma pasta fora do diretório do índice.",
        )


def recusar_indice_ausente(indice: Path) -> None:
    if not (indice / "registro.db").is_file():
        raise BackupRecusado(
            "Não há um índice neste diretório (falta registro.db).",
            "indice_ausente",
            "Confira o caminho em 'indice' no config.toml.",
        )


@contextmanager
def trava_de_backup(indice: Path) -> Iterator[None]:
    try:
        with TravaDeIndice(indice):
            yield
    except TravaOcupada as exc:
        raise BackupRecusado(
            "Há uma indexação em andamento neste índice.",
            "escritor_ativo",
            "Espere a passada terminar, ou escreva 'pausar' em comando.txt.",
        ) from exc


@contextmanager
def destino_exclusivo(destino: Path) -> Iterator[Path]:
    """Write into a pid-specific temp dir; publish with rename.

    Only this process's temp is removed on failure. A sibling `.*.<pid>.tmp`
    from another process is left alone.
    """
    destino = destino.resolve()
    if destino.exists():
        _exigir_vazio(destino)
        destino.rmdir()
    tmp = destino.parent / f".{destino.name}.{os.getpid()}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    publicado = False
    try:
        yield tmp
        tmp.rename(destino)
        publicado = True
    except OSError as exc:
        raise _io_recusado(exc) from exc
    finally:
        if not publicado and tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _exigir_vazio(destino: Path) -> None:
    if not destino.is_dir() or any(destino.iterdir()):
        raise BackupRecusado(
            "O destino já existe e não está vazio. Escolha uma pasta nova.",
            "destino_ocupado",
            "A restauração nunca apaga um índice existente; indique outro diretório.",
        )


def _io_recusado(exc: OSError) -> BackupRecusado:
    if getattr(exc, "errno", None) == 28 or getattr(exc, "winerror", None) == 112:
        return BackupRecusado(
            "Não há espaço em disco para concluir o backup.",
            "disco_cheio",
            "Libere espaço e tente de novo. O índice original não foi alterado.",
        )
    return BackupRecusado(
        f"Falha de arquivo durante o backup: {exc}",
        "io",
        "Feche o painel e o assistente se o índice estiver aberto, e tente de novo.",
    )


def copiar_sqlite(origem: Path, destino: Path) -> None:
    """Consistent snapshot via sqlite3 backup API — not a live file copy."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(origem.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destino)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
    except OSError as exc:
        raise _io_recusado(exc) from exc
    finally:
        src.close()


def _copy2_estendido(src: str, dst: str) -> str:
    return shutil.copy2(caminho_estendido(src), caminho_estendido(dst))


def copiar_arvore(origem: Path, destino: Path) -> None:
    try:
        shutil.copytree(
            caminho_estendido(str(origem)),
            caminho_estendido(str(destino)),
            copy_function=_copy2_estendido,
        )
    except OSError as exc:
        raise _io_recusado(exc) from exc


def copiar_arquivo(origem: Path, destino: Path) -> None:
    if not origem.is_file():
        raise BackupRecusado(
            f"Arquivo opcional não encontrado: {origem.name}.",
            "anexo_ausente",
            "Confira o caminho do anexo ou omita a opção.",
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        _copy2_estendido(str(origem), str(destino))
    except OSError as exc:
        raise _io_recusado(exc) from exc


def limpar_wal(diretorio: Path) -> None:
    for nome in ("registro.db-wal", "registro.db-shm"):
        (diretorio / nome).unlink(missing_ok=True)
