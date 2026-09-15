"""Corpus census — metadata only, never file content.

F0 deliverable: walk the configured roots and report what the corpus actually
is (count and size per extension, date distribution, folder depth, how many
files are cloud placeholders) so F1 invests in the parsers that matter.

Hard rule, see ARCHITECTURE.md "Armadilha do Files On-Demand": this module must
never open a file. On a synced SharePoint/OneDrive folder a file may be a
dehydrated placeholder, and reading one byte triggers a full download. Every
fact below comes from the directory entry (name, size, timestamps, Windows file
attributes) — obtained via os.scandir/lstat, which does not hydrate anything.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import stat
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .logger import get_logger

log = get_logger("census")

# --- Windows file attributes (winnt.h) -------------------------------------
# Available as os.stat_result.st_file_attributes on Windows only.
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_SYSTEM = 0x00000004
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

# A file carrying any of these is not fully on disk: opening it hydrates.
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

# Technical noise only. Nothing that could plausibly hold knowledge is excluded
# by default — extra exclusions belong in the config, and whatever is skipped is
# reported instead of silently dropped.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "$RECYCLE.BIN",
    "System Volume Information",
)
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    "~$*",  # Office lock files
    ".~lock.*",
    "*.tmp",
    "*.temp",
    "*.part",
    "*.crdownload",
    "Thumbs.db",
    "desktop.ini",
    ".DS_Store",
)

NO_EXTENSION = "(sem extensão)"

# Size bands for E6.1. Chosen so a generator can sample "small note / office
# file / big PDF / huge dump" without seeing a single path. Inclusive upper
# bound except the last, which is open.
FAIXAS_TAMANHO: tuple[tuple[int, str], ...] = (
    (16 * 1024, "<16KiB"),
    (64 * 1024, "16-64KiB"),
    (256 * 1024, "64-256KiB"),
    (1024 * 1024, "256KiB-1MiB"),
    (4 * 1024 * 1024, "1-4MiB"),
    (16 * 1024 * 1024, "4-16MiB"),
    (64 * 1024 * 1024, "16-64MiB"),
)
FAIXA_TAMANHO_RESTO = ">=64MiB"
EXTENSOES_PDF_DOCX = (".pdf", ".docx")
"""The already-published office mix (PDF+DOCX ~74% of a real archive)."""


@dataclass(frozen=True)
class RootSpec:
    """One configured corpus root."""

    name: str
    path: Path


@dataclass(frozen=True)
class RoleExclusion:
    """Exclusão por padrão de nome, mas só dentro de certas pastas.

    Um glob solto em `exclude_globs` casa pelo nome do arquivo em qualquer lugar
    da raiz, e isso **não** basta para pasta cujos arquivos carregam o *papel* no
    nome. Medido em 24/08/2026 (`docs/ablacao-f4-meetings.md`): o aplicativo de
    reuniões nomeia o relatório renderizado `*_relatorio.pdf`, e dois arquivos
    com exatamente essa forma moram fora da árvore de reuniões — um deles é a
    única cópia da sua reunião, sem transcrição em lugar nenhum. Escopo por pasta
    mantém fora os 178 relatórios redundantes e deixa esse um dentro; o glob
    solto o descartaria em silêncio, que é o pior modo de falha possível.

    `dirs` são prefixos de caminho relativos à raiz, com `/`. Vazio quer dizer
    "qualquer pasta", e aí a regra é equivalente a um glob solto.
    """

    globs: tuple[str, ...] = ()
    dirs: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Como esta regra aparece no aviso, na contagem e no relatório.

        Estável o suficiente para virar chave de contador: é o que a
        configuração escreveu, na ordem que escreveu."""
        onde = ", ".join(self.dirs) if self.dirs else "(qualquer pasta)"
        return f"papel: {', '.join(self.globs)} em {onde}"

    def covers(self, rel_dir: str) -> bool:
        if not self.dirs:
            return True
        target = rel_dir.replace("\\", "/").strip("/").lower()
        for d in self.dirs:
            prefix = d.replace("\\", "/").strip("/").lower()
            if not prefix or target == prefix or target.startswith(prefix + "/"):
                return True
        return False

    def matches(self, name: str, rel_dir: str) -> bool:
        if not self.covers(rel_dir):
            return False
        return _casa_algum(name, self.globs)


def _casa_algum(name: str, globs: tuple[str, ...]) -> bool:
    return _qual_casa(name, globs) is not None


