"""Censo limitado ao prefixo da pasta pedida — FND-04.

`iter_files` do census percorre a raiz inteira. list_folder de uma pasta pequena
não precisa disso: começa no diretório do prefixo, não segue symlink/junction e
não abre conteúdo. A visita é contada para o teste de escopo.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from .. import census as census_mod
from .original import ErroLeitura
from .registro import normalizar_prefixo

_ATRIBUTO_REPARSE = census_mod.FILE_ATTRIBUTE_REPARSE_POINT


@dataclass
class Visita:
    arquivos: int = 0


def _attrs(st: os.stat_result) -> int:
    return getattr(st, "st_file_attributes", 0)


def _diretorio_inicial(raiz: str, pasta: str) -> str | None:
    prefixo = normalizar_prefixo(pasta).rstrip("/")
    base = os.path.abspath(raiz)
    if not prefixo:
        return census_mod.caminho_estendido(base)
    partes = prefixo.split("/")
    if any(p in {"", ".", ".."} for p in partes):
        raise ErroLeitura(
            "pasta_invalida",
            "Use o caminho relativo devolvido por list_folder.",
        )
    alvo = os.path.abspath(os.path.join(base, *partes))
    raiz_sep = base if base.endswith(os.sep) else base + os.sep
    if alvo != base and not alvo.startswith(raiz_sep):
        raise ErroLeitura(
            "pasta_invalida",
            "Use o caminho relativo devolvido por list_folder.",
        )
    if not os.path.isdir(alvo):
        return None
    return census_mod.caminho_estendido(alvo)


def _relativo(caminho: str, base: str) -> str:
    return os.path.relpath(caminho, base).replace(os.sep, "/")


def _empurrar_dir(
    entry: os.DirEntry[str],
    st: os.stat_result,
    cfg: census_mod.Config,
    sink: census_mod.Census,
    rel_dir: str,
    recursivo: bool,
) -> tuple[str, str] | None:
    regra = cfg.dir_rule(entry.name)
    if regra is not None:
        sink.excluded_dirs += 1
        sink.excluded_dir_names[entry.name] += 1
        sink.excluded_by_rule[f"dirs: {regra}"] += 1
        return None
    if _attrs(st) & _ATRIBUTO_REPARSE or stat.S_ISLNK(st.st_mode):
        sink.reparse_dirs.append(census_mod.caminho_normal(entry.path))
        return None
    if not recursivo:
        return None
    rel_novo = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
    sink.dirs += 1
    return entry.path, rel_novo


def _arquivo(
    root: census_mod.RootSpec,
    entry: os.DirEntry[str],
    st: os.stat_result,
    cfg: census_mod.Config,
    sink: census_mod.Census,
    rel_dir: str,
    base: str,
    depth: int,
) -> census_mod.FileEntry | None:
    regra = cfg.file_rule(entry.name, rel_dir)
    if regra is not None:
        sink.excluded_files += 1
        sink.excluded_by_rule[regra] += 1
        return None
    caminho = census_mod.caminho_normal(entry.path)
    rel = _relativo(caminho, base)
    return census_mod.FileEntry(
        root=root,
        path=caminho,
        rel=rel,
        size=st.st_size,
        mtime=st.st_mtime,
        depth=depth,
        top_folder=rel.split("/", 1)[0] if "/" in rel else (rel or "(raiz)"),
        attrs=_attrs(st),
    )


def _varrer(
    root: census_mod.RootSpec,
    cfg: census_mod.Config,
    sink: census_mod.Census,
    inicio: str,
    rel_inicio: str,
    recursivo: bool,
    visita: Visita,
) -> list[census_mod.FileEntry]:
    base = os.path.abspath(str(root.path))
    pilha: list[tuple[str, str, int]] = [(inicio, rel_inicio, rel_inicio.count("/") if rel_inicio else 0)]
    achados: list[census_mod.FileEntry] = []
    while pilha:
        directory, rel_dir, depth = pilha.pop()
        try:
            entradas = list(os.scandir(directory))
        except OSError as exc:
            sink.errors.append(f"{census_mod.caminho_normal(directory)}: {exc.strerror or exc}")
            continue
        for entry in entradas:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                sink.errors.append(f"{census_mod.caminho_normal(entry.path)}: {exc.strerror or exc}")
                continue
            if stat.S_ISDIR(st.st_mode):
                proximo = _empurrar_dir(entry, st, cfg, sink, rel_dir, recursivo)
                if proximo is not None:
                    pilha.append((proximo[0], proximo[1], depth + 1))
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            visita.arquivos += 1
            item = _arquivo(root, entry, st, cfg, sink, rel_dir, base, depth)
            if item is not None:
                achados.append(item)
    return achados


def iter_escopo(
    root: census_mod.RootSpec,
    cfg: census_mod.Config,
    pasta: str,
    *,
    recursivo: bool,
    sink: census_mod.Census,
) -> tuple[list[census_mod.FileEntry], Visita]:
    """Arquivos sob `pasta` nesta raiz, sem descer no resto do acervo."""
    visita = Visita()
    if not os.path.isdir(str(root.path)):
        sink.errors.append(f"{root.name}: raiz inacessível")
        return [], visita
    inicio = _diretorio_inicial(str(root.path), pasta)
    if inicio is None:
        return [], visita
    rel_inicio = normalizar_prefixo(pasta).rstrip("/")
    return _varrer(root, cfg, sink, inicio, rel_inicio, recursivo, visita), visita
