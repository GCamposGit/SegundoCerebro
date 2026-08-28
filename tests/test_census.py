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
    DeclaredExclusions,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    Config,
    RootSpec,
    _tem_caminho,
    distribuicao_de,
    faixa_tamanho,
    human_bytes,
    is_cloud_only,
    load_config,
    main,
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


def test_distribuicao_nao_leva_nome_de_arquivo(corpus: RootSpec) -> None:
    """E6.1: a forma do acervo, não o acervo. `as_dict` vaza path em `largest`."""
    census = run_census([corpus])
    bruto = census.as_dict()
    forma = distribuicao_de(census)

    assert any(item.get("path") for item in bruto["largest"])
    assert not _tem_caminho(forma)
    assert forma["arquivos"] == 6
    assert forma["formato"][".pdf"]["arquivos"] == 2
    assert forma["formato"][".docx"]["arquivos"] == 2
    assert forma["fracao_pdf_docx"] == pytest.approx(4 / 6)
    assert forma["profundidade"]["0"]["arquivos"] == 1
    assert forma["profundidade"]["2"]["arquivos"] == 2
    assert sum(b["arquivos"] for b in forma["tamanho"].values()) == 6
    assert all(v < 16 * 1024 for v in (1000, 2000, 300, 500, 400, 10))
    assert set(forma["tamanho"]) == {"<16KiB"}


def test_faixa_tamanho_tem_teto_aberto() -> None:
    assert faixa_tamanho(0) == "<16KiB"
    assert faixa_tamanho(16 * 1024 - 1) == "<16KiB"
    assert faixa_tamanho(16 * 1024) == "16-64KiB"
    assert faixa_tamanho(64 * 1024 * 1024) == ">=64MiB"


def test_exemplo_versionado_e_o_mesmo_contrato() -> None:
    """O .toml que o gerador vai ler usa as mesmas faixas que o censo emite."""
    import tomllib

    from segundocerebro.census import FAIXA_TAMANHO_RESTO, FAIXAS_TAMANHO

    repo = Path(__file__).resolve().parents[1]
    texto = (repo / "eval" / "sintetico" / "distribuicao.example.toml").read_text(encoding="utf-8")
    dados = tomllib.loads(texto)
    assert dados["fracao_pdf_docx"] == pytest.approx(0.74)
    faixas = {nome for _teto, nome in FAIXAS_TAMANHO} | {FAIXA_TAMANHO_RESTO}
    assert set(dados["tamanho"]) == faixas
    assert abs(sum(dados["formato"].values()) - 1.0) < 0.02
    assert "path" not in texto and "caminho" not in texto.lower()


def test_cli_distribuicao_nao_grava_caminho(corpus: RootSpec, tmp_path: Path) -> None:
    saida = tmp_path / "forma.json"
    rc = main([str(corpus.path), "--distribuicao", str(saida)])
    assert rc == 0
    forma = json.loads(saida.read_text(encoding="utf-8"))
    assert not _tem_caminho(forma)
    assert forma["arquivos"] == 6


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


# --- Exclusão por papel: padrão de nome com escopo de pasta ------------------
#
# Medido em 24/08/2026 (`docs/ablacao-f4-meetings.md`): a pasta de saída do
# aplicativo de reuniões nomeia o relatório renderizado `*_relatorio.pdf`, e
# dois arquivos com essa mesma forma moram fora da árvore de reuniões — um deles
# a única cópia da sua reunião. Glob solto o descartaria em silêncio, que é o
# modo de falha que estes testes existem para travar.


@pytest.fixture
def corpus_com_papeis(tmp_path: Path) -> RootSpec:
    root = tmp_path / "acervo"
    (root / "Meetings" / "reuniao-1").mkdir(parents=True)
    (root / "Meetings-2026").mkdir()
    (root / "Negocios" / "Fibra").mkdir(parents=True)

    (root / "Meetings" / "reuniao-1" / "x_260804_154113_relatorio.pdf").write_bytes(b"x" * 900)
    (root / "Meetings" / "reuniao-1" / "x_260804_154113_transcript.txt").write_bytes(b"x" * 90)
    (root / "Meetings" / "reuniao-1" / "x_260804_154113_context.txt").write_bytes(b"x" * 30)
    (root / "Meetings-2026" / "y_260101_090000_relatorio.pdf").write_bytes(b"x" * 800)
    (root / "Negocios" / "Fibra" / "z_260708_185914_Relatorio.pdf").write_bytes(b"x" * 700)
    return RootSpec(name="acervo", path=root)