def _qual_casa(name: str, globs: tuple[str, ...]) -> str | None:
    """Qual padrão casou, não só se casou.

    O booleano bastava enquanto ninguém precisava saber que uma regra declarada
    não tinha casado com nada. Passou a não bastar em 26/08/2026."""
    for g in globs:
        if fnmatch.fnmatch(name, g) or fnmatch.fnmatch(name.lower(), g.lower()):
            return g
    return None


@dataclass(frozen=True)
class DeclaredExclusions:
    """As exclusões que a **configuração** pediu — não as técnicas padrão.

    A conferência de efeito (`check_exclusions`) só vale para estas: `.git`,
    `node_modules` e `~$*` casarem zero é o esperado num acervo de escritório, e
    avisar sobre elas afogaria o aviso que importa.
    """

    dirs: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    roles: tuple[RoleExclusion, ...] = ()

    @property
    def vazio(self) -> bool:
        return not (self.dirs or self.globs or self.roles)


@dataclass
class Config:
    roots: list[RootSpec] = field(default_factory=list)
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    role_exclusions: tuple[RoleExclusion, ...] = ()
    declared: DeclaredExclusions = DeclaredExclusions()
    """Quais das exclusões acima vieram do arquivo de configuração.

    Existe só para a conferência: sem separar o declarado do padrão técnico, ou
    o aviso não sai (ninguém declarou nada) ou sai doze vezes por passada."""
    top: int = 15

    def validar_raizes(self) -> None:
        """Root names are the stable namespace used by FND-01b."""
        nomes = [root.name.strip() for root in self.roots]
        repetidos = sorted({nome for nome in nomes if nome and nomes.count(nome) > 1})
        if repetidos:
            raise ValueError(
                "nomes de raiz repetidos: " + ", ".join(repetidos)
                + "; informe um root_id único para cada raiz"
            )

    def dir_rule(self, name: str) -> str | None:
        """Qual entrada de `exclude_dirs` tira esta pasta."""
        lowered = name.lower()
        for d in self.exclude_dirs:
            if lowered == d.lower():
                return d
        return None

    def excluded_dir(self, name: str) -> bool:
        return self.dir_rule(name) is not None

    def file_rule(self, name: str, rel_dir: str = "") -> str | None:
        """Qual regra tira este arquivo, com rótulo — `None` se nenhuma tira.

        O rótulo é a chave de `Census.excluded_by_rule`. Atribuir a exclusão à
        regra custa o mesmo que decidir se há exclusão, e é a diferença entre
        "463 fora por papel" e "463 fora, sabe-se lá por quê"."""
        g = _qual_casa(name, self.exclude_globs)
        if g is not None:
            return f"globs: {g}"
        for r in self.role_exclusions:
            if r.matches(name, rel_dir):
                return r.label
        return None

    def excluded_file(self, name: str, rel_dir: str = "") -> bool:
        return self.file_rule(name, rel_dir) is not None


@dataclass
class Bucket:
    """Counters for one aggregation key."""

    files: int = 0
    bytes: int = 0
    cloud_only_files: int = 0
    cloud_only_bytes: int = 0

    def add(self, size: int, cloud_only: bool) -> None:
        self.files += 1
        self.bytes += size
        if cloud_only:
            self.cloud_only_files += 1
            self.cloud_only_bytes += size

    def as_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "bytes": self.bytes,
            "cloud_only_files": self.cloud_only_files,
            "cloud_only_bytes": self.cloud_only_bytes,
        }


def _bucket(mapping: dict[str, Bucket], key: str) -> Bucket:
    b = mapping.get(key)
    if b is None:
        b = mapping[key] = Bucket()
    return b


