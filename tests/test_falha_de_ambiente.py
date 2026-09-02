"""Filho de parse que morre por ambiente não pode parecer documento sem conteúdo.

Pacotes `Q15` (P0) e `Q14`, 30/08/2026.

O `Q15` tinha a forma que este projeto mais teme — *a indexação diz pronto tendo
engolido metade do acervo*. Sob pressão de memória o `import pymupdf` levanta
`ModuleNotFoundError: No module named 'mupdf'` **dentro** do caminho de OCR, e um
`except Exception` largo devolvia `None`. Só que `None` já significava outra
coisa: *"esta instalação não tem OCR"*. Duas condições opostas, um valor só — e a
silenciosa vencia. O documento terminava `vazio`, sem linha de quarentena (porque
para o indexador nada deu errado), `digitalizado` nunca era marcado, a fila de
OCR saía vazia e `progresso.ocr` ficava em 0. No PDF misto o disfarce era melhor:
`ok`, com os trechos das páginas nativas.

Medido em 29/08/2026, cinco passadas seguidas sem uma linha mudar: **2 reprovaram
com 3,5–3,6 GB livres e 3 passaram com ~3,9 GB**.

Este arquivo é a **classe generalizada**, e não o caso. Ele é uma matriz
`modo de falha × ponto de entrada`: cada célula exige que o resultado seja
distinguível de "documento sem conteúdo". Ponto de entrada novo é uma linha em
`ENTRADAS`; modo de falha novo é uma linha em `MODOS`. O que a matriz proíbe é
que qualquer combinação devolva o valor benigno.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

from segundocerebro.index.isolamento import parse_isolado
from segundocerebro.ingest import ocr as ocr_mod
from segundocerebro.ingest.document import (
    MOTIVO_RECURSO,
    FalhaDeAmbiente,
    ParseStatus,
    ausencia_declarada,
)
from tests.falsos import bytes_pdf, bytes_pdf_misto

# --------------------------------------------------------------------------- #
# Os dois eixos da matriz


def _quebrar_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """`import pymupdf` falha por `mupdf` — o caso real, medido em 29/08/2026.

    Repare que o módulo ausente **não** é o que se pediu: é a biblioteca nativa
    por baixo. Essa é exatamente a diferença que `ausencia_declarada` mede.
    """
    real = builtins.__import__

    def falso(nome: str, *a: object, **k: object) -> object:
        if nome in ("pymupdf", "numpy") and sys._getframe(1).f_code.co_name == "_iter_rasters":
            raise ModuleNotFoundError("No module named 'mupdf'", name="mupdf")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", falso)


def _quebrar_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    """A máquina recusa a alocação do raster."""

    def estoura(*_a: object, **_k: object) -> object:
        raise MemoryError("não coube")

    monkeypatch.setattr(ocr_mod, "_iter_rasters", estoura)


def _quebrar_memoria_encapsulada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q15.b: the backend preserves allocation failure behind an exception."""
    def estoura(_imagem):
        try:
            raise MemoryError("allocation refused")
        except MemoryError as original:
            raise RuntimeError("inference failed") from original

    monkeypatch.setattr(ocr_mod, "motor_imagem", estoura)


MODOS = [
    ("import da nativa", _quebrar_import), ("memória", _quebrar_memoria),
    ("memória encapsulada", _quebrar_memoria_encapsulada),
]

PDFS = [("escaneado", lambda: bytes_pdf(texto=None, com_imagem=True)),
        ("misto", bytes_pdf_misto)]