def papeis_de_reuniao() -> tuple[census_mod.RoleExclusion, ...]:
    return (
        census_mod.RoleExclusion(
            globs=("*_relatorio.pdf", "*_context.txt"),
            dirs=("Meetings",),
        ),
    )


def enumerados(corpus: RootSpec, cfg: Config) -> set[str]:
    return {f.rel for f in census_mod.iter_files(corpus, cfg)}


def test_papel_exclui_dentro_da_pasta_e_preserva_fora(corpus_com_papeis: RootSpec) -> None:
    cfg = Config(roots=[corpus_com_papeis], role_exclusions=papeis_de_reuniao())

    vistos = enumerados(corpus_com_papeis, cfg)

    assert "Meetings/reuniao-1/x_260804_154113_relatorio.pdf" not in vistos
    assert "Meetings/reuniao-1/x_260804_154113_context.txt" not in vistos
    # o conteúdo da reunião fica
    assert "Meetings/reuniao-1/x_260804_154113_transcript.txt" in vistos
    # e o arquivo de mesma forma fora da árvore de reuniões NÃO sai
    assert "Negocios/Fibra/z_260708_185914_Relatorio.pdf" in vistos


def test_papel_nao_vaza_para_pasta_que_so_comeca_igual(corpus_com_papeis: RootSpec) -> None:
    """`dirs = ["Meetings"]` não pode alcançar `Meetings-2026`.

    Prefixo de string casaria; prefixo de *caminho* não. A diferença é uma pasta
    inteira excluída por engano.
    """
    cfg = Config(roots=[corpus_com_papeis], role_exclusions=papeis_de_reuniao())

    assert "Meetings-2026/y_260101_090000_relatorio.pdf" in enumerados(corpus_com_papeis, cfg)


def test_papel_sem_dirs_vale_em_qualquer_pasta(corpus_com_papeis: RootSpec) -> None:
    cfg = Config(
        roots=[corpus_com_papeis],
        role_exclusions=(census_mod.RoleExclusion(globs=("*_relatorio.pdf",)),),
    )

    vistos = enumerados(corpus_com_papeis, cfg)

    assert not [v for v in vistos if v.lower().endswith("_relatorio.pdf")]


def test_papel_casa_pasta_aninhada_e_ignora_caixa(corpus_com_papeis: RootSpec) -> None:
    """Windows não distingue caixa em caminho, e o usuário digita como quiser."""
    cfg = Config(
        roots=[corpus_com_papeis],
        role_exclusions=(
            census_mod.RoleExclusion(globs=("*_transcript.txt",), dirs=("meetings/REUNIAO-1",)),
        ),
    )

    assert "Meetings/reuniao-1/x_260804_154113_transcript.txt" not in enumerados(
        corpus_com_papeis, cfg
    )


def test_papel_conta_como_excluido_no_censo(corpus_com_papeis: RootSpec) -> None:
    resultado = run_census([corpus_com_papeis], Config(roots=[corpus_com_papeis], role_exclusions=papeis_de_reuniao()))

    assert resultado.excluded_files == 2
    assert resultado.total.files == 3


def test_load_config_le_papel(tmp_path: Path) -> None:
    caminho = tmp_path / "census.toml"
    caminho.write_text(
        """
[[roots]]
name = "acervo"
path = 'C:\\acervo'

[[exclude.papel]]
dirs = ["Meetings", "09. Meetings"]
globs = ["*_relatorio.pdf"]
""",
        encoding="utf-8",
    )

    cfg = load_config(caminho)

    assert len(cfg.role_exclusions) == 1
    assert cfg.role_exclusions[0].dirs == ("Meetings", "09. Meetings")
    assert cfg.role_exclusions[0].globs == ("*_relatorio.pdf",)
    # e as exclusões técnicas continuam valendo
    assert "~$*" in cfg.exclude_globs


