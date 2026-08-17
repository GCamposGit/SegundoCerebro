"""Tests for the corpus census.

The census only ever reads directory metadata; the most important test here is
the one that proves no file is opened (test_never_opens_file_content). Reading a
SharePoint placeholder would trigger a download, so that guarantee is a
correctness requirement, not a nicety.
"""

from __future__ import annotations

import builtins
import json
import os
from pathlib import Path

import pytest

from segundocerebro import census as census_mod
from segundocerebro.census import (
    CLOUD_ONLY_MASK,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    Config,
    RootSpec,
    human_bytes,
    is_cloud_only,
    load_config,
    render_markdown,
    run_census,
)


def make_tree(root: Path) -> None:
    """Small corpus resembling the real one: Office files, noise, nested folders."""
    (root / "Contratos" / "2025").mkdir(parents=True)
    (root / "Atas").mkdir()
    (root / "node_modules").mkdir()

    (root / "resumo.pdf").write_bytes(b"x" * 1000)
    (root / "Contratos" / "contrato-001.pdf").write_bytes(b"x" * 2000)
    (root / "Contratos" / "2025" / "aditivo.docx").write_bytes(b"x" * 300)
    (root / "Contratos" / "2025" / "planilha.XLSX").write_bytes(b"x" * 500)
    (root / "Atas" / "ata-12-03.docx").write_bytes(b"x" * 400)
    (root / "Atas" / "sem_extensao").write_bytes(b"x" * 10)

    # noise that must be excluded
    (root / "Atas" / "~$ata-12-03.docx").write_bytes(b"x" * 50)
    (root / "rascunho.tmp").write_bytes(b"x" * 50)
    (root / "node_modules" / "lib.js").write_bytes(b"x" * 9999)


@pytest.fixture
def corpus(tmp_path: Path) -> RootSpec:
    root = tmp_path / "pessoal"
    root.mkdir()
    make_tree(root)
    return RootSpec(name="pessoal", path=root)


def test_counts_and_sizes_by_extension(corpus: RootSpec) -> None:
    result = run_census([corpus])

    assert result.total.files == 6
    assert result.total.bytes == 1000 + 2000 + 300 + 500 + 400 + 10
    assert result.by_extension[".pdf"].files == 2
    assert result.by_extension[".pdf"].bytes == 3000
    # extension matching is case-insensitive: .XLSX lands in .xlsx
    assert result.by_extension[".xlsx"].files == 1
    assert result.by_extension[census_mod.NO_EXTENSION].files == 1
    assert result.errors == []


def test_excludes_noise_and_reports_it(corpus: RootSpec) -> None:
    result = run_census([corpus])

    assert ".tmp" not in result.by_extension
    assert ".js" not in result.by_extension  # node_modules never descended
    assert result.excluded_files == 2  # ~$ata-12-03.docx and rascunho.tmp
    assert result.excluded_dirs == 1
    assert result.excluded_dir_names["node_modules"] == 1


def test_depth_and_top_folder(corpus: RootSpec) -> None:
    result = run_census([corpus])

    assert result.by_depth[0] == 1  # resumo.pdf at the root
    assert result.by_depth[1] == 3  # Contratos/*, Atas/*
    assert result.by_depth[2] == 2  # Contratos/2025/*
    assert result.by_top_folder["pessoal/Contratos"].files == 3
    assert result.by_top_folder["pessoal/(raiz)"].files == 1


def test_date_distribution_present(corpus: RootSpec) -> None:
    result = run_census([corpus])

    assert sum(b.files for b in result.by_year.values()) == result.total.files
    assert result.oldest_mtime is not None
    assert result.newest_mtime >= result.oldest_mtime


def test_extra_exclusions_from_config(corpus: RootSpec) -> None:
    cfg = Config(
        roots=[corpus],
        exclude_dirs=census_mod.DEFAULT_EXCLUDE_DIRS + ("Atas",),
        exclude_globs=census_mod.DEFAULT_EXCLUDE_GLOBS + ("*.xlsx",),
    )
    result = run_census([corpus], cfg)

    assert "pessoal/Atas" not in result.by_top_folder
    assert ".xlsx" not in result.by_extension
    # left: resumo.pdf, contrato-001.pdf, aditivo.docx
    assert result.total.files == 3
    assert result.by_extension[".docx"].files == 1


@pytest.mark.parametrize(
    "attrs,expected",
    [
        (0, False),
        (FILE_ATTRIBUTE_HIDDEN, False),
        (FILE_ATTRIBUTE_OFFLINE, True),
        (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, True),
        (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, True),
        (CLOUD_ONLY_MASK, True),
    ],
)
def test_is_cloud_only(attrs: int, expected: bool) -> None:
    assert is_cloud_only(attrs) is expected


