"""Os dublês que a suíte inteira usa. Um lugar, e não um arquivo de teste.

Pacote `Q17`, 30/08/2026. `tests/test_index.py` exportava `DIM`,
`EmbedderFalso`, `chunk` e `corpus` para **18 sítios de import em 14 arquivos**
— dez em `tests/`, três em `eval/` e o `servidor_falso.py`, que nem teste é.
Qualquer refator naquele arquivo quebrava os quatorze, e era um conftest
informal com nome de teste: ninguém abre `test_index.py` esperando encontrar a
infraestrutura da suíte.

Um dos sítios importava **sem o prefixo do pacote** — `from test_index import`,
sem `tests.` na frente —, dependendo do `rootdir` que o pytest calculasse, e
outro redefinia `DIM = 8` por conta própria em vez de importar. Mesmo sintoma.

Isto **não** é um `conftest.py` porque o que mora aqui é classe e função, não
fixture: conftest serve o que o pytest injeta por nome de parâmetro. A fixture
`store`, que estava duplicada textualmente em `test_index.py` e `test_grafo.py`,
essa sim foi para `tests/conftest.py`, que é onde fixture compartilhada mora.

O código abaixo saiu de `test_index.py` **verbatim**."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from segundocerebro.census import Config, RootSpec
from segundocerebro.ingest.chunking import Chunk
from segundocerebro.ingest.document import BlockKind


DIM = 8


class EmbedderFalso:
    """Deterministic fake — the real model takes seconds to load per test."""

    def __init__(self, model_id: str = "falso:8", dim: int = DIM) -> None:
        self._model_id = model_id
        self.spec = type("Spec", (), {"id": "falso", "dim": dim})()
        self.dim = dim
        self.chamadas = 0
        self._cache_dir = Path("models")

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def orcamento_tokens(self) -> int:
        return 10_000  # folgado: estes testes não exercitam o orçamento

    def contar_tokens(self, texto: str) -> int:
        return len(texto) // 4

    def embed_passagens(self, textos, batch_size: int = 32, ao_progresso=None) -> list[np.ndarray]:  # noqa: ANN001, ARG002
        self.chamadas += len(textos)
        saida = []
        for t in textos:
            semente = int(hashlib.sha1(t.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(semente)
            v = rng.standard_normal(self.dim).astype(np.float32)
            saida.append(v / np.linalg.norm(v))
        if ao_progresso is not None:
            ao_progresso(len(saida), len(saida))
        return saida

    def embed_consulta(self, texto: str) -> np.ndarray:
        return self.embed_passagens([texto])[0]


def chunk(id_: str, path: str, ordinal: int, texto: str, trilha: tuple[str, ...] = ()) -> Chunk:
    return Chunk(
        id=id_,
        doc_path=path,
        ordinal=ordinal,
        heading_path=trilha,
        text=texto,
        locator=f"p. {ordinal + 1}",
        kind=BlockKind.TEXT,
    )


def corpus(raiz: Path) -> Config:
    (raiz / "Política de IA").mkdir(parents=True)
    (raiz / "Política de IA" / "PO-ACME-007_Política_IA_v8.md").write_text(
        "# Política\nO PO-ACME-007 define o uso aceitável de inteligência artificial.\n", encoding="utf-8"
    )
    (raiz / "contrato.md").write_text(
        "# Contrato\nContrato 4600009999 com a Nimbus Tecnologia, vigência de 12 meses.\n", encoding="utf-8"
    )
    (raiz / "vazio.md").write_text("   \n", encoding="utf-8")
    return Config(roots=[RootSpec(name="teste", path=raiz)])


def config_de_raiz(raiz: Path, nome: str = "teste") -> Config:
    """Uma raiz só — a forma repetida textualmente em 16 lugares de 7 arquivos.

    O nome nunca importa (variava entre `teste`, `t`, `r`, `x`, `fmt`,
    `hostil`), exceto onde há duas raízes e ele as distingue. Daí o padrão."""
    return Config(roots=[RootSpec(name=nome, path=raiz)])


def bytes_pdf(texto: str | None = "Contrato 4600009999 com a Nimbus Tecnologia.", com_imagem: bool = False) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    pagina = doc.new_page()
    if com_imagem:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
        pix.set_rect(pix.irect, (200, 200, 200))
        pagina.insert_image(pymupdf.Rect(0, 0, 500, 700), pixmap=pix)
    if texto:
        pagina.insert_text((72, 72), texto, fontsize=11)
    dados = doc.tobytes()
    doc.close()
    return dados


def bytes_pdf_misto(
    nativo: str = "Contrato 4600009999 com a Nimbus Tecnologia.",
) -> bytes:
    """Page 1 native text, page 2 image and no text layer — the mixed-PDF trap."""
    import pymupdf

    doc = pymupdf.open()
    capa = doc.new_page()
    capa.insert_text((72, 72), nativo, fontsize=11)
    corpo = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
    pix.set_rect(pix.irect, (200, 200, 200))
    corpo.insert_image(pymupdf.Rect(0, 0, 500, 700), pixmap=pix)
    dados = doc.tobytes()
    doc.close()
    return dados