@dataclass
class Census:
    """Aggregated result of a walk. Holds no file content, by design."""

    total: Bucket = field(default_factory=Bucket)
    dirs: int = 0
    by_root: dict[str, Bucket] = field(default_factory=dict)
    by_extension: dict[str, Bucket] = field(default_factory=dict)
    by_year: dict[str, Bucket] = field(default_factory=dict)
    by_top_folder: dict[str, Bucket] = field(default_factory=dict)
    by_depth: Counter = field(default_factory=Counter)
    by_size: dict[str, Bucket] = field(default_factory=dict)
    pinned_files: int = 0
    unpinned_files: int = 0
    hidden_files: int = 0
    reparse_dirs: list[str] = field(default_factory=list)
    excluded_files: int = 0
    excluded_dirs: int = 0
    excluded_dir_names: Counter = field(default_factory=Counter)
    excluded_by_rule: Counter = field(default_factory=Counter)
    """Quantas entradas cada regra de exclusão tirou desta passada, por rótulo.

    Existe porque regra que não casa com nada **falha em silêncio**, e o
    silêncio parece sucesso. Medido em 26/08/2026: uma regra de papel escrita
    com o prefixo errado (`16. Anexos volumosos` onde o caminho relativo à raiz
    era `corpus/16. Anexos volumosos`) casou com zero arquivos, a passada correu
    inteira como se a exclusão existisse, e o custo foi 3 h 22 min de máquina e
    uma medição contaminada. É a mesma classe que o `.gitignore` por nome já
    tinha custado em 20/08 — quatro `metricas-f2-*` commitados."""
    role_scope_dirs: Counter = field(default_factory=Counter)
    """Quantas pastas o escopo `dirs` de cada regra de papel alcançou.

    Separa os dois motivos de uma regra não casar nada, que pedem correções
    diferentes: prefixo apontando para pasta nenhuma (escopo zero) ou pasta
    certa e glob que não casa (escopo > 0)."""
    largest: list[tuple[int, str]] = field(default_factory=list)
    oldest_mtime: float | None = None
    newest_mtime: float | None = None
    errors: list[str] = field(default_factory=list)
    attributes_available: bool = True

    def add_file(
        self,
        *,
        root: RootSpec,
        path: str,
        size: int,
        mtime: float,
        depth: int,
        top_folder: str,
        attrs: int,
    ) -> None:
        cloud_only = bool(attrs & CLOUD_ONLY_MASK)
        self.total.add(size, cloud_only)
        _bucket(self.by_root, root.name).add(size, cloud_only)
        _bucket(self.by_extension, _extension_of(path)).add(size, cloud_only)
        _bucket(self.by_year, _year_of(mtime)).add(size, cloud_only)
        _bucket(self.by_top_folder, f"{root.name}/{top_folder}").add(size, cloud_only)
        _bucket(self.by_size, faixa_tamanho(size)).add(size, cloud_only)
        self.by_depth[depth] += 1

        if attrs & FILE_ATTRIBUTE_PINNED:
            self.pinned_files += 1
        if attrs & FILE_ATTRIBUTE_UNPINNED:
            self.unpinned_files += 1
        if attrs & FILE_ATTRIBUTE_HIDDEN:
            self.hidden_files += 1

        if self.oldest_mtime is None or mtime < self.oldest_mtime:
            self.oldest_mtime = mtime
        if self.newest_mtime is None or mtime > self.newest_mtime:
            self.newest_mtime = mtime

        self.largest.append((size, path))
        if len(self.largest) > 200:  # keep the list bounded on huge corpora
            self.largest.sort(reverse=True)
            del self.largest[50:]

    def top_largest(self, n: int) -> list[tuple[int, str]]:
        return sorted(self.largest, reverse=True)[:n]

    def as_dict(self, top: int = 15) -> dict:
        return {
            "total": self.total.as_dict(),
            "dirs": self.dirs,
            "by_root": {k: v.as_dict() for k, v in self.by_root.items()},
            "by_extension": {k: v.as_dict() for k, v in _sorted_by_files(self.by_extension)},
            "by_year": {k: v.as_dict() for k, v in sorted(self.by_year.items())},
            "by_top_folder": {k: v.as_dict() for k, v in _sorted_by_files(self.by_top_folder)},
            "by_depth": dict(sorted(self.by_depth.items())),
            "by_size": {k: v.as_dict() for k, v in self.by_size.items()},
            "pinned_files": self.pinned_files,
            "unpinned_files": self.unpinned_files,
            "hidden_files": self.hidden_files,
            "reparse_dirs": self.reparse_dirs,
            "excluded_files": self.excluded_files,
            "excluded_dirs": self.excluded_dirs,
            "excluded_dir_names": dict(self.excluded_dir_names),
            "excluded_by_rule": dict(self.excluded_by_rule),
            "role_scope_dirs": dict(self.role_scope_dirs),
            "largest": [{"bytes": s, "path": p} for s, p in self.top_largest(top)],
            "oldest_mtime": self.oldest_mtime,
            "newest_mtime": self.newest_mtime,
            "attributes_available": self.attributes_available,
            "errors": self.errors,
        }


# --- helpers ---------------------------------------------------------------


def faixa_tamanho(n: int) -> str:
    """Which E6.1 size band this file falls in. No path involved."""
    n = max(0, int(n))
    for teto, nome in FAIXAS_TAMANHO:
        if n < teto:
            return nome
    return FAIXA_TAMANHO_RESTO


