"""Natureza do arquivo: assinatura contra extensão, e as flags persistidas.

O caso que motivou o módulo é real e está no corpus: um arquivo `.pdf` cujo
conteúdo é email MIME. Ele falhava como `FileDataError: Failed to open stream`,
que soa como PDF corrompido e manda a investigação para o lado errado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.ingest.document import Block, BlockKind, ParsedDoc, ParseStatus
from segundocerebro.ingest.natureza import Natureza, detectar, familia_por_assinatura
from segundocerebro.ingest.reader import parse_file

PDF_MINIMO = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)
EMAIL_MIME = (
    b"Received: from mx.example.com\r\nReturn-Path: <a@example.com>\r\n"
    b"From: Alguem <a@example.com>\r\nSubject: Proposta\r\n\r\nCorpo da mensagem.\r\n"
)


# --- assinatura -------------------------------------------------------------


@pytest.mark.parametrize(
    ("dados", "esperado"),
    [
        (PDF_MINIMO, "pdf"),
        (b"PK\x03\x04\x14\x00", "ooxml"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),
        (EMAIL_MIME, "email"),
        (b"{\\rtf1\\ansi", "rtf"),
        (b"texto solto sem assinatura", ""),
    ],
)
def test_familia_por_assinatura(dados: bytes, esperado: str) -> None:
    assert familia_por_assinatura(dados) == esperado


def test_cabecalho_de_email_depois_de_algumas_linhas() -> None:
    """`.eml` real não começa necessariamente por `Received:`."""
    dados = b"X-Alguma-Coisa: 1\r\nX-Outra: 2\r\nMIME-Version: 1.0\r\n\r\ncorpo"
    assert familia_por_assinatura(dados) == "email"


# --- a extensão mente -------------------------------------------------------


def test_email_com_extensao_pdf_e_acusado() -> None:
    """O caso g033, reduzido ao mínimo."""
    n = detectar("pasta/PROPOSTA.pdf", EMAIL_MIME)

    assert n.familia_real == "email"
    assert n.extensao_mente


def test_extensao_coerente_nao_acusa() -> None:
    assert not detectar("a.pdf", PDF_MINIMO).extensao_mente
    assert not detectar("a.docx", b"PK\x03\x04").extensao_mente
    assert not detectar("a.msg", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1").extensao_mente


def test_arquivo_de_texto_nunca_e_acusado_de_mentir() -> None:
    """Um `.csv` com coluna `From: ` é um csv, não um email.

    A assinatura só é autoridade para família binária. Sem essa restrição, todo
    arquivo de texto que comece com uma palavra reservada viraria falso positivo.
    """
    n = detectar("dados.csv", b"From: ,Para: ,Assunto:\r\na,b,c\r\n")

    assert n.familia_real == "email"  # a assinatura casou...
    assert not n.extensao_mente  # ...e é ignorada, porque a extensão é de texto


def test_extensao_desconhecida_nao_acusa() -> None:
    """Sem expectativa registrada, não há contradição a afirmar."""
    assert not detectar("arquivo.qualquercoisa", PDF_MINIMO).extensao_mente


# --- flags vindas do parser -------------------------------------------------


def test_flags_saem_do_meta_do_parser() -> None:
    doc = ParsedDoc(
        name="a.pdf",
        blocks=(Block(heading_path=(), text="x", kind=BlockKind.TABLE),),
        meta={"paginas": "10", "paginas_com_imagem": "10", "sumario_nativo": "1", "suspeita": "digitalizado"},
    )
    n = detectar("a.pdf", PDF_MINIMO, doc)

    assert n.digitalizado
    assert n.tem_sumario_nativo
    assert n.tem_tabela
    assert n.figuras_por_pagina == 1.0
    assert n.paginas == 10


def test_documento_sem_bloco_ainda_rende_flags() -> None:
    """PDF digitalizado não tem bloco, e é exatamente dele que se quer a flag.

    O parser preenche `meta` antes de desistir; se `detectar` exigisse bloco, a
    fila de OCR nasceria vazia.
    """
    doc = ParsedDoc(name="a.pdf", blocks=(), meta={"paginas": "61", "suspeita": "digitalizado"})
    n = detectar("a.pdf", PDF_MINIMO, doc)

    assert n.digitalizado
    assert n.paginas == 61
    assert not n.tem_tabela


def test_sem_doc_as_flags_ficam_neutras() -> None:
    n = detectar("a.pdf", PDF_MINIMO)

    assert not n.digitalizado
    assert not n.tem_sumario_nativo
    assert n.paginas == 0


def test_como_colunas_converte_booleano_para_inteiro() -> None:
    colunas = Natureza(familia_real="pdf", extensao_mente=True, paginas=3).como_colunas()

    assert colunas["extensao_mente"] == 1
    assert colunas["digitalizado"] == 0
    assert colunas["familia_real"] == "pdf"
    assert isinstance(colunas["extensao_mente"], int)


# --- integração pelo portão de leitura --------------------------------------


def test_parse_file_reinterpreta_extensao_mentirosa_pelo_conteudo(tmp_path: Path) -> None:
    """A F4 fecha o ciclo que a flag abriu: acusar virou aproveitar.

    Até 20/08/2026 este arquivo terminava em `sem_parser` com o motivo escrito no
    `detalhe` — o melhor possível enquanto não havia parser de email. Com o parser
    da F4, recusar um documento cujo conteúdo sabemos interpretar seria desperdício
    de um documento que o dourado corporativo cobra (`g033`).

    A flag continua ligada: o arquivo **de fato** mente sobre a extensão, e é isso
    que o registro tem que dizer.
    """
    alvo = tmp_path / "PROPOSTA_falso.pdf"
    alvo.write_bytes(EMAIL_MIME)

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.OK
    assert resultado.natureza is not None and resultado.natureza.extensao_mente
    assert resultado.natureza.familia_real == "email"
    assert resultado.doc is not None
    assert "Corpo da mensagem." in "\n".join(b.text for b in resultado.doc.blocks)
    assert resultado.sha256, "os bytes foram lidos, então o hash tem que estar lá"


def test_parse_file_recusa_reinterpretar_familia_ambigua(tmp_path: Path) -> None:
    """`ole` pode ser doc, xls ou msg — adivinhar erraria calado.

    O portão continua dizendo o que o arquivo é, sem fingir que sabe interpretá-lo.
    """
    alvo = tmp_path / "planilha_falsa.docx"
    alvo.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.UNSUPPORTED
    assert "extensão mente" in resultado.detail
    assert "ole" in resultado.detail
    assert resultado.natureza is not None and resultado.natureza.extensao_mente


def test_parse_file_leva_natureza_no_caminho_bem_sucedido(tmp_path: Path) -> None:
    alvo = tmp_path / "nota.md"
    alvo.write_text("# Título\n\nCorpo da nota com texto suficiente.\n", encoding="utf-8")

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.OK
    assert resultado.natureza is not None
    assert not resultado.natureza.extensao_mente


# --- persistência: o motivo de tudo isso ------------------------------------


def _store(tmp_path: Path):  # noqa: ANN202
    from segundocerebro.index.store import Store

    return Store(tmp_path / "indice", dim=8)


def test_fila_de_ocr_vira_consulta(tmp_path: Path) -> None:
    """O ganho concreto: separar PDF digitalizado de PDF vazio de verdade.

    Antes os dois recebiam `status='vazio'` e distinguir exigia script avulso
    abrindo arquivo por arquivo.
    """
    store = _store(tmp_path)
    try:
        for nome, digitalizado in (("escaneado.pdf", True), ("vazio.pdf", False)):
            store.registrar_documento(
                path=nome,
                raiz="r",
                tamanho=1,
                mtime=0.0,
                status="vazio",
                natureza=Natureza(familia_real="pdf", digitalizado=digitalizado, paginas=9),
            )
        store.commit()

        fila = [
            r["path"]
            for r in store.con.execute(
                "SELECT path FROM documentos WHERE digitalizado = 1 ORDER BY path"
            )
        ]
        assert fila == ["escaneado.pdf"]
    finally:
        store.fechar()


def test_registrar_sem_natureza_grava_neutro(tmp_path: Path) -> None:
    """Formato sem sinais não pode gravar valor que finja medição."""
    store = _store(tmp_path)
    try:
        store.registrar_documento(path="a.txt", raiz="r", tamanho=1, mtime=0.0, status="ok")
        store.commit()

        linha = store.con.execute("SELECT * FROM documentos WHERE path='a.txt'").fetchone()
        assert linha["familia_real"] == ""
        assert linha["digitalizado"] == 0
        assert linha["figuras_por_pagina"] == 0
    finally:
        store.fechar()


def test_banco_antigo_ganha_as_colunas_novas(tmp_path: Path) -> None:
    """Sem isso, um índice de versão anterior falha com "no such column".

    E falharia no meio de uma passada de horas, que é o pior momento possível.
    """
    import sqlite3

    diretorio = tmp_path / "indice"
    diretorio.mkdir()
    antigo = sqlite3.connect(diretorio / "registro.db")
    antigo.executescript(
        """
        CREATE TABLE documentos (
            path TEXT PRIMARY KEY, raiz TEXT NOT NULL, tamanho INTEGER NOT NULL,
            mtime REAL NOT NULL, sha256 TEXT DEFAULT '', status TEXT NOT NULL,
            detalhe TEXT DEFAULT '', n_chunks INTEGER DEFAULT 0,
            model_id TEXT DEFAULT '', chunker TEXT DEFAULT '', indexado_em TEXT NOT NULL
        );
        INSERT INTO documentos (path, raiz, tamanho, mtime, status, indexado_em)
        VALUES ('velho.pdf', 'r', 1, 0.0, 'ok', '2026-01-01T00:00:00+00:00');
        """
    )
    antigo.commit()
    antigo.close()

    store = _store(tmp_path)
    try:
        store.registrar_documento(
            path="novo.pdf",
            raiz="r",
            tamanho=1,
            mtime=0.0,
            status="vazio",
            natureza=Natureza(familia_real="pdf", digitalizado=True),
        )
        store.commit()

        linhas = {r["path"]: r for r in store.con.execute("SELECT * FROM documentos")}
        assert linhas["novo.pdf"]["digitalizado"] == 1
        assert linhas["velho.pdf"]["digitalizado"] == 0, (
            "documento antigo tem 0 porque ninguém olhou, não porque foi verificado"
        )
    finally:
        store.fechar()


# --- adiar planilha cara -----------------------------------------------------


def planilha_com_abas(n_abas: int, linhas: int) -> bytes:
    import io

    import openpyxl

    livro = openpyxl.Workbook()
    livro.remove(livro.active)
    for a in range(n_abas):
        aba = livro.create_sheet(f"aba{a}")
        aba.append(["col1", "col2", "col3"])
        for i in range(linhas):
            aba.append([f"v{i}", i, f"texto da linha {i}"])
    buf = io.BytesIO()
    livro.save(buf)
    return buf.getvalue()


def test_mb_de_abas_le_o_zip_sem_descomprimir() -> None:
    from segundocerebro.ingest.natureza import mb_de_abas

    pequena = mb_de_abas(planilha_com_abas(1, 5))
    grande = mb_de_abas(planilha_com_abas(8, 400))

    assert pequena is not None and grande is not None
    assert grande > pequena * 10, "o preditor tem que separar planilha grande de pequena"


def test_mb_de_abas_devolve_none_para_nao_zip() -> None:
    from segundocerebro.ingest.natureza import mb_de_abas

    assert mb_de_abas(PDF_MINIMO) is None


def test_planilha_acima_do_limite_e_adiada(tmp_path: Path) -> None:
    """Adiada, não ignorada: fica no registro com o motivo e o custo medido."""
    from segundocerebro.ingest.natureza import mb_de_abas

    dados = planilha_com_abas(8, 400)
    alvo = tmp_path / "gigante.xlsx"
    alvo.write_bytes(dados)
    limite = (mb_de_abas(dados) or 0) / 2

    resultado = parse_file(str(alvo), limite_planilha_mb=limite)

    assert resultado.status is ParseStatus.DEFERRED
    assert "MB de XML de abas" in resultado.detail
    assert resultado.sha256, "o hash tem que estar lá para reconhecer o arquivo depois"


def test_planilha_abaixo_do_limite_passa_normal(tmp_path: Path) -> None:
    alvo = tmp_path / "pequena.xlsx"
    alvo.write_bytes(planilha_com_abas(1, 5))

    assert parse_file(str(alvo), limite_planilha_mb=50).status is ParseStatus.OK


def test_sem_limite_nada_e_adiado(tmp_path: Path) -> None:
    alvo = tmp_path / "gigante.xlsx"
    alvo.write_bytes(planilha_com_abas(8, 400))

    assert parse_file(str(alvo)).status is ParseStatus.OK


def test_limite_nao_afeta_outros_formatos(tmp_path: Path) -> None:
    """O limite é sobre planilha; PDF e DOCX não têm XML de aba para medir."""
    alvo = tmp_path / "nota.md"
    alvo.write_text("# Título\n\nCorpo com texto suficiente para virar bloco.\n", encoding="utf-8")

    assert parse_file(str(alvo), limite_planilha_mb=0.001).status is ParseStatus.OK


def test_adiado_e_repescado_na_proxima_passada() -> None:
    """Sem isso, adiar viraria esquecer — que é o defeito de mover o arquivo para fora."""
    from segundocerebro.index.indexer import STATUS_PARA_REPESCAR

    assert ParseStatus.DEFERRED.value in STATUS_PARA_REPESCAR


def test_txt_acima_do_limite_e_adiado_sem_abrir(tmp_path: Path) -> None:
    """269 MB de dump não podem entrar na RAM só para depois serem recusados."""
    alvo = tmp_path / "dump.txt"
    alvo.write_bytes(b"x" * 3_000_000)

    resultado = parse_file(str(alvo), limite_texto_mb=2.0)

    assert resultado.status is ParseStatus.DEFERRED
    assert resultado.sha256 == ""
    assert "MB" in resultado.detail


def test_csv_abaixo_do_limite_passa(tmp_path: Path) -> None:
    alvo = tmp_path / "tabela.csv"
    alvo.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    assert parse_file(str(alvo), limite_texto_mb=2.0).status is ParseStatus.OK


def test_csv_nao_e_adiado_pelo_limite_de_texto(tmp_path: Path) -> None:
    """C7.d: the text-size shortcut must not hide a dump the digest now covers."""
    alvo = tmp_path / "dump.csv"
    alvo.write_text("a,b\n" + "1,2\n" * 80, encoding="utf-8")

    assert parse_file(str(alvo), limite_texto_mb=0.0001).status is ParseStatus.OK


def test_limite_de_texto_nao_afeta_markdown(tmp_path: Path) -> None:
    alvo = tmp_path / "nota.md"
    alvo.write_text("# Título\n\nCorpo com texto suficiente para virar bloco.\n", encoding="utf-8")

    assert parse_file(str(alvo), limite_texto_mb=0.0001).status is ParseStatus.OK


def test_mapa_de_limites_adia_pdf_pelo_tamanho_em_disco(tmp_path: Path) -> None:
    """O painel configura por tipo; o reader recusa antes de abrir."""
    alvo = tmp_path / "relatorio.pdf"
    alvo.write_bytes(b"%PDF-1.4\n" + b"x" * 3_000_000)

    resultado = parse_file(str(alvo), limites_mb={".pdf": 2.0})

    assert resultado.status is ParseStatus.DEFERRED
    assert resultado.sha256 == ""
    assert "MB" in resultado.detail


def test_mapa_de_limites_nao_adia_abaixo_do_teto(tmp_path: Path) -> None:
    alvo = tmp_path / "nota.txt"
    alvo.write_text("nota curta o bastante para um trecho.\n", encoding="utf-8")

    assert parse_file(str(alvo), limites_mb={".txt": 2.0}).status is ParseStatus.OK
