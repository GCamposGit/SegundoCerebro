"""Backup consistente e restauração verificável do índice (FND-08b).

O leigo guarda o índice (registro + vetores) e restaura para um diretório novo.
Originais da pasta apontada não entram. A restauração nunca apaga o índice
atual: ativar o restaurado é apontar `indice` no config.toml para a pasta nova.

LanceDB 0.37.1 não expõe snapshot portátil (`checkout`/`restore` são versões
in-place). Com a trava exclusiva do indexador, copiar `vetores.lance` é o
procedimento verificado. Copiar arquivos de banco vivo, sem a trava, não é
snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import BASE_UNICA, ErroDeConfig
from ..config import carregar as carregar_config
from ..logger import get_logger
from .backup_io import (
    copiar_arquivo,
    copiar_arvore,
    copiar_sqlite,
    destino_exclusivo,
    recusar_indice_ausente,
    recusar_sobreposto,
    trava_de_backup,
)
from .backup_manifesto import (
    LANCEDB_SEM_SNAPSHOT,
    PROCEDIMENTO_LANCEDB,
    PROCEDIMENTO_SQLITE,
    VERSAO_FORMATO,
    BackupInconsistente,
    BackupRecusado,
    FalhaDeBackup,
    ManifestoBackup,
    agora_iso,
    checksums_de,
    conferir_checksums,
    conferir_versao,
    gravar_manifesto,
    ler_manifesto,
)
from .backup_verificar import verificar_copia

log = get_logger("index.backup")

PASTA_PARSE_STORE = "parse_store"
"""Same directory name as ingest.parse_store.PASTA; copied only with --parse-store."""

__all__ = [
    "BackupInconsistente",
    "BackupRecusado",
    "FalhaDeBackup",
    "ManifestoBackup",
    "criar_backup",
    "main",
    "restaurar_backup",
]


def _montar_manifesto(tmp: Path, verificado: dict[str, object]) -> ManifestoBackup:
    inclui = ["registro"]
    if (tmp / "vetores.lance").is_dir():
        inclui.append("vetores")
    if (tmp / PASTA_PARSE_STORE).is_dir():
        inclui.append("parse_store")
    if (tmp / "anexos" / "config.toml").is_file():
        inclui.append("config")
    if (tmp / "anexos" / "glossario.toml").is_file():
        inclui.append("glossario")
    lance = verificado["lance"]
    return ManifestoBackup(
        versao_formato=VERSAO_FORMATO,
        criado_em=agora_iso(),
        procedimento={
            "sqlite": PROCEDIMENTO_SQLITE,
            "lancedb": PROCEDIMENTO_LANCEDB,
            "lancedb_instalado": str(lance.get("lancedb") or LANCEDB_SEM_SNAPSHOT),
        },
        schema=dict(verificado["schema"]),
        contagens=dict(verificado["contagens"]),
        integridade=dict(verificado["integridade"]),
        inclui=tuple(inclui),
        checksums=checksums_de(tmp),
        consulta=dict(verificado["consulta"]),
    )


def criar_backup(
    indice: Path,
    destino: Path,
    *,
    config: Path | None = None,
    glossario: Path | None = None,
    incluir_parse_store: bool = False,
) -> ManifestoBackup:
    """Snapshot with the writer stopped. Publishes only after verification."""
    indice = indice.resolve()
    destino = destino.resolve()
    recusar_sobreposto(indice, destino)
    recusar_indice_ausente(indice)
    with destino_exclusivo(destino) as tmp:
        _copiar_indice(indice, tmp, incluir_parse_store=incluir_parse_store)
        _copiar_anexos(tmp, config=config, glossario=glossario)
        verificado = verificar_copia(tmp)
        manifesto = _montar_manifesto(tmp, verificado)
        gravar_manifesto(tmp, manifesto)
    log.info("backup publicado com %d arquivo(s)", len(manifesto.checksums))
    return manifesto


def _copiar_indice(indice: Path, tmp: Path, *, incluir_parse_store: bool) -> None:
    with trava_de_backup(indice):
        copiar_sqlite(indice / "registro.db", tmp / "registro.db")
        lance = indice / "vetores.lance"
        if lance.is_dir():
            copiar_arvore(lance, tmp / "vetores.lance")
        if incluir_parse_store:
            pasta = indice / PASTA_PARSE_STORE
            if pasta.is_dir():
                copiar_arvore(pasta, tmp / PASTA_PARSE_STORE)


def _copiar_anexos(
    tmp: Path, *, config: Path | None, glossario: Path | None
) -> None:
    if config is not None:
        copiar_arquivo(config, tmp / "anexos" / "config.toml")
    if glossario is not None:
        copiar_arquivo(glossario, tmp / "anexos" / "glossario.toml")


def restaurar_backup(origem: Path, destino: Path) -> ManifestoBackup:
    """Restore into a new directory. Never deletes the original index."""
    origem = origem.resolve()
    destino = destino.resolve()
    recusar_sobreposto(origem, destino)
    manifesto = ler_manifesto(origem)
    conferir_versao(manifesto)
    conferir_checksums(origem, manifesto)
    with destino_exclusivo(destino) as tmp:
        copiar_sqlite(origem / "registro.db", tmp / "registro.db")
        if "vetores" in manifesto.inclui:
            copiar_arvore(origem / "vetores.lance", tmp / "vetores.lance")
        if "parse_store" in manifesto.inclui:
            copiar_arvore(origem / PASTA_PARSE_STORE, tmp / PASTA_PARSE_STORE)
        if "config" in manifesto.inclui:
            copiar_arquivo(origem / "anexos" / "config.toml", tmp / "anexos" / "config.toml")
        if "glossario" in manifesto.inclui:
            copiar_arquivo(
                origem / "anexos" / "glossario.toml", tmp / "anexos" / "glossario.toml"
            )
        verificado = verificar_copia(tmp)
        _conferir_ids(manifesto, verificado)
        gravar_manifesto(tmp, manifesto)
    log.info("restauração verificada; índice original intacto")
    return manifesto


def _conferir_ids(manifesto: ManifestoBackup, verificado: dict) -> None:
    if verificado["contagens"] != manifesto.contagens:
        raise BackupInconsistente(
            "As contagens restauradas não batem com o manifesto.",
            "contagem_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )
    if not verificado["consulta"].get("reproduzido"):
        raise BackupInconsistente(
            "A consulta sintética não reproduziu o resultado do backup.",
            "consulta_divergente",
            "Não ative este destino; o índice original permanece no lugar.",
        )


def _indice_da_base(base_id: str, config: Path | None) -> tuple[Path, Path | None]:
    conf = carregar_config(config, validar=True) if config is not None else carregar_config()
    base = next((b for b in conf.bases if b.id == base_id), None)
    if base is None:
        raise ErroDeConfig(
            f"A base '{base_id}' não foi encontrada. Disponíveis: {', '.join(conf.ids)}."
        )
    return base.indice, base.glossario


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backup e restauração verificável do índice do Segundo Cérebro."
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    criar = sub.add_parser("criar", help="Copia o índice com a indexação parada.")
    criar.add_argument("--base", default=BASE_UNICA, help="Base cujo índice será copiado.")
    criar.add_argument("--config", type=Path, help="config.toml da base.")
    criar.add_argument("--indice", type=Path, help="Diretório do índice; sobrepõe a base.")
    criar.add_argument("--destino", type=Path, required=True, help="Pasta nova do backup.")
    criar.add_argument("--glossario", type=Path, help="Copia o glossário para anexos/.")
    criar.add_argument(
        "--incluir-config",
        action="store_true",
        help="Copia o config.toml para anexos/. Não inclui os documentos originais.",
    )
    criar.add_argument(
        "--parse-store",
        action="store_true",
        dest="parse_store",
        help="Inclui o cache de parse (reconstruível; omitido por padrão).",
    )
    restaurar = sub.add_parser(
        "restaurar", help="Restaura para uma pasta nova; não apaga o índice atual."
    )
    restaurar.add_argument("--origem", type=Path, required=True, help="Pasta do backup.")
    restaurar.add_argument("--destino", type=Path, required=True, help="Pasta nova do índice.")
    return parser


def _criar_via_cli(args: argparse.Namespace) -> ManifestoBackup:
    glossario = args.glossario
    indice = args.indice
    config_anexo: Path | None = None
    if indice is None:
        indice, glossario_base = _indice_da_base(args.base, args.config)
        if glossario is None:
            glossario = glossario_base
    if args.incluir_config:
        config_anexo = args.config if args.config is not None else Path("config.toml")
    return criar_backup(
        indice,
        args.destino,
        config=config_anexo,
        glossario=glossario,
        incluir_parse_store=args.parse_store,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.comando == "criar":
            manifesto = _criar_via_cli(args)
            print(json.dumps(manifesto.para_dict(), indent=2, ensure_ascii=False))  # noqa: T201 — saída da CLI
            print(  # noqa: T201 — saída da CLI
                "Backup pronto. Os documentos originais não foram copiados. "
                "Para restaurar: py -m segundocerebro.index.backup restaurar "
                f"--origem {args.destino} --destino <pasta-nova>",
                file=sys.stderr,
            )
            return 0
        manifesto = restaurar_backup(args.origem, args.destino)
        print(json.dumps(manifesto.para_dict(), indent=2, ensure_ascii=False))  # noqa: T201 — saída da CLI
        print(  # noqa: T201 — saída da CLI
            f"Restaurado em {args.destino}. O índice original não foi alterado. "
            "Para usar esta cópia, aponte 'indice' no config.toml para essa pasta.",
            file=sys.stderr,
        )
        return 0
    except (BackupRecusado, BackupInconsistente, FalhaDeBackup) as exc:
        print(f"erro: {exc}", file=sys.stderr)  # noqa: T201 — saída da CLI
        if exc.acao:
            print(f"ação: {exc.acao}", file=sys.stderr)  # noqa: T201 — saída da CLI
        return 1
    except ErroDeConfig as exc:
        print(f"erro: {exc}", file=sys.stderr)  # noqa: T201 — saída da CLI
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