def distribuicao_de(census: Census) -> dict[str, object]:
    """Shape of an archive for the synthetic generator — never a filename.

    E6.1. The census JSON (`as_dict`) carries `largest.path` and folder
    names; those must not leave this machine. This dict is the contract the
    generator can consume: format mix, size bands, folder depth, and the
    PDF+DOCX fraction already published as ~74% of a real office archive.
    """
    total = census.total.files
    denom = max(1, total)

    def _frac(n: int) -> float:
        return round(n / denom, 6)

    formato = {
        ext: {
            "arquivos": b.files,
            "bytes": b.bytes,
            "fracao": _frac(b.files),
        }
        for ext, b in _sorted_by_files(census.by_extension)
    }
    pdf_docx = sum(census.by_extension[e].files for e in EXTENSOES_PDF_DOCX if e in census.by_extension)
    return {
        "arquivos": total,
        "bytes": census.total.bytes,
        "formato": formato,
        "fracao_pdf_docx": _frac(pdf_docx),
        "tamanho": {
            nome: {
                "arquivos": b.files,
                "bytes": b.bytes,
                "fracao": _frac(b.files),
            }
            for nome, b in census.by_size.items()
        },
        "profundidade": {
            str(depth): {"arquivos": count, "fracao": _frac(count)}
            for depth, count in sorted(census.by_depth.items())
        },
    }


def _tem_caminho(obj: object) -> bool:
    """True if a nested dict still carries a path — the leak E6.1 exists to stop."""
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave in {"path", "caminho", "largest", "by_top_folder", "by_root", "reparse_dirs"}:
                return True
            if _tem_caminho(valor):
                return True
    elif isinstance(obj, (list, tuple)):
        return any(_tem_caminho(item) for item in obj)
    return False


def _extension_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext or NO_EXTENSION


def _year_of(mtime: float) -> str:
    try:
        # noqa DTZ006: hora local ingênua é o certo aqui. `mtime` é do sistema de
        # arquivos do usuário e o relatório é lido por ele; converter para UTC
        # mudaria o ano de arquivos criados na virada, sem ninguém pedir.
        return datetime.fromtimestamp(mtime).strftime("%Y")  # noqa: DTZ006
    except (OSError, OverflowError, ValueError):
        return "(data inválida)"


def _sorted_by_files(mapping: dict[str, Bucket]) -> list[tuple[str, Bucket]]:
    return sorted(mapping.items(), key=lambda kv: (-kv[1].files, kv[0]))


def is_cloud_only(attrs: int) -> bool:
    """True when the file's content is not on disk — opening it would download."""
    return bool(attrs & CLOUD_ONLY_MASK)


def human_bytes(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} TB"


def _attrs_of(st: os.stat_result) -> int:
    return getattr(st, "st_file_attributes", 0)


# --- long paths ------------------------------------------------------------
# The classic Windows limit is 260 characters, and it bites during *directory
# enumeration*, not just when opening a file: scandir on a deep folder fails
# with "o sistema não pode encontrar o caminho especificado" and everything
# below it silently disappears from the census. Found in the real corpus on 17
# DataRoom folders. The extended-length prefix lifts the limit.

_PREFIXO_LONGO = "\\\\?\\"
_PREFIXO_UNC = "\\\\?\\UNC\\"


def caminho_estendido(path: str) -> str:
    """Add the \\\\?\\ prefix on Windows so long paths work. No-op elsewhere."""
    if os.name != "nt":
        return path
    absoluto = os.path.abspath(path)
    if absoluto.startswith(_PREFIXO_LONGO):
        return absoluto
    if absoluto.startswith("\\\\"):  # UNC share
        return _PREFIXO_UNC + absoluto[2:]
    return _PREFIXO_LONGO + absoluto


def caminho_normal(path: str) -> str:
    """Strip the extended-length prefix, for display and for relative paths."""
    if path.startswith(_PREFIXO_UNC):
        return "\\\\" + path[len(_PREFIXO_UNC) :]
    if path.startswith(_PREFIXO_LONGO):
        return path[len(_PREFIXO_LONGO) :]
    return path


# --- walk ------------------------------------------------------------------


@dataclass(frozen=True)
class FileEntry:
    """One file found during a walk. Metadata only — content is never read."""

    root: RootSpec
    path: str  # absolute
    rel: str  # relative to the root, always with "/" — matches the golden set
    size: int
    mtime: float
    depth: int
    top_folder: str
    attrs: int

    @property
    def cloud_only(self) -> bool:
        return is_cloud_only(self.attrs)


