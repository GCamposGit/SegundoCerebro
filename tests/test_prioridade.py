"""Queue order is metadata-only and must not open the real corpus."""

from __future__ import annotations

from pathlib import Path

from segundocerebro.census import FileEntry, RootSpec
from segundocerebro.index.indexer import indexar
from segundocerebro.index.prioridade import (
    chave_de_versao,
    e_dump,
    indexaveis,
    onda_de,
    ordenar,
    pasta_de,
    vigentes,
)
from segundocerebro.index.store import Store
from tests.falsos import DIM, EmbedderFalso, config_de_raiz

ROOT = RootSpec(name="t", path=Path("."))
AGORA = 1_777_000_000.0  # ~2026-04, keeps recency deterministic


def f(rel: str, size: int, mtime: float = AGORA) -> FileEntry:
    pasta = rel.split("/")[0] if "/" in rel else "(raiz)"
    return FileEntry(
        root=ROOT,
        path=rel,
        rel=rel,
        size=size,
        mtime=mtime,
        depth=rel.count("/"),
        top_folder=pasta,
        attrs=0,
    )


def test_ruido_nao_entra_na_fila() -> None:
    arquivos = [
        f("foto.jpg", 1000),
        f("lib.dll", 4000),
        f("idx.lance", 8000),
        f("nota.docx", 20_000),
        f("relatorio.pdf", 80_000),
    ]
    fila = indexaveis(arquivos)
    assert [a.rel for a in fila] == ["nota.docx", "relatorio.pdf"]


def test_docx_pequeno_antes_de_pdf_grande() -> None:
    arquivos = [
        f("deck/grosso.pdf", 40_000_000),
        f("notas/curta.docx", 80_000),
    ]
    ordem = [a.rel for a in ordenar(arquivos, agora=AGORA)]
    assert ordem[0] == "notas/curta.docx"
    assert onda_de(arquivos[1], vigentes_rels={arquivos[1].rel}) == 1
    assert onda_de(arquivos[0], vigentes_rels={arquivos[0].rel}) == 3


def test_pasta_pequena_fecha_antes_da_grande_na_mesma_onda() -> None:
    arquivos = [
        f("grande/a.docx", 80_000),
        f("grande/b.docx", 90_000),
        f("grande/c.docx", 100_000),
        f("grande/d.docx", 110_000),
        f("pequena/x.docx", 80_000),
        f("pequena/y.docx", 90_000),
    ]
    ordem = [a.rel for a in ordenar(arquivos, agora=AGORA)]
    pastas = [pasta_de(rel) for rel in ordem]
    # once "pequena" starts, it finishes before "grande" resumes
    primeira_pequena = pastas.index("pequena")
    ultima_pequena = max(i for i, p in enumerate(pastas) if p == "pequena")
    assert all(p == "pequena" for p in pastas[primeira_pequena : ultima_pequena + 1])


def test_vigente_e_mtime_nao_numero_de_versao() -> None:
    """g010 shape: current file has no _vN and is newer than _v6."""
    antigo = f("politica/PO-VCE-007_v6.docx", 40_000, mtime=AGORA - 10_000_000)
    vigente = f("politica/PO-VCE-007.docx", 41_000, mtime=AGORA)
    assert chave_de_versao(antigo.rel) == chave_de_versao(vigente.rel)
    assert vigentes([antigo, vigente]) == {vigente.rel}
    ordem = ordenar([antigo, vigente], agora=AGORA)
    assert onda_de(ordem[0], vigentes_rels={vigente.rel}) == 1
    assert ordem[0].rel == vigente.rel
    assert onda_de(ordem[1], vigentes_rels={vigente.rel}) == 4


def test_pdf_e_pptx_do_mesmo_stem_nao_fundem() -> None:
    pdf = f("deck/Briefing.pdf", 100_000)
    pptx = f("deck/Briefing.pptx", 120_000)
    assert chave_de_versao(pdf.rel) != chave_de_versao(pptx.rel)
    vig = vigentes([pdf, pptx])
    assert vig == {pdf.rel, pptx.rel}


def test_mesmo_nome_em_pastas_distintas_nao_e_familia() -> None:
    a = f("modelo/Assignment.docx", 10_000)
    b = f("preenchido/Assignment.docx", 12_000)
    assert chave_de_versao(a.rel) != chave_de_versao(b.rel)
    assert vigentes([a, b]) == {a.rel, b.rel}


def test_txt_nota_onda_1_dump_e_grande_nao() -> None:
    nota = f("diario.txt", 50_000)
    grande = f("relatorio.txt", 5_000_000)
    dump = f("export_dump.csv", 20_000)
    assert onda_de(nota, vigentes_rels={nota.rel}) == 1
    assert onda_de(grande, vigentes_rels={grande.rel}) == 3
    assert e_dump(dump.rel)
    assert onda_de(dump, vigentes_rels={dump.rel}) == 4
    assert not e_dump("catalogo.csv")
    assert not e_dump("dialog.md")


def test_apenas_onda_1_omite_o_resto() -> None:
    arquivos = [
        f("a.docx", 80_000),
        f("b.pdf", 40_000_000),
        f("c.txt", 50_000),
    ]
    so_1 = ordenar(arquivos, apenas_onda=1, agora=AGORA)
    assert {a.rel for a in so_1} == {"a.docx", "c.txt"}


def test_ordenar_e_estavel() -> None:
    arquivos = [
        f("b/z.docx", 50_000, mtime=AGORA - 10),
        f("a/x.docx", 40_000),
        f("a/y.docx", 45_000),
    ]
    assert [a.rel for a in ordenar(arquivos, agora=AGORA)] == [
        a.rel for a in ordenar(arquivos, agora=AGORA)
    ]


def test_indexador_ignora_png_e_declara_so_legiveis(tmp_path: Path) -> None:
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "nota.md").write_text("# Nota\nContrato CT-VCE-2024-0142.\n", encoding="utf-8")
    (raiz / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    cfg = config_de_raiz(raiz, "t")
    store = Store(tmp_path / "indice", DIM)

    from segundocerebro.index.progresso import ler

    progresso = indexar(cfg, store, EmbedderFalso())
    publicado = ler(tmp_path / "indice")

    assert progresso.indexados == 1
    assert "sem_parser" not in progresso.falhas
    assert publicado["documentos"]["totais"] == 1
    assert list(store.paths_indexados()) == ["nota.md"]
    store.fechar()


def test_sha_cruzado_nao_reembedda(tmp_path: Path) -> None:
    raiz = tmp_path / "raiz"
    (raiz / "a").mkdir(parents=True)
    (raiz / "b").mkdir()
    texto = "# Copia\nO mesmo contrato CT-VCE-2024-0142 em duas pastas.\n"
    (raiz / "a" / "um.md").write_text(texto, encoding="utf-8")
    (raiz / "b" / "dois.md").write_text(texto, encoding="utf-8")
    cfg = config_de_raiz(raiz, "t")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    progresso = indexar(cfg, store, emb, publicar=False)

    assert progresso.indexados == 2
    assert not progresso.falhas.get("duplicado")
    assert emb.chamadas == 2
    assert store.estatisticas()["documentos"] == 2
    store.fechar()