# --- Regra declarada que não casa com nada ----------------------------------
#
# A classe, e não o caso: regra de exclusão inerte **não devolve erro**. A
# passada corre inteira, sobram menos arquivos, e menos arquivos é justamente o
# que se pediu — o silêncio parece sucesso. Já custou duas vezes neste
# repositório: em 20/08/2026 quatro `metricas-f2-*` commitados por lista de nome
# no `.gitignore`, e em 26/08/2026 (`F4-P.1`) uma regra de papel escrita
# `16. Anexos volumosos` onde o caminho relativo à raiz era
# `corpus/16. Anexos volumosos` — zero arquivos casados, 3 h 22 min de máquina e
# uma medição contaminada com 312 chunks patológicos.
#
# O que estes testes travam é o método: contar por regra e comparar com zero
# antes de abrir arquivo.


@pytest.fixture
def corpus_aninhado(tmp_path: Path) -> RootSpec:
    """O corpus mora um nível abaixo da raiz — como o gerador do `E1` escreve."""
    root = tmp_path / "corpus-e1"
    (root / "corpus" / "16. Anexos volumosos").mkdir(parents=True)
    (root / "corpus" / "12. Normas").mkdir(parents=True)
    (root / "corpus" / "16. Anexos volumosos" / "Anexo de precos CT-CK-000.txt").write_bytes(b"x")
    (root / "corpus" / "16. Anexos volumosos" / "Anexo de precos CT-CK-001.txt").write_bytes(b"x")
    (root / "corpus" / "12. Normas" / "Norma 000.txt").write_bytes(b"x")
    return RootSpec(name="e1", path=root)


def _papel(dirs: tuple[str, ...], globs: tuple[str, ...] = ("*",)) -> census_mod.RoleExclusion:
    return census_mod.RoleExclusion(globs=globs, dirs=dirs)


def _passada(corpus: RootSpec, cfg: Config) -> census_mod.Census:
    censo = census_mod.Census()
    list(census_mod.iter_files(corpus, cfg, sink=censo))
    return censo


def test_prefixo_errado_de_papel_vira_aviso_e_nao_silencio(corpus_aninhado: RootSpec) -> None:
    """O defeito de 26/08, exatamente como foi escrito."""
    regra = _papel(("16. Anexos volumosos",))
    cfg = Config(
        roots=[corpus_aninhado],
        role_exclusions=(regra,),
        declared=DeclaredExclusions(roles=(regra,)),
    )

    censo = _passada(corpus_aninhado, cfg)
    avisos = census_mod.check_exclusions(cfg, censo)

    assert censo.excluded_by_rule.get(regra.label, 0) == 0
    assert len(avisos) == 1
    # e o aviso diz *qual* dos dois erros é, porque as correções são diferentes
    assert "não alcançou nenhuma pasta" in avisos[0]
    assert "relativos à raiz" in avisos[0]


def test_prefixo_certo_de_papel_conta_e_nao_avisa(corpus_aninhado: RootSpec) -> None:
    regra = _papel(("corpus/16. Anexos volumosos",))
    cfg = Config(
        roots=[corpus_aninhado],
        role_exclusions=(regra,),
        declared=DeclaredExclusions(roles=(regra,)),
    )

    censo = _passada(corpus_aninhado, cfg)

    assert censo.excluded_by_rule[regra.label] == 2
    assert census_mod.check_exclusions(cfg, censo) == []


def test_pasta_certa_e_glob_que_nao_casa_avisa_o_outro_motivo(corpus_aninhado: RootSpec) -> None:
    """Escopo achado, glob errado: mesma consequência, correção diferente."""
    regra = _papel(("corpus/16. Anexos volumosos",), ("*.pdf",))
    cfg = Config(
        roots=[corpus_aninhado],
        role_exclusions=(regra,),
        declared=DeclaredExclusions(roles=(regra,)),
    )

    avisos = census_mod.check_exclusions(cfg, _passada(corpus_aninhado, cfg))

    assert len(avisos) == 1
    assert "nenhum arquivo casou com os globs" in avisos[0]
    assert "não alcançou nenhuma pasta" not in avisos[0]