def _contar_escopo(cfg: Config, sink: Census, rel_dir: str) -> None:
    """Registra que esta pasta caiu no escopo `dirs` de cada regra de papel."""
    for r in cfg.role_exclusions:
        if r.dirs and r.covers(rel_dir):
            sink.role_scope_dirs[r.label] += 1


def iter_files(root: RootSpec, cfg: Config, sink: Census | None = None) -> Iterator[FileEntry]:
    """Yield every file under a root, applying the configured exclusions.

    The single traversal used by both the census and the retrieval baseline —
    they must see exactly the same corpus, or the metrics measure a different
    set of documents than the census reported. Counters for excluded entries
    and access errors go to `sink` when one is given.
    """
    base = str(root.path)
    stack: list[tuple[str, int, str, str]] = [(caminho_estendido(base), 0, "", "")]
    if sink is not None:
        # A própria raiz conta como pasta alcançada: uma regra sem `dirs` cobre
        # tudo, e uma com `dirs` pode apontar para a raiz.
        _contar_escopo(cfg, sink, "")
    while stack:
        directory, depth, top_folder, rel_dir = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            if sink is not None:
                sink.errors.append(f"{caminho_normal(directory)}: {exc.strerror or exc}")
            continue

        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                if sink is not None:
                    sink.errors.append(f"{caminho_normal(entry.path)}: {exc.strerror or exc}")
                continue

            attrs = _attrs_of(st)
            if stat.S_ISDIR(st.st_mode):
                regra_dir = cfg.dir_rule(entry.name)
                if regra_dir is not None:
                    if sink is not None:
                        sink.excluded_dirs += 1
                        sink.excluded_dir_names[entry.name] += 1
                        sink.excluded_by_rule[f"dirs: {regra_dir}"] += 1
                    continue
                if attrs & FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(st.st_mode):
                    # Junction / symlink: record it, do not descend (cycles, and
                    # it would double-count content reachable elsewhere).
                    if sink is not None:
                        sink.reparse_dirs.append(caminho_normal(entry.path))
                    continue
                rel_novo = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                if sink is not None:
                    sink.dirs += 1
                    _contar_escopo(cfg, sink, rel_novo)
                stack.append((entry.path, depth + 1, top_folder or entry.name, rel_novo))
                continue

            if not stat.S_ISREG(st.st_mode):
                continue
            regra_arquivo = cfg.file_rule(entry.name, rel_dir)
            if regra_arquivo is not None:
                if sink is not None:
                    sink.excluded_files += 1
                    sink.excluded_by_rule[regra_arquivo] += 1
                continue

            caminho = caminho_normal(entry.path)
            yield FileEntry(
                root=root,
                path=caminho,
                rel=os.path.relpath(caminho, base).replace(os.sep, "/"),
                size=st.st_size,
                mtime=st.st_mtime,
                depth=depth,
                top_folder=top_folder or "(raiz)",
                attrs=attrs,
            )


def walk_root(root: RootSpec, cfg: Config, census: Census) -> None:
    """Walk one root and fold every file into the census."""
    for f in iter_files(root, cfg, sink=census):
        census.add_file(
            root=f.root,
            path=f.path,
            size=f.size,
            mtime=f.mtime,
            depth=f.depth,
            top_folder=f.top_folder,
            attrs=f.attrs,
        )


# --- conferência das exclusões declaradas ----------------------------------
# Uma regra de exclusão que não casa com nada não devolve erro nenhum: a passada
# corre inteira e o resultado *parece* certo, porque menos arquivos é o que se
# pediu. O único jeito de perceber é contar por regra e comparar com zero — e
# isso tem de acontecer **antes** de abrir o primeiro arquivo, senão o aviso
# chega depois do custo. Ver `docs/regra-de-ouro.md` regra 12: o defeito não se
# remenda no `config.e1.toml`, se generaliza aqui.