@pytest.fixture(autouse=True)
def motor_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um motor de OCR que sempre responde — o defeito não é falta de motor."""
    monkeypatch.setattr(ocr_mod, "motor_imagem", lambda _img: "texto reconhecido")


# --------------------------------------------------------------------------- #
# A matriz


@pytest.mark.parametrize("modo,quebrar", MODOS, ids=[m for m, _ in MODOS])
@pytest.mark.parametrize("forma,fabrica", PDFS, ids=[f for f, _ in PDFS])
def test_ocr_pdf_levanta_em_vez_de_devolver_none(monkeypatch, modo, quebrar, forma, fabrica):
    """`ocr_pdf` devolvia `None`, que é o valor de "não há motor" — o silêncio."""
    quebrar(monkeypatch)
    with pytest.raises(FalhaDeAmbiente):
        ocr_mod.ocr_pdf(fabrica())


@pytest.mark.parametrize("modo,quebrar", MODOS, ids=[m for m, _ in MODOS])
@pytest.mark.parametrize("forma,fabrica", PDFS, ids=[f for f, _ in PDFS])
def test_doc_de_ocr_levanta_em_vez_de_devolver_none(monkeypatch, modo, quebrar, forma, fabrica):
    """`doc_de_ocr` é a camada acima, e `None` ali vira "fique com o parse barato"."""
    quebrar(monkeypatch)
    with pytest.raises(FalhaDeAmbiente):
        ocr_mod.doc_de_ocr(fabrica(), "x.pdf")


@pytest.mark.parametrize("modo,quebrar", MODOS, ids=[m for m, _ in MODOS])
def test_scan_sem_texto_nativo_vira_erro_e_nunca_vazio(monkeypatch, tmp_path, modo, quebrar):
    """O funil que o indexador executa. `erro` manda quarentenar; `vazio` não.

    É a asserção que importa do pacote: a fase de OCR pode falhar, mas não pode
    falhar **parecendo** um documento que não tinha texto. Vale para o PDF que
    não tem nada além do scan — aí não há o que preservar.

    Ramo **em processo** de `parse_isolado`: `deve_isolar` é forçado a `False`
    porque a injeção de falha vive neste processo e o `spawn` não a levaria. O
    ramo do filho é conferido em `test_o_filho_isolado_converte_do_mesmo_jeito`.
    """
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    monkeypatch.setattr("segundocerebro.index.isolamento.deve_isolar", lambda _p: False)
    quebrar(monkeypatch)
    r = parse_isolado(str(alvo), worker="parse", ocr=True)
    assert r.status is ParseStatus.ERROR, f"{modo}: saiu {r.status.value}, não `erro`"
    assert MOTIVO_RECURSO in r.detail, (
        f"o detalhe não diz que a causa foi recurso: {r.detail!r} — a linha de "
        "quarentena precisa distinguir 'tente com mais memória' de 'está corrompido'"
    )


@pytest.mark.parametrize("modo,quebrar", MODOS, ids=[m for m, _ in MODOS])
def test_pdf_misto_preserva_o_texto_nativo_quando_o_ocr_cai(monkeypatch, tmp_path, modo, quebrar):
    """A outra metade, e ela é a que uma revisão adversarial teve de me ensinar.

    O OCR é **segunda** passada. Se ele cai por recurso num PDF que já teve
    páginas nativas lidas, deixar a falha subir troca um documento `ok` com
    texto por um `erro` sem nada — e `indexer.aplicar` chama
    `remover_documento`, que apaga chunks e vetores **já gravados**. Some a
    quarentena, que aposenta o documento na segunda tentativa, e o conserto do
    `Q15` ficava pior que o defeito: perder texto indexado é pior que não ganhar
    o do scan.

    O documento fica `ok` sem a versão de OCR carimbada, então volta para
    `documentos_para_ocr` na passada seguinte — que é o comportamento de antes.
    """
    alvo = tmp_path / "misto.pdf"
    alvo.write_bytes(bytes_pdf_misto())
    monkeypatch.setattr("segundocerebro.index.isolamento.deve_isolar", lambda _p: False)
    quebrar(monkeypatch)
    r = parse_isolado(str(alvo), worker="parse", ocr=True)
    assert r.status is ParseStatus.OK, f"{modo}: saiu {r.status.value} — o texto nativo se perdeu"
    assert r.doc is not None and r.doc.blocks, "documento `ok` sem bloco nenhum"
    assert "Nimbus" in " ".join(b.text for b in r.doc.blocks)


def test_o_filho_isolado_converte_do_mesmo_jeito(monkeypatch):
    """O ramo que roda no `spawn`, conferido sem subir processo.

    Ele tem o seu próprio `except`, e um dos dois ramos consertado sozinho é
    metade da superfície — a classe que este repositório já nomeou.
    """
    from segundocerebro.index import isolamento

    enviados: list[object] = []
    monkeypatch.setattr(
        isolamento, "parse_file", lambda *_a, **_k: (_ for _ in ()).throw(FalhaDeAmbiente("sem mupdf"))
    )
    conn = type("Conn", (), {"send": lambda _s, v: enviados.append(v), "close": lambda _s: None})()
    isolamento._worker_parse(conn, "x.pdf", {})
    assert enviados and enviados[0].status is ParseStatus.ERROR
    assert MOTIVO_RECURSO in enviados[0].detail


def test_o_caminho_bom_continua_bom(tmp_path, monkeypatch):
    """A régua da matriz: sem quebrar nada, o mesmo PDF sai `ok` com o texto.

    Aqui o dublê é a variável de ambiente, e não o `motor_imagem`: este caminho
    **isola de verdade**, e só o ambiente atravessa o `spawn`.
    """
    monkeypatch.setenv(ocr_mod.VARIAVEL_FAKE, "texto reconhecido")
    alvo = tmp_path / "escaneado.pdf"
    alvo.write_bytes(bytes_pdf(texto=None, com_imagem=True))
    r = parse_isolado(str(alvo), worker="parse", ocr=True)
    assert r.status is ParseStatus.OK, f"saiu {r.status.value}: {r.detail}"
    assert r.doc is not None and "texto reconhecido" in r.doc.blocks[0].text


# --------------------------------------------------------------------------- #
# O discriminador: ausência declarada não é falha de ambiente


def test_extra_ausente_continua_sendo_no_op():
    """`pip install` sem o extra `[ocr]` é no-op, não erro. Não pode regredir."""
    assert ocr_mod._probe("modulo_que_nao_existe_mesmo") is False


def test_falha_transitiva_nao_e_ausencia(monkeypatch):
    """O extra está instalado e não carregou — isso levanta.

    O discriminador é o **nome** do módulo que faltou: pedir `X` e receber
    "falta X" é ausência; pedir `X` e receber "falta Y" é ambiente.
    """
    real = builtins.__import__

    def falso(nome: str, *a: object, **k: object) -> object:
        if nome == "rapidocr_onnxruntime":
            raise ModuleNotFoundError("No module named 'onnxruntime'", name="onnxruntime")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", falso)
    with pytest.raises(FalhaDeAmbiente):
        ocr_mod._probe("rapidocr_onnxruntime")


def test_ausencia_declarada_distingue_os_dois():
    """O discriminador em si, sem depender de nenhum motor instalado."""
    assert ausencia_declarada(ModuleNotFoundError("x", name="pymupdf"), "pymupdf")
    assert not ausencia_declarada(ModuleNotFoundError("y", name="mupdf"), "pymupdf")
    assert not ausencia_declarada(MemoryError("não coube"), "pymupdf")


# --------------------------------------------------------------------------- #
# Q14 — o hook de teste que estava vivo em produção


def _avisos(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """As linhas de `log.warning` deste módulo, já formatadas.

    Nem `caplog` nem `capfd`: `logger.get_logger` põe `propagate = False` na
    raiz e o handler prende o stream na importação, então nenhum dos dois vê a
    linha de forma confiável. Interceptar o logger é determinístico e é o que
    importa — que o aviso exista e diga o quê.
    """
    linhas: list[str] = []
    monkeypatch.setattr(
        ocr_mod.log, "warning", lambda msg, *a: linhas.append(str(msg) % a if a else str(msg))
    )
    return linhas


def test_o_motor_falso_e_ignorado_fora_de_teste(monkeypatch):
    """Variável herdada de shell não muda o produto — e o log diz que foi ignorada."""
    linhas = _avisos(monkeypatch)
    monkeypatch.setenv(ocr_mod.VARIAVEL_FAKE, "texto injetado")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert ocr_mod._fake_de_teste() is None
    assert any("IGNORADA" in linha for linha in linhas), linhas


def test_o_motor_falso_avisa_em_toda_passada(monkeypatch):
    """Sob pytest ele vale, e grita — com o texto que está injetando."""
    linhas = _avisos(monkeypatch)
    monkeypatch.setenv(ocr_mod.VARIAVEL_FAKE, "texto injetado")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "algum::teste")
    assert ocr_mod._fake_de_teste() == "texto injetado"
    assert any("FALSO" in linha and "texto injetado" in linha for linha in linhas), linhas


def test_nenhum_hook_de_teste_sem_guarda_em_src():
    """A classe do `Q14`: variável de ambiente com cara de dublê tem de ter guarda.

    Varre `src/` por `os.environ.get(...)` cujo nome contenha `FAKE`, `TEST`,
    `DEBUG` ou `MOCK`, e exige que o arquivo mencione `PYTEST_CURRENT_TEST` ou
    emita aviso. Hook novo nasce conferido — que é o que faltava quando
    `SEGUNDOCEREBRO_OCR_FAKE` desviava o motor de OCR em produção.
    """
    import ast

    PACOTE = Path(__file__).resolve().parent.parent / "src" / "segundocerebro"
    SUSPEITAS = ("FAKE", "TEST", "DEBUG", "MOCK")
    faltas: list[str] = []
    for arquivo in sorted(PACOTE.rglob("*.py")):
        fonte = arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(fonte, filename=str(arquivo))
        nomes = {
            no.value
            for no in ast.walk(arvore)
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and no.value.startswith("SEGUNDOCEREBRO_")
            and any(s in no.value.upper() for s in SUSPEITAS)
        }
        if not nomes:
            continue
        # `PYTEST_CURRENT_TEST` e nada mais. A primeira versao aceitava
        # `"log.warning" in fonte`, e isso passa para QUALQUER modulo que tenha
        # um aviso em qualquer linha — guarda que nunca reprova. Achado por
        # revisao em 30/08/2026; e a forma que o `CLAUDE.md` ja nomeia.
        if "PYTEST_CURRENT_TEST" not in fonte:
            faltas.append(f"{arquivo.relative_to(PACOTE).as_posix()}: {sorted(nomes)}")
    assert not faltas, (
        "hook de teste alcançável em produção sem guarda de `PYTEST_CURRENT_TEST`:\n  "
        + "\n  ".join(faltas)
    )


def test_a_guarda_de_hook_reprova_contra_caso_isolado():
    """Prova da guarda acima, num módulo sintético onde o hook é a única coisa.

    Contra o arquivo real ela nunca foi provada: casa com um módulo só, e o
    critério antigo (`"log.warning" in fonte`) passava por acidente — qualquer
    aviso em qualquer linha satisfazia. Prova de guarda roda contra caso
    isolado, e a lição vale quando a guarda é minha.
    """
    import ast

    suspeitas = ("FAKE", "TEST", "DEBUG", "MOCK")
    desguardado = 'import os\nx = os.environ.get("SEGUNDOCEREBRO_ALGO_FAKE")\n'
    com_aviso = desguardado + 'log.warning("qualquer coisa")\n'
    guardado = desguardado + 'if "PYTEST_CURRENT_TEST" in os.environ:\n    pass\n'

    def acusa(fonte: str) -> bool:
        nomes = {
            no.value
            for no in ast.walk(ast.parse(fonte))
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and no.value.startswith("SEGUNDOCEREBRO_")
            and any(s in no.value.upper() for s in suspeitas)
        }
        return bool(nomes) and "PYTEST_CURRENT_TEST" not in fonte

    assert acusa(desguardado), "a guarda não vê um hook desguardado isolado"
    assert acusa(com_aviso), "um `log.warning` solto não pode contar como guarda"
    assert not acusa(guardado), "a guarda acusa um hook que TEM guarda"


# --------------------------------------------------------------------------- #
# `Q15.a` — a fase certa apura, e a fase errada não desfaz


@pytest.mark.parametrize("modo,quebrar", MODOS, ids=[m for m, _ in MODOS])
def test_a_repesca_barata_nao_reescreve_vazio_por_cima_do_erro_do_ocr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, modo: str, quebrar
) -> None:  # noqa: ANN001
    """O laço inteiro, e a passada **sem** `--ocr` — que é onde o `Q15.a` vivia.

    A primeira versão deste teste rodava duas passadas com `--ocr` e passava com
    o conserto desligado. Medida a sequência, a razão apareceu: com OCR a fase
    de OCR é a última e regrava o `erro` por cima do `vazio` que o laço barato
    acabou de escrever, então o defeito não aparece. Sem OCR o laço barato é a
    última palavra:

    | passada | `--ocr` | status ao fim, antes do conserto |
    |---|---|---|
    | 1 e 2 | sim | `erro` |
    | 3 e 4 | não | **`vazio`** |

    As duas palavras dizem coisas diferentes: `erro` é *"tentei ler e a máquina
    não deixou"*; `vazio` é *"li e não há texto"*. A segunda é falsa, e era a que
    ficava gravada — e ficava justamente na passada de rotina, que ninguém roda
    com `--ocr`.

    A quarentena é limpa entre as passadas de propósito: o backoff de uma hora
    esconderia o defeito sem consertá-lo, e o que se afirma aqui é sobre a
    **ordem das fases**, não sobre o relógio.
    """
    from segundocerebro.index.indexer import indexar
    from segundocerebro.index.store import Store

    from tests.falsos import DIM, EmbedderFalso, config_de_raiz

    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))
    monkeypatch.setattr("segundocerebro.index.isolamento.deve_isolar", lambda _p: False)
    quebrar(monkeypatch)

    store = Store(tmp_path / "indice", DIM)
    try:
        cfg = config_de_raiz(raiz)
        for passada, com_ocr in enumerate([True, False, False], start=1):
            indexar(
                cfg, store, EmbedderFalso(), publicar=False,
                reconciliar_ao_fim=False, ocr=com_ocr,
            )
            estado = store.estado_documento("escaneado.pdf")
            assert estado is not None, f"passada {passada}: o documento sumiu do registro"
            assert estado.status == ParseStatus.ERROR.value, (
                f"{modo}, passada {passada} (ocr={com_ocr}): status `{estado.status}`. "
                "`vazio` afirma que o documento não tem texto, e o que houve foi a máquina "
                "recusar a leitura — a fase de OCR apurou, e o laço barato desfez."
            )
            store.limpar_quarentena("escaneado.pdf")  # o backoff esconderia o defeito
    finally:
        store.fechar()


def test_o_documento_continua_na_fila_de_ocr_depois_da_falha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ficar `erro` só vale se o documento continuar sendo tentado.

    Um status honesto que tira o documento da fila troca um silêncio por outro:
    o acervo perderia o scan de vez. `digitalizado` é a marca, e ela sobrevive
    porque `registrar_documento` preserva a natureza quando o `ParseResult` não
    traz nenhuma.
    """
    from segundocerebro.index.indexer import indexar
    from segundocerebro.index.repesca import esperando_ocr
    from segundocerebro.index.store import Store
    from segundocerebro.ingest.ocr import VERSAO as OCR_VERSAO

    from tests.falsos import DIM, EmbedderFalso, config_de_raiz

    raiz = tmp_path / "corpus"
    raiz.mkdir()
    (raiz / "escaneado.pdf").write_bytes(bytes_pdf(texto=None, com_imagem=True))
    monkeypatch.setattr("segundocerebro.index.isolamento.deve_isolar", lambda _p: False)
    _quebrar_memoria(monkeypatch)

    store = Store(tmp_path / "indice", DIM)
    try:
        indexar(
            config_de_raiz(raiz), store, EmbedderFalso(), publicar=False,
            reconciliar_ao_fim=False, ocr=True,
        )
        assert "escaneado.pdf" in {rel for rel, _ in store.documentos_para_ocr(OCR_VERSAO)}
        assert esperando_ocr(store) == frozenset({"escaneado.pdf"})
    finally:
        store.fechar()