def test_placeholders_are_counted_not_hydrated(corpus: RootSpec, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a synced SharePoint folder where the .pdf files are dehydrated."""
    real_attrs = census_mod._attrs_of

    def fake_attrs(st: os.stat_result) -> int:
        # 2000 bytes is contrato-001.pdf in the fixture tree
        return FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS if st.st_size == 2000 else real_attrs(st)

    monkeypatch.setattr(census_mod, "_attrs_of", fake_attrs)
    result = run_census([corpus])

    assert result.total.cloud_only_files == 1
    assert result.total.cloud_only_bytes == 2000
    assert result.by_extension[".pdf"].cloud_only_files == 1


def test_never_opens_file_content(corpus: RootSpec, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"o censo tentou abrir conteúdo: {args!r}")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)

    result = run_census([corpus])

    assert result.total.files == 6


def test_missing_root_is_reported_not_raised(tmp_path: Path) -> None:
    ghost = RootSpec(name="fantasma", path=tmp_path / "nao-existe")
    result = run_census([ghost])

    assert result.total.files == 0
    assert any("inexistente" in err for err in result.errors)


def test_multiple_roots_are_kept_separate(corpus: RootSpec, tmp_path: Path) -> None:
    other = tmp_path / "sharepoint"
    other.mkdir()
    (other / "apresentacao.pptx").write_bytes(b"x" * 700)
    second = RootSpec(name="sharepoint", path=other)

    result = run_census([corpus, second])

    assert result.by_root["pessoal"].files == 6
    assert result.by_root["sharepoint"].files == 1
    assert result.total.files == 7


def test_render_markdown_has_the_sections_f0_requires(corpus: RootSpec) -> None:
    cfg = Config(roots=[corpus])
    report = render_markdown(run_census([corpus], cfg), cfg, [corpus])

    for heading in ("# Censo do corpus", "## Por extensão", "## Por ano de modificação", "## Profundidade"):
        assert heading in report
    assert "Placeholders de nuvem" in report
    assert "`.pdf`" in report


def test_load_config(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    cfg_path = tmp_path / "census.toml"
    cfg_path.write_text(
        "top = 5\n"
        "[[roots]]\n"
        f'name = "pessoal"\npath = {str(root)!r}\n'
        "[exclude]\n"
        'dirs = ["Backups"]\n'
        'globs = ["*.bak"]\n',
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)

    assert cfg.top == 5
    assert cfg.roots == [RootSpec(name="pessoal", path=root)]
    assert "Backups" in cfg.exclude_dirs
    assert "*.bak" in cfg.exclude_globs
    assert ".git" in cfg.exclude_dirs  # defaults are kept


def test_cli_writes_report_and_json(corpus: RootSpec, tmp_path: Path) -> None:
    md = tmp_path / "out" / "censo.md"
    js = tmp_path / "out" / "censo.json"

    code = census_mod.main([str(corpus.path), "--out", str(md), "--json", str(js)])

    assert code == 0
    assert "## Por extensão" in md.read_text(encoding="utf-8")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["total"]["files"] == 6
    assert data["by_extension"][".pdf"]["files"] == 2


def test_cli_without_roots_fails() -> None:
    assert census_mod.main([]) == 2


@pytest.mark.parametrize(
    "n,expected",
    [(0, "0 B"), (512, "512 B"), (1024, "1.0 KB"), (1536, "1.5 KB"), (5 * 1024**3, "5.0 GB")],
)
def test_human_bytes(n: int, expected: str) -> None:
    assert human_bytes(n) == expected


def test_caminho_estendido_e_normal_sao_inversos() -> None:
    from segundocerebro.census import caminho_estendido, caminho_normal

    if os.name != "nt":
        pytest.skip("prefixo de caminho longo só existe no Windows")

    original = r"C:\Users\alguem\pasta\arquivo.pdf"
    estendido = caminho_estendido(original)

    assert estendido.startswith(census_mod._PREFIXO_LONGO)
    assert caminho_normal(estendido) == original
    # idempotente: aplicar duas vezes não duplica o prefixo
    assert caminho_estendido(estendido) == estendido


def test_caminho_estendido_em_unc() -> None:
    from segundocerebro.census import caminho_estendido, caminho_normal

    if os.name != "nt":
        pytest.skip("prefixo de caminho longo só existe no Windows")

    unc = "\\\\servidor\\share\\x.docx"
    estendido = caminho_estendido(unc)

    assert estendido == census_mod._PREFIXO_UNC + "servidor\\share\\x.docx"
    assert caminho_normal(estendido) == unc


def test_censo_percorre_pasta_com_caminho_acima_de_260(tmp_path: Path) -> None:
    """A varredura não pode parar no limite clássico do Windows.

    Achado no corpus real: 17 pastas do DataRoom sumiram do censo porque o
    scandir falhou com "caminho não encontrado" — e tudo abaixo delas junto.
    Nem o próprio teste consegue montar a árvore sem o prefixo estendido.
    """
    import shutil

    from segundocerebro.census import caminho_estendido

    root = tmp_path / "raiz"
    root.mkdir()

    fundo = root
    while len(str(fundo)) < 300:
        fundo = fundo / ("p" * 40)
    os.makedirs(caminho_estendido(str(fundo)), exist_ok=True)
    with open(caminho_estendido(str(fundo / "escondido.pdf")), "wb") as fh:
        fh.write(b"x" * 123)

    try:
        result = run_census([RootSpec(name="fundo", path=root)])

        assert result.errors == []
        assert result.total.files == 1
        assert result.by_extension[".pdf"].bytes == 123
    finally:
        # tmp_path não consegue limpar sozinho uma árvore acima de 260
        shutil.rmtree(caminho_estendido(str(root)), ignore_errors=True)