def check_exclusions(cfg: Config, census: Census) -> list[str]:
    """Regras declaradas que não tiraram nada, em texto de aviso.

    Chamar depois de percorrer as raízes inteiras (o `sink` tem de ser o mesmo
    `Census` da passada) e antes de abrir qualquer conteúdo. Lista vazia = toda
    regra declarada teve efeito.
    """
    avisos: list[str] = []
    for d in cfg.declared.dirs:
        if not census.excluded_by_rule.get(f"dirs: {d}"):
            avisos.append(
                f"exclusão sem efeito — `dirs = \"{d}\"` não casou com nenhuma pasta. "
                "`dirs` casa pelo **nome** da pasta, em qualquer nível; caminho com "
                "`/` nunca casa"
            )
    for g in cfg.declared.globs:
        if not census.excluded_by_rule.get(f"globs: {g}"):
            avisos.append(
                f"exclusão sem efeito — `globs = \"{g}\"` não casou com nenhum arquivo"
            )
    for r in cfg.declared.roles:
        if census.excluded_by_rule.get(r.label):
            continue
        if r.dirs and not census.role_scope_dirs.get(r.label):
            avisos.append(
                f"exclusão sem efeito — a regra de papel `{r.label}` não alcançou nenhuma "
                "pasta. `dirs` são **prefixos de caminho relativos à raiz**, com `/`, e não "
                "nomes de pasta soltos: se o corpus mora em `<raiz>/corpus/`, o prefixo "
                "precisa começar por `corpus/`"
            )
        else:
            alcance = census.role_scope_dirs.get(r.label, census.dirs)
            avisos.append(
                f"exclusão sem efeito — a regra de papel `{r.label}` alcançou {alcance} "
                "pasta(s), mas nenhum arquivo casou com os globs"
            )
    return avisos


def relatar_exclusoes(cfg: Config, census: Census) -> dict[str, object]:
    """O que a passada excluiu, por regra, mais os avisos. Vai no `progresso.json`."""
    return {
        "por_regra": dict(census.excluded_by_rule),
        "arquivos": census.excluded_files,
        "pastas": census.excluded_dirs,
        "inertes": check_exclusions(cfg, census),
    }


def run_census(roots: list[RootSpec], cfg: Config | None = None) -> Census:
    """Walk every root and return the aggregated census."""
    cfg = cfg or Config(roots=roots)
    census = Census(attributes_available=(os.name == "nt"))
    if not census.attributes_available:
        log.warning(
            "st_file_attributes indisponível fora do Windows — "
            "a contagem de placeholders de nuvem será zero"
        )
    for root in roots:
        if not root.path.exists():
            census.errors.append(f"{root.path}: raiz inexistente")
            log.error("raiz inexistente: %s", root.path)
            continue
        log.info("percorrendo raiz '%s': %s", root.name, root.path)
        walk_root(root, cfg, census)
        bucket = census.by_root.get(root.name, Bucket())
        log.info(
            "raiz '%s': %d arquivos, %s (%d placeholders)",
            root.name,
            bucket.files,
            human_bytes(bucket.bytes),
            bucket.cloud_only_files,
        )
    for aviso in check_exclusions(cfg, census):
        log.warning("%s", aviso)
    return census


# --- report ----------------------------------------------------------------


def _fmt_date(ts: float | None) -> str:
    if ts is None:
        return "—"
    try:
        # noqa DTZ006: mesma razão de `_year_of` — data local, para leitura humana.
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")  # noqa: DTZ006
    except (OSError, OverflowError, ValueError):
        return "(inválida)"