def _estado_em_erro(**mudancas: object):  # noqa: ANN202
    """Um registro em `erro`, batendo com modelo, chunker, parser e bytes."""
    from segundocerebro.ingest.chunking import CHUNKER_VERSION

    campos = {
        "status": ParseStatus.ERROR.value,
        "tamanho": 10,
        "mtime": 1.0,
        "parser": "p1",
        "model_id": "m",
        "chunker": CHUNKER_VERSION,
        **mudancas,
    }
    return type("Estado", (), campos)()


def test_o_documento_bom_continua_sendo_repescado_quando_o_erro_nao_e_de_scan() -> None:
    """O gate é estreito de propósito: só o que espera OCR perde o atalho.

    Sem esta prova o conserto seria "nada com `erro` volta", que abandonaria em
    silêncio todo documento cuja falha é transitória — a razão de
    `STATUS_PARA_REPESCAR` existir.
    """
    from segundocerebro.index.repesca import _AlvoDoMapa, _precisa_indexar

    alvo = _AlvoDoMapa("rasgado.pdf", 10, 1.0)
    assert _precisa_indexar(_estado_em_erro(), alvo, "m", "p1", frozenset())
    assert not _precisa_indexar(_estado_em_erro(), alvo, "m", "p1", frozenset({"rasgado.pdf"}))


