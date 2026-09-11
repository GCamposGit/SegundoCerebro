"""Validate the active package queue without calling the hosting API.

FND-12: ROADMAP.md is history. docs/pacotes-ativos.toml is the queue.
A delivered package without evidence, a dependency cycle, or two writers on
the same path fail here. The phrase 'neste PR' is not merge evidence.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILA = ROOT / "docs" / "pacotes-ativos.toml"
ESTADOS = frozenset({"proposto", "pronto", "em_execucao", "bloqueado", "entregue"})
ESCREVEM = frozenset({"pronto", "em_execucao"})
GLOB = re.compile(r"[*?[]")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
NESTE_PR = re.compile(r"neste\s+pr", re.I)


@dataclass(frozen=True)
class Pacote:
    id: str
    estado: str
    dono: str
    paths: tuple[str, ...]
    dependencias: tuple[str, ...]
    aceite: str
    evidencia: object
    proxima_acao: str


def carregar(texto: str) -> list[Pacote]:
    dados = tomllib.loads(texto)
    brutos = dados.get("pacote", [])
    if not isinstance(brutos, list):
        raise ValueError("[[pacote]] ausente ou nao e lista")
    saida: list[Pacote] = []
    for item in brutos:
        if not isinstance(item, dict):
            raise ValueError("entrada de pacote nao e tabela")
        saida.append(
            Pacote(
                id=str(item.get("id") or "").strip(),
                estado=str(item.get("estado") or "").strip(),
                dono=str(item.get("dono") or "").strip(),
                paths=_tupla(item.get("paths")),
                dependencias=_tupla(item.get("dependencias")),
                aceite=str(item.get("aceite") or "").strip(),
                evidencia=item.get("evidencia", ""),
                proxima_acao=str(item.get("proxima_acao") or "").strip(),
            )
        )
    return saida


def _tupla(valor: object) -> tuple[str, ...]:
    if valor is None:
        return ()
    if isinstance(valor, list):
        return tuple(str(v).strip() for v in valor if str(v).strip())
    raise ValueError("paths/dependencias devem ser listas")


def evidencia_prova_entrega(evidencia: object) -> bool:
    """True only with a PR number or a git SHA. 'neste PR' never counts."""
    if evidencia is None or evidencia == "" or evidencia == {}:
        return False
    if isinstance(evidencia, str):
        if NESTE_PR.search(evidencia):
            return False
        return bool(re.search(r"#\d+", evidencia) or SHA.search(evidencia.strip().lower()))
    if isinstance(evidencia, Mapping):
        if any(NESTE_PR.search(str(v)) for v in evidencia.values()):
            return False
        pr = evidencia.get("pr")
        if isinstance(pr, int) and pr > 0:
            return True
        sha = str(evidencia.get("sha") or "").strip().lower()
        return bool(SHA.fullmatch(sha))
    return False


def expandir_path(raiz: Path, bruto: str) -> tuple[str, ...]:
    """Globs must hit real files. A concrete missing path is a new-file reservation."""
    normal = bruto.replace("\\", "/").lstrip("/")
    if GLOB.search(normal):
        achados = sorted(
            p.relative_to(raiz).as_posix()
            for p in raiz.glob(normal)
            if p.is_file()
        )
        return tuple(achados)
    return (normal,)


def _ciclo(pacotes: Sequence[Pacote]) -> list[str]:
    ids = {p.id for p in pacotes}
    grafico = {p.id: [d for d in p.dependencias if d in ids] for p in pacotes}
    visitado: dict[str, int] = {}
    pilha: list[str] = []
    achados: list[str] = []

    def dfs(no: str) -> None:
        estado = visitado.get(no, 0)
        if estado == 1:
            i = pilha.index(no)
            achados.append(" -> ".join(pilha[i:] + [no]))
            return
        if estado == 2:
            return
        visitado[no] = 1
        pilha.append(no)
        for nxt in grafico.get(no, ()):
            dfs(nxt)
        pilha.pop()
        visitado[no] = 2

    for ident in grafico:
        dfs(ident)
    return achados


def validar(pacotes: Sequence[Pacote], raiz: Path) -> list[str]:
    erros: list[str] = []
    vistos: dict[str, str] = {}
    for pacote in pacotes:
        if not pacote.id:
            erros.append("pacote sem id")
            continue
        if pacote.id in vistos:
            erros.append(f"{pacote.id}: id duplicado")
        vistos[pacote.id] = pacote.dono
        if not pacote.estado:
            erros.append(f"{pacote.id}: estado vazio")
        elif pacote.estado not in ESTADOS:
            erros.append(f"{pacote.id}: estado desconhecido {pacote.estado!r}")
        if not pacote.dono:
            erros.append(f"{pacote.id}: dono vazio")
        if not pacote.paths:
            erros.append(f"{pacote.id}: paths vazios")
        if not pacote.aceite:
            erros.append(f"{pacote.id}: aceite vazio")
        if pacote.estado == "entregue" and not evidencia_prova_entrega(pacote.evidencia):
            erros.append(f"{pacote.id}: entregue sem evidencia de PR ou SHA")
        for bruto in pacote.paths:
            if GLOB.search(bruto.replace("\\", "/")):
                achados = expandir_path(raiz, bruto)
                if not achados:
                    erros.append(f"{pacote.id}: glob sem arquivo {bruto}")

    ids = {p.id for p in pacotes}
    for pacote in pacotes:
        for dep in pacote.dependencias:
            if dep not in ids:
                erros.append(f"{pacote.id}: dependencia inexistente {dep}")

    for ciclo in _ciclo(pacotes):
        erros.append(f"ciclo: {ciclo}")

    ativos = [p for p in pacotes if p.estado in ESCREVEM]
    ocupado: dict[str, str] = {}
    for pacote in ativos:
        for bruto in pacote.paths:
            for alvo in expandir_path(raiz, bruto):
                outro = ocupado.get(alvo)
                if outro and outro != pacote.id:
                    erros.append(
                        f"paths sobrepostos: {outro} e {pacote.id} em {alvo}"
                    )
                ocupado[alvo] = pacote.id
    return erros


def validar_arquivo(caminho: Path, raiz: Path) -> list[str]:
    texto = caminho.read_text(encoding="utf-8")
    return validar(carregar(texto), raiz)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida a fila ativa (FND-12).")
    parser.add_argument("--fila", type=Path, default=FILA)
    parser.add_argument("--raiz", type=Path, default=ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.fila.is_file():
        print(f"fila ausente: {args.fila}", file=sys.stderr)
        return 2
    erros = validar_arquivo(args.fila, args.raiz)
    for erro in erros:
        print(erro, file=sys.stderr)
    print(f"{args.fila.name}: {len(erros)} erro(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