def render_markdown(census: Census, cfg: Config, roots: list[RootSpec]) -> str:
    total = census.total
    lines: list[str] = []
    add = lines.append

    add("# Censo do corpus")
    add("")
    add("Somente metadados. Nenhum arquivo foi aberto — ler um placeholder do")
    add("SharePoint dispararia download (ver ARCHITECTURE.md §3).")
    add("")
    add("## Raízes")
    add("")
    add("| Raiz | Caminho | Arquivos | Tamanho | Placeholders |")
    add("|------|---------|---------:|--------:|-------------:|")
    for root in roots:
        b = census.by_root.get(root.name, Bucket())
        add(f"| {root.name} | `{root.path}` | {b.files} | {human_bytes(b.bytes)} | {b.cloud_only_files} |")
    add("")

    add("## Totais")
    add("")
    add(f"- Arquivos: **{total.files}** em {census.dirs} pastas")
    add(f"- Tamanho lógico: **{human_bytes(total.bytes)}**")
    add(
        f"- Placeholders de nuvem: **{total.cloud_only_files}** "
        f"({human_bytes(total.cloud_only_bytes)} que um indexador ingênuo baixaria)"
    )
    if not census.attributes_available:
        add("  - ⚠️ atributos de nuvem não disponíveis nesta plataforma; contagem não confiável")
    add(f"- Pinados / não-pinados: {census.pinned_files} / {census.unpinned_files}")
    add(f"- Ocultos: {census.hidden_files}")
    add(f"- Modificação mais antiga: {_fmt_date(census.oldest_mtime)} · mais recente: {_fmt_date(census.newest_mtime)}")
    add(f"- Excluídos por padrão: {census.excluded_files} arquivos, {census.excluded_dirs} pastas")
    if census.reparse_dirs:
        add(f"- Junctions/symlinks não percorridos: {len(census.reparse_dirs)}")
    if census.errors:
        add(f"- Erros de acesso: {len(census.errors)}")
    add("")

    if not cfg.declared.vazio:
        add("## Exclusões declaradas")
        add("")
        add("Contagem por regra, e não só o total: regra que não casa com nada")
        add("falha em silêncio, e menos arquivos é justamente o que se pediu.")
        add("")
        add("| Regra | Entradas excluídas |")
        add("|-------|-------------------:|")
        for d in cfg.declared.dirs:
            add(f"| `dirs: {d}` | {census.excluded_by_rule.get(f'dirs: {d}', 0)} |")
        for g in cfg.declared.globs:
            add(f"| `globs: {g}` | {census.excluded_by_rule.get(f'globs: {g}', 0)} |")
        for r in cfg.declared.roles:
            add(f"| `{r.label}` | {census.excluded_by_rule.get(r.label, 0)} |")
        add("")
        inertes = check_exclusions(cfg, census)
        if inertes:
            for aviso in inertes:
                add(f"- ⚠️ {aviso}")
        else:
            add("Toda regra declarada teve efeito.")
        add("")

    add("## Por extensão")
    add("")
    add("| Extensão | Arquivos | % arquivos | Tamanho | Placeholders |")
    add("|----------|---------:|-----------:|--------:|-------------:|")
    ranked = _sorted_by_files(census.by_extension)
    for ext, b in ranked[: cfg.top]:
        pct = (b.files / total.files * 100) if total.files else 0.0
        add(f"| `{ext}` | {b.files} | {pct:.1f}% | {human_bytes(b.bytes)} | {b.cloud_only_files} |")
    if len(ranked) > cfg.top:
        rest = ranked[cfg.top :]
        files = sum(b.files for _, b in rest)
        size = sum(b.bytes for _, b in rest)
        add(f"| _outras {len(rest)} extensões_ | {files} | — | {human_bytes(size)} | — |")
    add("")

    add("## Por ano de modificação")
    add("")
    add("| Ano | Arquivos | Tamanho |")
    add("|-----|---------:|--------:|")
    for year, b in sorted(census.by_year.items()):
        add(f"| {year} | {b.files} | {human_bytes(b.bytes)} |")
    add("")

    add("## Pastas de primeiro nível")
    add("")
    add("| Pasta | Arquivos | Tamanho |")
    add("|-------|---------:|--------:|")
    for name, b in _sorted_by_files(census.by_top_folder)[: cfg.top]:
        add(f"| `{name}` | {b.files} | {human_bytes(b.bytes)} |")
    add("")

    add("## Profundidade")
    add("")
    add("| Nível | Arquivos |")
    add("|------:|---------:|")
    for depth, count in sorted(census.by_depth.items()):
        add(f"| {depth} | {count} |")
    add("")

    add("## Maiores arquivos")
    add("")
    add("| Tamanho | Caminho |")
    add("|--------:|---------|")
    for size, path in census.top_largest(cfg.top):
        add(f"| {human_bytes(size)} | `{path}` |")
    add("")

    if census.errors:
        add("## Erros de acesso")
        add("")
        for err in census.errors[:50]:
            add(f"- `{err}`")
        if len(census.errors) > 50:
            add(f"- _… e mais {len(census.errors) - 50}_")
        add("")

    return "\n".join(lines)


# --- config / CLI ----------------------------------------------------------


