"""Manifesto, checksums e versão do formato de backup (FND-08b)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..census import caminho_estendido

VERSAO_FORMATO = 1
NOME_MANIFESTO = "manifesto.json"
PROCEDIMENTO_SQLITE = "backup_api"
PROCEDIMENTO_LANCEDB = "copia_apos_trava"

# LanceDB 0.37.1: Table.checkout/restore are in-place versions, not a portable
# snapshot. With the indexer lock held, copying vetores.lance is the verified
# procedure. A live-file copy without the lock is not a snapshot.
LANCEDB_SEM_SNAPSHOT = "0.37.1"


class FalhaDeBackup(RuntimeError):
    """Backup or restore refused; the original index is untouched."""

    def __init__(self, mensagem: str, codigo: str, acao: str = "") -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.acao = acao


class BackupRecusado(FalhaDeBackup):
    """Precondition failed before any destination was published."""


class BackupInconsistente(FalhaDeBackup):
    """Checksum, integrity or synthetic query did not match the manifest."""


@dataclass(frozen=True)
class ManifestoBackup:
    versao_formato: int
    criado_em: str
    procedimento: dict[str, str]
    schema: dict[str, Any]
    contagens: dict[str, int]
    integridade: dict[str, Any]
    inclui: tuple[str, ...]
    checksums: dict[str, str]
    consulta: dict[str, Any]

    def para_dict(self) -> dict[str, Any]:
        return {
            "versao_formato": self.versao_formato,
            "criado_em": self.criado_em,
            "procedimento": dict(self.procedimento),
            "schema": dict(self.schema),
            "contagens": dict(self.contagens),
            "integridade": dict(self.integridade),
            "inclui": list(self.inclui),
            "checksums": dict(self.checksums),
            "consulta": dict(self.consulta),
        }

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> ManifestoBackup:
        try:
            inclui = tuple(str(x) for x in dados["inclui"])
            checksums = {str(k): str(v) for k, v in dict(dados["checksums"]).items()}
            return cls(
                versao_formato=int(dados["versao_formato"]),
                criado_em=str(dados["criado_em"]),
                procedimento={str(k): str(v) for k, v in dict(dados["procedimento"]).items()},
                schema=dict(dados["schema"]),
                contagens={str(k): int(v) for k, v in dict(dados["contagens"]).items()},
                integridade=dict(dados["integridade"]),
                inclui=inclui,
                checksums=checksums,
                consulta=dict(dados["consulta"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupInconsistente(
                "O manifesto do backup está incompleto ou ilegível.",
                "manifesto_invalido",
                "Gere o backup de novo com esta versão do programa.",
            ) from exc


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_arquivo(caminho: Path) -> str:
    digest = sha256()
    with open(caminho_estendido(str(caminho)), "rb") as fh:
        while True:
            bloco = fh.read(1024 * 1024)
            if not bloco:
                break
            digest.update(bloco)
    return digest.hexdigest()


def checksums_de(raiz: Path) -> dict[str, str]:
    """SHA-256 of every payload file, relative POSIX paths, manifesto excluded."""
    saida: dict[str, str] = {}
    for arquivo in sorted(p for p in raiz.rglob("*") if p.is_file()):
        rel = arquivo.relative_to(raiz).as_posix()
        if rel == NOME_MANIFESTO:
            continue
        saida[rel] = hash_arquivo(arquivo)
    return saida


def gravar_manifesto(diretorio: Path, manifesto: ManifestoBackup) -> None:
    alvo = diretorio / NOME_MANIFESTO
    texto = json.dumps(manifesto.para_dict(), indent=2, ensure_ascii=False)
    alvo.write_text(texto + "\n", encoding="utf-8")


def ler_manifesto(diretorio: Path) -> ManifestoBackup:
    alvo = diretorio / NOME_MANIFESTO
    if not alvo.is_file():
        raise BackupInconsistente(
            "Esta pasta não é um backup do Segundo Cérebro (falta manifesto.json).",
            "manifesto_ausente",
            "Escolha a pasta gerada por 'backup criar'.",
        )
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupInconsistente(
            "Não foi possível ler o manifesto do backup.",
            "manifesto_invalido",
            "Gere o backup de novo.",
        ) from exc
    if not isinstance(dados, dict):
        raise BackupInconsistente(
            "O manifesto do backup não é um objeto JSON.",
            "manifesto_invalido",
            "Gere o backup de novo.",
        )
    return ManifestoBackup.de_dict(dados)


def conferir_versao(manifesto: ManifestoBackup) -> None:
    if manifesto.versao_formato > VERSAO_FORMATO:
        raise BackupRecusado(
            f"Este backup usa o formato {manifesto.versao_formato}; "
            f"esta instalação lê até {VERSAO_FORMATO}.",
            "versao_incompativel",
            "Atualize o Segundo Cérebro e tente restaurar de novo.",
        )
    if manifesto.versao_formato < 1:
        raise BackupInconsistente(
            "O manifesto declara uma versão de formato inválida.",
            "versao_incompativel",
            "Gere o backup de novo.",
        )


def conferir_checksums(diretorio: Path, manifesto: ManifestoBackup) -> None:
    atuais = checksums_de(diretorio)
    esperados = dict(manifesto.checksums)
    if atuais != esperados:
        raise BackupInconsistente(
            "Os arquivos do backup não batem com o manifesto (checksum).",
            "checksum_divergente",
            "Não restaure este backup; gere outro a partir do índice íntegro.",
        )
