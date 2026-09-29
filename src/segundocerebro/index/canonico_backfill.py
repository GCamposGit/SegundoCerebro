"""Reconstrói o Parse Store sem alterar o índice lexical ou vetorial."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Mapping

from ..config import ErroDeConfig, carregar
from ..ingest.document import ParseStatus
from ..ingest.parse_cache import canonicos_disponiveis
from ..ingest.parsers import parser_for
from ..ingest.reader import parse_file
from ..logger import get_logger
from .cli import construir_parser_backfill_canonico
from .repesca import versao_efetiva

log = get_logger("index.canonico_backfill")

EXTENSOES_PPTX = frozenset({".ppt", ".pptx", ".pptm"})


@dataclass(frozen=True)
class ResultadoBackfill:
    recuperados: int = 0
    existentes: int = 0
    ignorados: int = 0
    falhas: int = 0


def _registro_somente_leitura(indice: Path) -> sqlite3.Connection:
    registro = indice / "registro.db"
    if not registro.is_file():
        raise FileNotFoundError(f"registro do índice não encontrado: {registro}")
    conexao = sqlite3.connect(f"{registro.resolve().as_uri()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    return conexao


def _coluna_raiz(conexao: sqlite3.Connection) -> str:
    nomes = {linha["name"] for linha in conexao.execute("PRAGMA table_info(documentos)")}
    from .ocorrencia import usa_ocorrencia

    if usa_ocorrencia(conexao):
        return "root_id"
    if "raiz" in nomes:
        return "raiz"
    if "root_id" in nomes:
        return "root_id"
    raise sqlite3.OperationalError("o registro não contém identidade da raiz")


def _arquivo_da_raiz(
    relativo: str,
    root_id: str,
    raizes: Mapping[str, Path],
) -> Path | None:
    raiz = raizes.get(root_id)
    if raiz is None and not root_id and len(raizes) == 1:
        raiz = next(iter(raizes.values()))
    if raiz is None or not relativo or "\\" in relativo:
        return None
    caminho = PurePosixPath(relativo)
    if caminho.is_absolute() or PureWindowsPath(relativo).drive or ".." in caminho.parts:
        return None
    raiz_real = raiz.resolve()
    arquivo = raiz_real.joinpath(*caminho.parts).resolve()
    return arquivo if arquivo.is_relative_to(raiz_real) else None


def _iterar_documentos(conexao: sqlite3.Connection) -> sqlite3.Cursor:
    raiz = _coluna_raiz(conexao)
    return conexao.execute(
        "SELECT path, "
        f"{raiz} AS root_id, sha256, parser, status, n_chunks, tamanho, mtime "
        "FROM documentos WHERE status = 'ok' AND n_chunks > 0 "
        "AND sha256 IS NOT NULL AND sha256 != '' ORDER BY path"
    )


def _arquivo_inalterado(linha: sqlite3.Row, raizes: Mapping[str, Path]) -> Path | None:
    arquivo = _arquivo_da_raiz(str(linha["path"]), str(linha["root_id"] or ""), raizes)
    if arquivo is None:
        return None
    try:
        stat = arquivo.stat()
    except OSError:
        return None
    if not arquivo.is_file() or stat.st_size != int(linha["tamanho"] or 0):
        return None
    if abs(stat.st_mtime - float(linha["mtime"] or 0)) > 1e-6:
        return None
    return arquivo


def _reconstruir_arquivo(arquivo: Path, indice: Path, sha256: str, extensao: str) -> Literal[
    "recuperado", "ignorado", "falha"
]:
    try:
        resultado = parse_file(str(arquivo), indice=indice, ocr=False)
    except Exception as erro:  # noqa: BLE001 — um documento não interrompe a passada
        log.warning("não foi possível reconstruir o canônico de %s: %s", arquivo.name, erro)
        return "falha"
    if resultado.sha256 != sha256:
        return "ignorado"
    if resultado.status is not ParseStatus.OK or resultado.doc is None:
        return "falha"
    try:
        persistido = next(canonicos_disponiveis(indice, sha256, extensao), None)
    except OSError as erro:
        log.warning("não foi possível conferir o canônico gravado de %s: %s", arquivo.name, erro)
        return "falha"
    return "recuperado" if persistido is not None else "falha"


def _processar_linha(
    linha: sqlite3.Row,
    indice: Path,
    raizes: Mapping[str, Path],
) -> Literal["recuperado", "existente", "ignorado", "falha"]:
    extensao = Path(str(linha["path"])).suffix.lower()
    if extensao in EXTENSOES_PPTX or parser_for(extensao) is None:
        return "ignorado"
    if str(linha["parser"] or "") != versao_efetiva(extensao):
        return "ignorado"
    sha256 = str(linha["sha256"])
    try:
        if next(canonicos_disponiveis(indice, sha256, extensao), None) is not None:
            return "existente"
    except OSError as erro:
        log.warning("não foi possível conferir o Parse Store de %s: %s", linha["path"], erro)
        return "falha"
    arquivo = _arquivo_inalterado(linha, raizes)
    if arquivo is None:
        return "ignorado"
    return _reconstruir_arquivo(arquivo, indice, sha256, extensao)


def reconstruir_parse_store(indice: Path, raizes: Mapping[str, Path]) -> ResultadoBackfill:
    """Persiste canônicos ausentes apenas para registros atuais e ainda válidos."""
    recuperados = existentes = ignorados = falhas = 0
    conexao = _registro_somente_leitura(indice)
    try:
        for linha in _iterar_documentos(conexao):
            estado = _processar_linha(linha, indice, raizes)
            recuperados += estado == "recuperado"
            existentes += estado == "existente"
            ignorados += estado == "ignorado"
            falhas += estado == "falha"
    finally:
        conexao.close()
    return ResultadoBackfill(recuperados, existentes, ignorados, falhas)


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace = construir_parser_backfill_canonico().parse_args(argv)
    try:
        configuracao = carregar(args.config)
        base = configuracao.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2
    if not base.raizes:
        log.error("a base '%s' não declara nenhuma raiz", base.id)
        return 2

    indice = args.indice or base.indice
    raizes = {raiz.name: Path(raiz.path) for raiz in base.raizes}
    try:
        resultado = reconstruir_parse_store(indice, raizes)
    except (OSError, sqlite3.Error) as erro:
        log.error("backfill canônico não concluído: %s", erro)
        return 2
    log.info(
        "Backfill canônico: "
        f"{resultado.recuperados} recuperado(s), {resultado.existentes} já presente(s), "
        f"{resultado.ignorados} ignorado(s), {resultado.falhas} falha(s)."
    )
    return 1 if resultado.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
