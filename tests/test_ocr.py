"""R1.2: scanned PDFs become chunks after the text waves, not instead of them."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.ocr import VERSAO, backend_disponivel, doc_de_ocr
from segundocerebro.ingest.reader import parse_file
from segundocerebro.index.indexer import indexar
from segundocerebro.index.isolamento import timeout_para
from segundocerebro.index.orcamento import medir
from segundocerebro.index.store import Store
from segundocerebro.ingest.document import MOTIVO_RECURSO
from tests.falsos import DIM, EmbedderFalso, bytes_pdf, bytes_pdf_misto, config_de_raiz

SINAIS_DE_RECURSO = (
    MOTIVO_RECURSO,  # o marcador que o produto escreve desde o `Q15` (30/08/2026)
    "subprocesso morreu",
    "timeout",
    "memory",
    "memória",
    "openblas",
    "allocation",
    "cannot allocate",
)
"""When the isolated parse child dies of RAM, the product quarantines — that is
success, not a red suite. Measured 27/08/2026 on the notebook: 2.7 GB free →
OpenBLAS abort → status `erro`; RAM freed → the same tests `ok`. The suite
verdict was the machine window. Same class as F4-R (regime not recorded)."""

PISO_RAM_OCR_REMOVIDO_EM = "30/08/2026"
"""O piso de 4 GB saiu quando o `Q15` fechou, e o motivo é o pacote inteiro.

Ele existia porque o produto tinha **duas** reações à pressão de memória e só
uma era honesta. A honesta — filho de parse morre dizendo que morreu — sempre
foi aceita aqui. A silenciosa não: o `import pymupdf` falhava dentro do filho
com `ModuleNotFoundError: No module named 'mupdf'`, o documento terminava
`vazio` sem linha de quarentena, e a suíte reprovava por uma janela de máquina
em vez de por regressão. Medido em 29/08/2026 (16 GB), cinco passadas em
sequência: **2 reprovaram com 3,5–3,6 GB livres e 3 passaram com ~3,9 GB**, sem
uma linha mudar.

