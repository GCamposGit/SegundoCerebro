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
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(name.lower(), g.lower()) for g in globs)


@dataclass
class Config:
    roots: list[RootSpec] = field(default_factory=list)
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    role_exclusions: tuple[RoleExclusion, ...] = ()
    top: int = 15

    def excluded_dir(self, name: str) -> bool:
        lowered = name.lower()
        return any(lowered == d.lower() for d in self.exclude_dirs)

    def excluded_file(self, name: str, rel_dir: str = "") -> bool:
        if _casa_algum(name, self.exclude_globs):
            return True
        return any(r.matches(name, rel_dir) for r in self.role_exclusions)


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
    pinned_files: int = 0
    unpinned_files: int = 0
    hidden_files: int = 0
    reparse_dirs: list[str] = field(default_factory=list)
    excluded_files: int = 0
    excluded_dirs: int = 0
    excluded_dir_names: Counter = field(default_factory=Counter)
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
            "pinned_files": self.pinned_files,
            "unpinned_files": self.unpinned_files,
            "hidden_files": self.hidden_files,
            "reparse_dirs": self.reparse_dirs,
            "excluded_files": self.excluded_files,
            "excluded_dirs": self.excluded_dirs,
            "excluded_dir_names": dict(self.excluded_dir_names),
            "largest": [{"bytes": s, "path": p} for s, p in self.top_largest(top)],
            "oldest_mtime": self.oldest_mtime,
            "newest_mtime": self.newest_mtime,
            "attributes_available": self.attributes_available,
            "errors": self.errors,
        }


# --- helpers ---------------------------------------------------------------


def _extension_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext or NO_EXTENSION


def _year_of(mtime: float) -> str:
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y")
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


def iter_files(root: RootSpec, cfg: Config, sink: Census | None = None) -> Iterator[FileEntry]:
    """Yield every file under a root, applying the configured exclusions.

    The single traversal used by both the census and the retrieval baseline —
    they must see exactly the same corpus, or the metrics measure a different
    set of documents than the census reported. Counters for excluded entries
    and access errors go to `sink` when one is given.
    """
    base = str(root.path)
    stack: list[tuple[str, int, str, str]] = [(caminho_estendido(base), 0, "", "")]
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
                if cfg.excluded_dir(entry.name):
                    if sink is not None:
                        sink.excluded_dirs += 1
                        sink.excluded_dir_names[entry.name] += 1
                    continue
                if attrs & FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(st.st_mode):
                    # Junction / symlink: record it, do not descend (cycles, and
                    # it would double-count content reachable elsewhere).
                    if sink is not None:
                        sink.reparse_dirs.append(caminho_normal(entry.path))
                    continue
                if sink is not None:
                    sink.dirs += 1
                stack.append(
                    (
                        entry.path,
                        depth + 1,
                        top_folder or entry.name,
                        f"{rel_dir}/{entry.name}" if rel_dir else entry.name,
                    )
                )
                continue

            if not stat.S_ISREG(st.st_mode):
                continue
            if cfg.excluded_file(entry.name, rel_dir):
                if sink is not None:
                    sink.excluded_files += 1
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
    return census


# --- report ----------------------------------------------------------------


def _fmt_date(ts: float | None) -> str:
    if ts is None:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
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
    if "dirs" in exclude:
        cfg.exclude_dirs = DEFAULT_EXCLUDE_DIRS + tuple(exclude["dirs"])
    if "globs" in exclude:
        cfg.exclude_globs = DEFAULT_EXCLUDE_GLOBS + tuple(exclude["globs"])
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

    if census.total.cloud_only_files:
        log.warning(
            "%d arquivos são placeholders de nuvem (%s). Política de hidratação é decisão da F1.",
            census.total.cloud_only_files,
            human_bytes(census.total.cloud_only_bytes),
        )
    return 1 if census.errors and census.total.files == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
