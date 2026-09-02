"""Small, real-format fixtures for J.f, never a user's configured corpus."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

import pymupdf

from segundocerebro.ingest.converters.libreoffice import encontrar_soffice
from .gerador.escrita import _docx, _pdf

ROTAS = {"nativo": 2, "libreoffice": 2, "ocr": 2}


def rasterizar(origem: Path, destino: Path) -> None:
    """Use a genuine image-only PDF, not the generator's empty scan fixture."""
    with pymupdf.open(origem) as fonte, pymupdf.open() as scan:
        for pagina in fonte:
            pix = pagina.get_pixmap(matrix=pymupdf.Matrix(2, 2))
            nova = scan.new_page(width=pagina.rect.width, height=pagina.rect.height)
            nova.insert_image(nova.rect, pixmap=pix)
        scan.save(destino)


def gerar(raiz: Path) -> dict[str, str]:
    """Create six distinct documents; conversion is preparation, never timed."""
    binario = encontrar_soffice()
    if not binario:
        raise RuntimeError("LibreOffice necessário para o corpus J.f")
    raiz.mkdir()  # Refuse an existing destination instead of overwriting it.
    preparo, corpus = raiz / "preparo", raiz / "corpus"
    preparo.mkdir()
    corpus.mkdir()
    for n in range(1, 3):
        for rota in ROTAS:
            texto = f"Contrato NN-VCE-{n:03d} - rota {rota}\n" + "\n".join(
                f"Clausula {k}: a Varzea Clara Energia entrega o relatorio em {k + n} dias."
                for k in range(1, 9)
            )
            if rota == "nativo":
                _pdf(corpus / f"textual-{n}.pdf", texto)
            elif rota == "ocr":
                original = preparo / f"scan-{n}.pdf"
                _pdf(original, texto)
                rasterizar(original, corpus / original.name)
            else:
                original = preparo / f"legado-{n}.docx"
                _docx(original, texto)
                subprocess.run(  # noqa: S603 — fixed arguments and generated paths, no shell
                    [binario, "--headless", "--norestore", "--nologo",
                     f"-env:UserInstallation={(preparo / 'perfil').resolve().as_uri()}",
                     "--convert-to", "doc:MS Word 97", "--outdir", str(corpus), str(original)],
                    check=True, capture_output=True, timeout=60,
                )
                if not (corpus / f"legado-{n}.doc").is_file():
                    raise RuntimeError("LibreOffice não gerou o Word OLE sintético")
    arquivos = manifesto(corpus)
    if len(arquivos) != sum(ROTAS.values()):
        raise RuntimeError("Corpus J.f incompleto")
    return arquivos


def manifesto(corpus: Path) -> dict[str, str]:
    """Hash and pre-read generated inputs identically before either arm."""
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(corpus.iterdir())}