Com o `Q15`, falha de ambiente vira `erro` com motivo de recurso — que é uma das
duas saídas que `ocr_produziu_texto_ou_declarou_recurso` já aceitava. O ramo de
pular ficou morto, e teste que pula por causa da máquina é teste que não tem
veredito: agora ele **sempre** tem um, e `vazio` volta a ser reprovação em
qualquer janela. `regime_da_maquina()` continua na mensagem de falha, porque a
lição do `F4-R` não mudou — o número sem a máquina ao lado não diz nada."""


def regime_da_maquina() -> str:
    """A janela em que esta passada rodou, para a mensagem de falha carregá-la."""
    r = medir()
    return (
        f"RAM livre {r.ram_livre_mb} MB de {r.ram_total_mb} MB · "
        f"{r.nucleos} núcleos · {r.gpus} GPU(s)"
    )


def ocr_produziu_texto_ou_declarou_recurso(store: Store, rel: str, progresso) -> bool:
    """True if OCR committed chunks. False if the child died of resource/timeout.

    Any other status fails the test: silent EMPTY or missing row would be the
    lie this helper exists to refuse.
    """
    estado = store.estado_documento(rel)
    assert estado is not None, f"{rel} saiu do registro"
    if estado.status == "ok" and estado.n_chunks >= 1:
        return True
    # A propriedade que o `Q15` instalou, e a unica que nao depende da RAM desta
    # maquina: se o OCR nao produziu texto, **existe linha de quarentena com
    # motivo de recurso**. Antes nao existia nenhuma, e o documento sumia
    # parecendo um PDF sem texto. O status final ainda pode ficar `vazio` depois
    # de uma fase de OCR quarentenada — e isso e o resto declarado do `Q15`, no
    # ROADMAP —, mas o silencio acabou, e e o silencio que fazia o acervo sumir.
    item = store.quarentena_de(rel)
    assert item is not None, (
        f"{rel} ficou {estado.status!r} SEM linha de quarentena — e a regressao do "
        f"`Q15`: falha de ambiente indistinguivel de documento sem conteudo. "
        f"Regime: {regime_da_maquina()}"
    )
    motivo = (item.motivo or "").lower()
    assert any(s in motivo for s in SINAIS_DE_RECURSO), (
        f"{rel} em erro por motivo que não é recurso: {item.motivo!r}"
    )
    assert progresso.quarentena >= 1
    # O produto se comportou certo, e mesmo assim esta passada **não tem
    # veredito sobre OCR**: nenhuma página foi reconhecida. Devolver `False` e
    # deixar o chamador sair calado trocava um não-veredito VISÍVEL (o skip, que
    # aparece no sumário) por um invisível (verde). Achado por revisão em
    # 30/08/2026, e é a mesma armadilha que o piso de RAM tinha — só que pior,
    # porque some do relatório. O motivo agora vem do produto, não de um número
    # escrito à mão.
    pytest.skip(
        f"sem veredito de OCR nesta passada: o produto declarou recurso em {rel} "
        f"({item.motivo!r}). Regime: {regime_da_maquina()}"
    )


TEXTO_VCE = "Contrato NN-VCE-001 da Varzea Clara Energia."


def test_sem_motor_ocr_e_noop() -> None:
    """The extra is optional. Missing backend is None, not an exception."""
    assert backend_disponivel() in {None, "rapidocr", "tesseract", "teste"}
    if backend_disponivel() not in {None, "teste"}:
        return
    assert doc_de_ocr(bytes_pdf(texto=None, com_imagem=True), "x.pdf") is None


def test_parse_sem_ocr_continua_vazio_no_digitalizado(tmp_path: Path) -> None:
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    resultado = parse_file(str(alvo), ocr=False)
    assert resultado.status is ParseStatus.EMPTY
    assert resultado.natureza is not None
    assert resultado.natureza.digitalizado


def test_parse_com_ocr_falso_vira_trechos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None
    assert resultado.doc.meta.get("fonte") == "ocr"
    assert resultado.doc.meta.get("parser") == VERSAO
    assert any(TEXTO_VCE in b.text for b in resultado.doc.blocks)
    assert any(b.locator.startswith("p. ") for b in resultado.doc.blocks)


def test_pdf_com_texto_nao_entra_no_ocr(tmp_path: Path, monkeypatch) -> None:
    chamou = []
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    monkeypatch.setattr(
        "segundocerebro.ingest.reader._ocr_pdf",
        lambda *a, **k: chamou.append(1) or None,
    )
    alvo = tmp_path / "contrato.pdf"
    alvo.write_bytes(bytes_pdf(texto="Contrato 4600009999 com a Nimbus Tecnologia."))
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert chamou == []
    assert "4600009999" in resultado.doc.blocks[0].text


def test_timeout_ocr_soma_no_teto() -> None:
    assert timeout_para(0, "x.pdf") == 60.0
    assert timeout_para(0, "x.pdf", ocr=True) == 180.0


def test_indexar_ocr_depois_do_texto(tmp_path: Path, monkeypatch) -> None:
    """Acceptance: text files are searchable before the scan is OCRed.

    The OCR phase runs after the parse loop. A .md next to a scan is committed
    first; the scan is still `vazio` until the second phase.
    """
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "politica.md").write_text("# Politica VCE\nUso aceitavel de IA.\n", encoding="utf-8")
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))

    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=True,
    )
    assert not progresso.interrompido
    assert store.estado_documento("politica.md").status == "ok"
    if not ocr_produziu_texto_ou_declarou_recurso(store, "escaneado.pdf", progresso):
        store.fechar()
        return
    escaneado = store.estado_documento("escaneado.pdf")
    assert escaneado is not None
    assert escaneado.parser == VERSAO
    assert progresso.ocr >= 1
    texto = " ".join(c.texto for c in store.chunks_de("escaneado.pdf"))
    assert TEXTO_VCE in texto
    store.fechar()


def test_indexar_sem_ocr_nao_mexe_no_digitalizado(tmp_path: Path) -> None:
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))
    store = Store(tmp_path / "indice", DIM)
    indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=False,
    )
    estado = store.estado_documento("escaneado.pdf")
    assert estado is not None
    assert estado.status == "vazio"
    assert estado.n_chunks == 0
    assert store.documentos_para_ocr(VERSAO) == [("escaneado.pdf", "teste")]
    store.fechar()


def test_pdf_misto_nativa_nao_passa_pelo_ocr(tmp_path: Path, monkeypatch) -> None:
    """O.2a: photo page becomes a chunk; native page never hits the engine."""
    chamadas: list[int] = []

    def fake(imagem) -> str:
        chamadas.append(1)
        return "SCAN-VCE-001"

    monkeypatch.setattr("segundocerebro.ingest.ocr.motor_imagem", fake)
    alvo = tmp_path / "oficio.pdf"
    alvo.write_bytes(bytes_pdf_misto())
    resultado = parse_file(str(alvo), ocr=True)
    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None
    assert len(chamadas) == 1
    texto = " ".join(b.text for b in resultado.doc.blocks)
    assert "4600009999" in texto
    assert "SCAN-VCE-001" in texto
    locators = {b.locator for b in resultado.doc.blocks}
    assert "p. 1" in locators
    assert "p. 2" in locators


def test_indexar_misto_entra_na_fila_ocr(tmp_path: Path) -> None:
    """Without --ocr the native page is searchable and the photo waits in queue."""
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "oficio.pdf").write_bytes(bytes_pdf_misto())
    store = Store(tmp_path / "indice", DIM)
    indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=False,
    )
    estado = store.estado_documento("oficio.pdf")
    assert estado is not None
    assert estado.status == "ok"
    assert estado.n_chunks >= 1
    texto = " ".join(c.texto for c in store.chunks_de("oficio.pdf"))
    assert "4600009999" in texto
    assert store.documentos_para_ocr(VERSAO) == [("oficio.pdf", "teste")]
    store.fechar()


def test_ocr_rasteriza_uma_pagina_por_vez(monkeypatch) -> None:
    """O.2c: N scan pages, at most one pixmap alive."""
    import pymupdf

    from segundocerebro.ingest.ocr import ocr_pdf

    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", TEXTO_VCE)
    doc = pymupdf.open()
    for _ in range(8):
        pagina = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
        pix.set_rect(pix.irect, (180, 180, 180))
        pagina.insert_image(pymupdf.Rect(0, 0, 500, 700), pixmap=pix)
    dados = doc.tobytes()
    doc.close()

    vivo: list[object] = []
    pico = [0]
    from segundocerebro.ingest import ocr as mod

    original = mod._iter_rasters

    def envolto(dados_pdf, *, teto_mb=None):
        for item in original(dados_pdf, teto_mb=teto_mb):
            vivo.append(item)
            pico[0] = max(pico[0], len(vivo))
            yield item
            vivo.pop()

    monkeypatch.setattr(mod, "_iter_rasters", envolto)
    paginas = ocr_pdf(dados, teto_mb=256)
    assert paginas is not None
    assert len(paginas) == 8
    assert pico[0] == 1


def test_dpi_ocr_respeita_teto_de_ram() -> None:
    """A page bigger than the parse budget drops to 72 dpi, never below."""
    import pymupdf

    from segundocerebro.ingest.ocr import DPI_OCR, _dpi_cabivel

    doc = pymupdf.open()
    pagina = doc.new_page(width=595, height=842)
    try:
        assert _dpi_cabivel(pagina, teto_mb=1) == 72.0
        assert _dpi_cabivel(pagina, teto_mb=256) == DPI_OCR
    finally:
        doc.close()


def test_indexar_misto_com_ocr_junta_as_paginas(tmp_path: Path, monkeypatch) -> None:
    # parse_isolado runs in a child: a monkeypatch of motor_imagem does not
    # survive spawn. The env var does — same contract as the O.0 suite.
    monkeypatch.setenv("SEGUNDOCEREBRO_OCR_FAKE", "SCAN-VCE-001")
    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "oficio.pdf").write_bytes(bytes_pdf_misto())
    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(
        config_de_raiz(raiz),
        store,
        EmbedderFalso(),
        publicar=False,
        reconciliar_ao_fim=False,
        ocr=True,
    )
    # No PDF misto a régua é OUTRA, e a primeira versão deste teste pedia a
    # errada — pedia linha de quarentena, que o produto **de propósito** não
    # emite aqui: o parse nativo valeu, o documento ficou `ok` com texto, e
    # engolir a falha é o conserto que impede `remover_documento` de apagar
    # chunks e vetores já gravados. As duas exigências se contradiziam, e a
    # suíte reprovava 1 em 5 passadas por isso (achado por revisão, 30/08/2026).
    #
    # O que o produto promete aqui, e o que se cobra: o documento **continua na
    # fila de OCR**. Não depende da RAM da máquina, e é a diferença entre "o OCR
    # não rodou desta vez" e "o documento sumiu do acervo".
    if progresso.ocr < 1:
        estado = store.estado_documento("oficio.pdf")
        assert estado is not None, "oficio.pdf saiu do registro"
        texto_nativo = " ".join(c.texto for c in store.chunks_de("oficio.pdf"))
        assert "4600009999" in texto_nativo, (
            "o texto nativo do PDF misto se perdeu quando o OCR falhou — é o "
            f"defeito que o conserto do `Q15` existe para impedir. Regime: {regime_da_maquina()}"
        )
        na_fila = [rel for rel, _ in store.documentos_para_ocr(VERSAO)]
        assert "oficio.pdf" in na_fila, (
            "o OCR não produziu nada e o documento saiu da fila — a próxima passada "
            f"nunca mais tentaria. Estado: {estado.status!r}. Regime: {regime_da_maquina()}"
        )
        store.fechar()
        return
    texto = " ".join(c.texto for c in store.chunks_de("oficio.pdf"))
    assert "4600009999" in texto
    assert "SCAN-VCE-001" in texto
    assert store.documentos_para_ocr(VERSAO) == []
    store.fechar()


def test_config_ocr_ligado_por_padrao(tmp_path: Path) -> None:
    from segundocerebro.config import carregar

    caminho = tmp_path / "config.toml"
    caminho.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is True
    caminho.write_text('[indexacao]\nocr = false\n[[base]]\nid = "a"\n', encoding="utf-8")
    assert carregar(caminho, ambiente={}).indexacao.ocr is False


def test_teste_de_ocr_que_indexa_aceita_falha_de_recurso() -> None:
    """The next `indexar(..., ocr=True)` test that asserts ok-only fails here.

    F4-O.2 added a second test with the same assumption the first already had.
    The checklist is this helper, not a list of two names.

    Desde 30/08/2026 há **duas** saídas aceitas, porque o produto passou a ter
    duas garantias diferentes. Scan puro: `ocr_produziu_texto_ou_declarou_recurso`,
    que pula com o motivo do produto. PDF misto: o OCR pode falhar sem quarentena
    — engolir a falha é o conserto que preserva o texto nativo já indexado —, e a
    régua ali é `documentos_para_ocr`, que prova que a próxima passada tenta de
    novo. Exigir quarentena nos dois era uma contradição, e ela reprovava a suíte
    1 em 5 passadas.
    """
    fonte = Path(__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    faltando: list[str] = []
    for no in arvore.body:
        if not isinstance(no, ast.FunctionDef) or not no.name.startswith("test_"):
            continue
        trecho = ast.get_source_segment(fonte, no) or ""
        if "indexar(" not in trecho or "ocr=True" not in trecho:
            continue
        aceita_recurso = "ocr_produziu_texto_ou_declarou_recurso" in trecho
        aceita_fila = "documentos_para_ocr" in trecho
        if not (aceita_recurso or aceita_fila):
            faltando.append(no.name)
    assert not faltando, (
        "teste de OCR que indexa e afirma o caminho feliz sem aceitar falha de "
        "recurso. Use `ocr_produziu_texto_ou_declarou_recurso` (scan puro) ou "
        "confira `documentos_para_ocr` (PDF misto), senão a suíte mede a janela "
        "de memória outra vez: " + ", ".join(faltando)
    )