def load_config(path: Path) -> Config:
    """Load roots and exclusions from a TOML file.

    [[roots]]
    name = "pessoal"
    path = 'C:\\Users\\...\\Documentos'

    [exclude]
    dirs = ["Backups"]
    globs = ["*.bak"]
    papel = [{ dirs = ["Meetings"], globs = ["*_relatorio.pdf"] }]
    """
    import tomllib

    with path.open("rb") as fh:  # config file, not corpus content
        data = tomllib.load(fh)

    roots: list[RootSpec] = []
    for i, entry in enumerate(data.get("roots", []), start=1):
        if "path" not in entry:
            raise ValueError(f"raiz #{i} em {path} não tem 'path'")
        roots.append(RootSpec(name=entry.get("name") or f"raiz{i}", path=Path(entry["path"])))

    exclude = data.get("exclude", {})
    cfg = Config(roots=roots, top=int(data.get("top", 15)))
    declarados_dirs: tuple[str, ...] = ()
    declarados_globs: tuple[str, ...] = ()
    if "dirs" in exclude:
        declarados_dirs = tuple(str(d) for d in exclude["dirs"])
        cfg.exclude_dirs = DEFAULT_EXCLUDE_DIRS + declarados_dirs
    if "globs" in exclude:
        declarados_globs = tuple(str(g) for g in exclude["globs"])
        cfg.exclude_globs = DEFAULT_EXCLUDE_GLOBS + declarados_globs
    # `papel` também aqui, e não só em `config.py`: este é o caminho que o
    # baseline do eval usa, e ele tem de enumerar o MESMO universo que o
    # indexador. Duas listas de exclusão divergentes medem escala e creditam ao
    # ranqueador — é o erro que o comentário do próprio census.toml previne.
    papel = exclude.get("papel")
    if papel:
        if isinstance(papel, dict):
            papel = [papel]
        cfg.role_exclusions = tuple(
            RoleExclusion(globs=tuple(r.get("globs", ())), dirs=tuple(r.get("dirs", ())))
            for r in papel
        )
    cfg.declared = DeclaredExclusions(
        dirs=declarados_dirs, globs=declarados_globs, roles=cfg.role_exclusions
    )
    return cfg


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="segundocerebro-censo",
        description="Censo do corpus: contagem por extensão, tamanho, datas e placeholders de nuvem. "
        "Lê somente metadados, nunca abre conteúdo.",
    )
    parser.add_argument("roots", nargs="*", help="caminhos das raízes (alternativa a --config)")
    parser.add_argument("--config", type=Path, help="arquivo TOML com as raízes")
    parser.add_argument("--json", type=Path, dest="json_out", help="grava o resultado em JSON")
    parser.add_argument(
        "--distribuicao",
        type=Path,
        help="grava só a forma do acervo (formato/tamanho/profundidade), sem nomes de arquivo. "
        "É o contrato do E6.1 para o gerador sintético.",
    )
    parser.add_argument("--out", type=Path, help="grava o relatório markdown (padrão: stdout)")
    parser.add_argument("--exclude-dir", action="append", default=[], help="nome de pasta a excluir (repetível)")
    parser.add_argument("--exclude-glob", action="append", default=[], help="padrão de arquivo a excluir (repetível)")
    parser.add_argument("--top", type=int, default=15, help="quantas linhas nas tabelas de ranking")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.config:
        cfg = load_config(args.config)
    elif args.roots:
        cfg = Config(roots=[RootSpec(name=Path(r).name or r, path=Path(r)) for r in args.roots])
    else:
        log.error("informe as raízes como argumento ou use --config")
        return 2

    cfg.top = args.top
    if args.exclude_dir:
        cfg.exclude_dirs = tuple(cfg.exclude_dirs) + tuple(args.exclude_dir)
    if args.exclude_glob:
        cfg.exclude_globs = tuple(cfg.exclude_globs) + tuple(args.exclude_glob)
    if args.exclude_dir or args.exclude_glob:
        # Exclusão pedida na linha de comando é declaração como qualquer outra —
        # e é a mais fácil de errar, porque não fica escrita em lugar nenhum.
        cfg.declared = DeclaredExclusions(
            dirs=tuple(cfg.declared.dirs) + tuple(args.exclude_dir),
            globs=tuple(cfg.declared.globs) + tuple(args.exclude_glob),
            roles=cfg.declared.roles,
        )

    if not cfg.roots:
        log.error("nenhuma raiz configurada")
        return 2

    census = run_census(cfg.roots, cfg)

    report = render_markdown(census, cfg, cfg.roots)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        log.info("relatório gravado em %s", args.out)
    else:
        sys.stdout.write(report + "\n")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(census.as_dict(cfg.top), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("JSON gravado em %s", args.json_out)

    if args.distribuicao:
        forma = distribuicao_de(census)
        args.distribuicao.parent.mkdir(parents=True, exist_ok=True)
        args.distribuicao.write_text(
            json.dumps(forma, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("distribuição gravada em %s", args.distribuicao)

    if census.total.cloud_only_files:
        log.warning(
            "%d arquivos são placeholders de nuvem (%s). Política de hidratação é decisão da F1.",
            census.total.cloud_only_files,
            human_bytes(census.total.cloud_only_bytes),
        )
    return 1 if census.errors and census.total.files == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