def test_exclusao_tecnica_padrao_nunca_vira_aviso(corpus_aninhado: RootSpec) -> None:
    """`.git` e `~$*` casarem zero é o esperado em acervo de escritório.

    Se o aviso saísse para o padrão técnico, sairiam vinte por passada e o que
    importa afogaria junto — que é como um aviso morre.
    """
    cfg = Config(roots=[corpus_aninhado])

    assert census_mod.check_exclusions(cfg, _passada(corpus_aninhado, cfg)) == []


def test_dirs_e_globs_declarados_tambem_sao_conferidos(corpus_aninhado: RootSpec) -> None:
    cfg = Config(
        roots=[corpus_aninhado],
        exclude_dirs=census_mod.DEFAULT_EXCLUDE_DIRS + ("corpus/12. Normas",),
        exclude_globs=census_mod.DEFAULT_EXCLUDE_GLOBS + ("*.bak", "*.txt"),
        declared=DeclaredExclusions(dirs=("corpus/12. Normas",), globs=("*.bak", "*.txt")),
    )

    censo = _passada(corpus_aninhado, cfg)
    avisos = census_mod.check_exclusions(cfg, censo)

    # `dirs` casa pelo NOME da pasta: caminho com "/" nunca casa, e é erro comum
    assert any("dirs" in a and "nenhuma pasta" in a for a in avisos)
    assert any("*.bak" in a for a in avisos)
    # o glob que funcionou não gera aviso, e a contagem por regra diz quanto tirou
    assert not any("*.txt" in a for a in avisos)
    assert censo.excluded_by_rule["globs: *.txt"] == 3


def test_contagem_por_regra_separa_duas_regras(corpus_aninhado: RootSpec) -> None:
    """Total sozinho não distingue "as duas funcionaram" de "uma fez tudo"."""
    volumosos = _papel(("corpus/16. Anexos volumosos",))
    normas = _papel(("corpus/12. Normas",))
    cfg = Config(
        roots=[corpus_aninhado],
        role_exclusions=(volumosos, normas),
        declared=DeclaredExclusions(roles=(volumosos, normas)),
    )

    censo = _passada(corpus_aninhado, cfg)

    assert censo.excluded_files == 3
    assert censo.excluded_by_rule[volumosos.label] == 2
    assert censo.excluded_by_rule[normas.label] == 1


def test_relatorio_do_censo_mostra_contagem_e_aviso(corpus_aninhado: RootSpec) -> None:
    regra = _papel(("16. Anexos volumosos",))
    cfg = Config(
        roots=[corpus_aninhado],
        role_exclusions=(regra,),
        declared=DeclaredExclusions(roles=(regra,)),
    )

    censo = run_census([corpus_aninhado], cfg)
    relatorio = render_markdown(censo, cfg, [corpus_aninhado])

    assert "## Exclusões declaradas" in relatorio
    assert "não alcançou nenhuma pasta" in relatorio


def test_load_config_marca_o_que_o_arquivo_declarou(tmp_path: Path) -> None:
    caminho = tmp_path / "census.toml"
    caminho.write_text(
        """
[[roots]]
name = "acervo"
path = 'C:\\acervo'

[exclude]
dirs = ["Backups"]
globs = ["*.bak"]

[[exclude.papel]]
dirs = ["Meetings"]
globs = ["*_relatorio.pdf"]
""",
        encoding="utf-8",
    )

    cfg = load_config(caminho)

    assert cfg.declared.dirs == ("Backups",)
    assert cfg.declared.globs == ("*.bak",)
    assert len(cfg.declared.roles) == 1
    # e o padrão técnico continua fora da declaração, logo fora da conferência
    assert ".git" not in cfg.declared.dirs
    assert "~$*" not in cfg.declared.globs
