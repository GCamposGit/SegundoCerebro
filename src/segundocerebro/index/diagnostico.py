"""Diagnóstico operacional somente leitura do Segundo Cérebro (FND-08a)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import BASE_UNICA, Base, Config, ErroDeConfig
from ..config import carregar as carregar_config
from .cuda_runtime import diagnosticar as diagnosticar_cuda
from .diagnostico_integridade import conferir_integridade as _conferir_integridade
from .diagnostico_relatorio import (
    ItemDiagnostico,
    RelatorioDiagnostico,
    StatusGeral,
)
from .diagnostico_relatorio import item as _item
from .trava import TravaDeIndice

Cancelar = Callable[[], bool]
Progresso = Callable[[int, int], None]


def _conferir_config(
    caminho: Path | str | None,
) -> tuple[Config | None, list[ItemDiagnostico]]:
    alvo = Path(caminho) if caminho is not None else Path("config.toml")
    if not alvo.exists():
        return None, [
            _item(
                "config_invalida",
                "erro",
                f"Arquivo de configuração '{alvo}' não foi encontrado.",
                "Crie-o a partir de 'config.example.toml'.",
                escopo="configuracao",
                evidencia={"caminho": str(alvo), "motivo": "arquivo_inexistente"},
            )
        ]
    try:
        conf = carregar_config(alvo, validar=True)
    except (ErroDeConfig, OSError, ValueError) as exc:
        return None, [
            _item(
                "config_invalida",
                "erro",
                f"Configuração '{alvo}' inválida: {exc}",
                "Corrija o config.toml conforme a mensagem acima.",
                escopo="configuracao",
                evidencia={"caminho": str(alvo), "tipo_erro": type(exc).__name__},
            )
        ]
    return conf, [
        _item(
            "config_valida",
            "ok",
            f"Configuração carregada com {len(conf.bases)} base(s).",
            escopo="configuracao",
            evidencia={"bases": [base.id for base in conf.bases]},
        )
    ]


def _conferir_raizes(base: Base) -> list[ItemDiagnostico]:
    if not base.raizes:
        return [
            _item(
                "raiz_inacessivel",
                "erro",
                f"A base '{base.id}' não possui pasta de documentos configurada.",
                "Adicione pelo menos uma entrada em 'raizes' no config.toml.",
                escopo="raizes",
            )
        ]
    itens: list[ItemDiagnostico] = []
    for raiz in base.raizes:
        caminho = Path(raiz.path)
        acessivel = caminho.exists() and caminho.is_dir() and os.access(caminho, os.R_OK)
        itens.append(
            _item(
                "raiz_acessivel" if acessivel else "raiz_inacessivel",
                "ok" if acessivel else "erro",
                (
                    f"Raiz '{raiz.name}' acessível."
                    if acessivel
                    else f"A raiz '{raiz.name}' não existe, não é pasta ou não permite leitura."
                ),
                "" if acessivel else "Corrija o caminho ou a permissão dessa raiz.",
                escopo="raizes",
                evidencia={"nome": raiz.name, "caminho": str(caminho)},
            )
        )
    return itens


def _abrir_sqlite_ro(registro: Path) -> sqlite3.Connection:
    con = sqlite3.connect(registro.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
    con.execute("PRAGMA query_only=ON")
    return con


@dataclass(frozen=True)
class _ResumoIndice:
    documentos: int
    chunks: int
    modelo: str = ""


def _ler_resumo(registro: Path) -> _ResumoIndice:
    con = _abrir_sqlite_ro(registro)
    try:
        tabelas = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        exigidas = {"documentos", "chunks"}
        if not exigidas.issubset(tabelas):
            raise RuntimeError("tabelas ausentes: " + ", ".join(sorted(exigidas - tabelas)))
        documentos = int(con.execute("SELECT count(*) FROM documentos").fetchone()[0])
        chunks = int(con.execute("SELECT count(*) FROM chunks").fetchone()[0])
        modelo = ""
        if "execucoes" in tabelas:
            row = con.execute(
                "SELECT model_id FROM execucoes WHERE status='concluida' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            modelo = str(row[0]) if row and row[0] else ""
        return _ResumoIndice(documentos, chunks, modelo)
    finally:
        con.close()


def _conferir_indice(
    diretorio: Path, base_id: str
) -> tuple[list[ItemDiagnostico], _ResumoIndice | None]:
    registro = diretorio / "registro.db"
    if not registro.is_file():
        return [
            _item(
                "indice_ausente",
                "aviso",
                f"O índice da base '{base_id}' ainda não foi criado.",
                (
                    f"Execute 'segundocerebro-indexar --base {base_id}' "
                    f"(ou 'py -m segundocerebro.index.indexer --base {base_id}' no checkout)."
                ),
                escopo="indice",
                evidencia={"diretorio": str(diretorio)},
            )
        ], None
    try:
        resumo = _ler_resumo(registro)
    except Exception as exc:  # noqa: BLE001 — registro hostil não pode derrubar o diagnóstico operacional
        return [
            _item(
                "indice_incompleto",
                "erro",
                f"O registro do índice não pôde ser lido: {exc}",
                "Pare a indexação e restaure ou reconstrua esta base.",
                escopo="indice",
                evidencia={"tipo_erro": type(exc).__name__},
            )
        ], None
    return [
        _item(
            "indice_presente",
            "ok",
            f"Índice com {resumo.documentos} documento(s) e {resumo.chunks} chunk(s).",
            escopo="indice",
            evidencia={"documentos": resumo.documentos, "chunks": resumo.chunks},
        )
    ], resumo


def _conferir_trava(diretorio: Path) -> list[ItemDiagnostico]:
    trava = TravaDeIndice(diretorio)
    try:
        if trava.ocupada():
            pid, criacao = trava._dono()
            return [
                _item(
                    "escrita_ativa",
                    "aviso",
                    f"Há uma indexação viva escrevendo no índice (PID {pid}).",
                    "Aguarde o término antes do diagnóstico profundo.",
                    escopo="indice",
                    evidencia={"pid": pid, "criacao": criacao},
                )
            ]
        if trava.caminho.exists():
            return [
                _item(
                    "trava_orfa",
                    "aviso",
                    "Existe uma trava sem processo vivo correspondente.",
                    "A próxima indexação removerá a trava órfã com segurança.",
                    escopo="indice",
                )
            ]
    except (OSError, ValueError) as exc:
        return [
            _item(
                "trava_indisponivel",
                "aviso",
                f"Não foi possível interpretar a trava: {exc}",
                "Verifique permissões e tente novamente.",
                escopo="indice",
                evidencia={"tipo_erro": type(exc).__name__},
            )
        ]
    return [_item("escrita_inativa", "ok", "Nenhuma indexação ativa.", escopo="indice")]


def _conferir_hardware_modelo(
    base: Base, provider: str, resumo: _ResumoIndice | None
) -> list[ItemDiagnostico]:
    itens: list[ItemDiagnostico] = []
    pedido = os.environ.get("SEGUNDOCEREBRO_PROVIDER", provider).strip().lower()
    if pedido == "cuda":
        diag = diagnosticar_cuda(modelo=base.modelo)
        itens.append(
            _item(
                "hardware_compativel" if diag.ok else "modelo_incompativel",
                "ok" if diag.ok else "erro",
                diag.mensagem,
                "" if diag.ok else "Corrija o extra GPU/driver ou use CPU.",
                escopo="hardware",
                evidencia={"codigo": diag.codigo},
            )
        )
    else:
        itens.append(
            _item(
                "hardware_cpu",
                "ok",
                "O provider é CPU; nenhuma sonda de GPU foi executada.",
                escopo="hardware",
            )
        )
    if resumo and resumo.modelo:
        corresponde = resumo.modelo == base.modelo or resumo.modelo.startswith(base.modelo + ":")
        if not corresponde:
            itens.append(
                _item(
                    "modelo_divergente",
                    "aviso",
                    f"O índice usa '{resumo.modelo}', mas a configuração pede '{base.modelo}'.",
                    "Reindexe a base antes da busca vetorial com o novo modelo.",
                    escopo="modelo",
                    evidencia={"configurado": base.modelo, "gravado": resumo.modelo},
                )
            )
    return itens


def _erro_parser(nome: str, exc: Exception) -> ItemDiagnostico:
    return _item(
        "parser_indisponivel",
        "aviso",
        f"Não foi possível verificar {nome}: {exc}",
        "Confira a instalação e as permissões desse componente.",
        escopo="parsers",
        evidencia={"componente": nome, "tipo_erro": type(exc).__name__},
    )


def _conferir_parsers() -> list[ItemDiagnostico]:
    itens: list[ItemDiagnostico] = []
    try:
        from ..ingest.converters.libreoffice import encontrar_soffice

        soffice = encontrar_soffice()
        itens.append(
            _item(
                "parser_soffice_disponivel" if soffice else "parser_soffice_ausente",
                "ok",
                (
                    "LibreOffice disponível para formatos legados."
                    if soffice
                    else "LibreOffice ausente; .doc, .xls e .ppt são opcionais."
                ),
                escopo="parsers",
                evidencia={"caminho": soffice} if soffice else None,
            )
        )
    except Exception as exc:  # noqa: BLE001 — probe de parser: LibreOffice ausente ou recusado é aviso
        itens.append(_erro_parser("LibreOffice", exc))
    try:
        from ..ingest.ocr import backend_disponivel

        backend = backend_disponivel()
        itens.append(
            _item(
                "parser_ocr_disponivel" if backend else "parser_ocr_ausente",
                "ok",
                f"OCR disponível ({backend})." if backend else "OCR opcional ausente.",
                escopo="parsers",
                evidencia={"backend": backend} if backend else None,
            )
        )
    except Exception as exc:  # noqa: BLE001 — probe de parser: OCR ausente ou recusado é aviso
        itens.append(_erro_parser("OCR", exc))
    return itens


def _status(itens: list[ItemDiagnostico]) -> StatusGeral:
    if any(item.severidade == "erro" for item in itens):
        return "inoperante"
    if any(item.severidade == "aviso" for item in itens):
        return "atencao"
    return "saudavel"


def _conferir_base(
    base: Base,
    conf: Config,
    profundo: bool,
    lote: int,
    cancelar: Cancelar | None,
    progresso: Progresso | None,
) -> list[ItemDiagnostico]:
    itens = _conferir_raizes(base)
    trava = _conferir_trava(base.indice)
    itens.extend(trava)
    indice, resumo = _conferir_indice(base.indice, base.id)
    itens.extend(indice)
    itens.extend(_conferir_hardware_modelo(base, conf.maquina.provider, resumo))
    itens.extend(_conferir_parsers())
    if profundo and any(item.codigo == "escrita_ativa" for item in trava):
        itens.append(
            _item(
                "integridade_adiada",
                "aviso",
                "A integridade profunda não foi aberta porque há escrita ativa.",
                "Aguarde a indexação terminar e execute o diagnóstico novamente.",
                escopo="integridade",
            )
        )
    elif profundo:
        itens.extend(_conferir_integridade(base.indice, lote, cancelar, progresso))
    return itens


def diagnosticar_base(
    base_id: str = BASE_UNICA,
    caminho_config: Path | str | None = None,
    profundo: bool = False,
    limite_integridade: int = 1000,
    *,
    cancelar: Cancelar | None = None,
    progresso: Progresso | None = None,
) -> RelatorioDiagnostico:
    """Inspeciona metadados; a comparação entre stores é opt-in."""
    inicio = time.perf_counter()
    itens: list[ItemDiagnostico] = []
    try:
        conf, config_itens = _conferir_config(caminho_config)
        itens.extend(config_itens)
        if conf is not None:
            base = next((b for b in conf.bases if b.id == base_id), None)
            if base is None:
                raise ErroDeConfig(
                    f"A base '{base_id}' não foi encontrada. Disponíveis: {', '.join(conf.ids)}."
                )
            itens.extend(
                _conferir_base(
                    base,
                    conf,
                    profundo,
                    limite_integridade,
                    cancelar,
                    progresso,
                )
            )
    except ErroDeConfig as exc:
        itens.append(
            _item(
                "base_inexistente",
                "erro",
                str(exc),
                "Escolha uma base declarada no config.toml.",
                escopo="configuracao",
            )
        )
    except Exception as exc:  # noqa: BLE001 — falha interna vira inoperante, não crash do CLI
        itens.append(
            _item(
                "erro_interno",
                "erro",
                f"Falha interna durante o diagnóstico: {exc}",
                "Exporte o relatório higienizado e envie ao suporte.",
                escopo="diagnostico",
                evidencia={"tipo_erro": type(exc).__name__},
            )
        )
    duracao = (time.perf_counter() - inicio) * 1000
    return RelatorioDiagnostico(base_id, _status(itens), itens, profundo, duracao)


def _progresso_terminal(processados: int, total: int) -> None:
    print(
        f"\rIntegridade profunda: {processados}/{total} vetores",
        end="",
        file=sys.stderr,
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico operacional somente leitura do Segundo Cérebro."
    )
    parser.add_argument("--base", default=BASE_UNICA, help="Base a inspecionar.")
    parser.add_argument("--config", type=Path, help="Configuração a utilizar.")
    parser.add_argument("--profundo", action="store_true", help="Compara SQLite e vetores.")
    parser.add_argument(
        "--lote-integridade", type=int, default=1000, help="Vetores por lote profundo."
    )
    saida = parser.add_mutually_exclusive_group()
    saida.add_argument("--json", action="store_true", help="Emite JSON estruturado.")
    saida.add_argument("--exportar-suporte", action="store_true", help="Emite JSON seguro.")
    args = parser.parse_args(argv)
    relatorio = diagnosticar_base(
        args.base,
        args.config,
        args.profundo,
        args.lote_integridade,
        progresso=_progresso_terminal if args.profundo else None,
    )
    if args.profundo:
        print(file=sys.stderr)
    if args.exportar_suporte:
        print(relatorio.exportar_suporte())
    elif args.json:
        print(json.dumps(relatorio.para_dict(), indent=2, ensure_ascii=False))
    else:
        print(relatorio.formatar_texto())
    return 1 if relatorio.status_geral == "inoperante" else 0


if __name__ == "__main__":
    raise SystemExit(main())