@pytest.mark.parametrize(
    "motivo,estado,model_id,parser,alvo",
    [
        ("parser corrigido", {}, "m", "p2", (10, 1.0)),
        ("modelo trocado", {}, "outro", "p1", (10, 1.0)),
        ("chunker trocado", {"chunker": "chunker:antigo"}, "m", "p1", (10, 1.0)),
        ("bytes novos", {}, "m", "p1", (99, 1.0)),
        ("mtime novo", {}, "m", "p1", (10, 900.0)),
    ],
)
def test_o_scan_que_espera_ocr_ainda_e_alcancado_por_motivo_de_verdade(
    motivo: str, estado: dict, model_id: str, parser: str, alvo: tuple
) -> None:
    """O que o `Q15.a` tira do scan é a passada **gratuita**, não todas.

    Achado em revisão: a primeira versão punha a condição do `Q15.a` **antes** dos
    testes de parser, modelo e chunker, e com isso um scan em `erro` deixava de
    ser alcançado por parser corrigido — trocando um defeito por outro, mais
    silencioso, porque ninguém percebe documento que não volta.
    """
    from segundocerebro.index.repesca import _AlvoDoMapa, _precisa_indexar

    fila = frozenset({"escaneado.pdf"})
    item = _AlvoDoMapa("escaneado.pdf", alvo[0], alvo[1])

    assert _precisa_indexar(_estado_em_erro(**estado), item, model_id, parser, fila), (
        f"{motivo}: o scan devia voltar ao laço, e não voltou"
    )
