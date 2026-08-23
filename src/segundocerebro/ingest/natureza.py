"""Natureza do arquivo: o que ele é, e não o que a extensão diz que é.

Duas coisas moram aqui, e as duas nasceram de defeito medido:

1. **Tipo real por assinatura.** O despachante de parser usava só a extensão. O
   corpus tem um arquivo `.pdf` cujo conteúdo é email MIME, e ele falhou como
   `FileDataError: Failed to open stream` — que soa como PDF corrompido e mandou
   a investigação para o lado errado por meia hora. A assinatura custa 16 bytes
   que já estão em mão.

2. **Flags de natureza persistidas.** O parser de PDF já sabia dizer
   `suspeita=digitalizado`, mas isso vivia em `ParsedDoc.meta` e era descartado.
   Consequência: um PDF digitalizado e um PDF de verdade vazio recebiam o mesmo
   `status='vazio'`, e separar os dois exigia script avulso. Gravadas, viram
   consulta — a fila de OCR da F4 deixa de ser investigação manual, e a anotação
   `fora_de_escopo` do conjunto dourado passa a ser conferível contra o índice.

O que **não** entrou, e por quê: `is_composite` (documento com várias seções
independentes) e `has_sommaire` (página de sumário impressa com pontinhos) são
sinais do artigo que motivou este módulo. O primeiro é caro e difuso de detectar;
o segundo resolve uma convenção tipográfica que este acervo quase não tem. Nenhum
dos dois tem uso a jusante hoje, e flag sem consumidor é peso morto que envelhece
sem ninguém notar. Voltam quando houver etapa que os leia.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

# Assinaturas suficientes para o acervo real. Não é detecção genérica de tipo:
# é a pergunta estreita "a extensão está mentindo?".
ASSINATURAS: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "ooxml"),  # docx, xlsx, pptx — zip por baixo
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),  # doc, xls, msg legado
    (b"{\\rtf", "rtf"),
    (b"\x89PNG", "imagem"),
    (b"\xff\xd8\xff", "imagem"),
)

# Cabeçalhos de email MIME. Verificados por prefixo de linha, não de arquivo,
# porque um `.eml` pode começar por qualquer um deles.
CABECALHOS_EMAIL: tuple[bytes, ...] = (
    b"Received:",
    b"Return-Path:",
    b"MIME-Version:",
    b"Delivered-To:",
    b"Message-ID:",
    b"From: ",
)

FAMILIA_POR_EXTENSAO: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "ooxml",
    ".dotx": "ooxml",
    ".xlsx": "ooxml",
    ".xlsm": "ooxml",
    ".pptx": "ooxml",
    ".potx": "ooxml",
    ".doc": "ole",
    ".xls": "ole",
    ".xlsb": "ole",
    ".ppt": "ole",
    ".msg": "ole",
    ".eml": "email",
    ".rtf": "rtf",
    ".md": "texto",
    ".txt": "texto",
    ".csv": "texto",
    ".tsv": "texto",
}

FAMILIAS_BINARIAS = frozenset({"pdf", "ooxml", "ole", "rtf", "imagem"})
"""Só para estas a assinatura é autoridade.

Um `.csv` que comece com `From: ` é um csv com uma coluna chamada From, não um
email. Acusar mentira em arquivo de texto seria falso positivo garantido."""

BYTES_DE_ASSINATURA = 8192
"""Cabeçalho de email pode vir depois de algumas linhas; 8 KB cobre com folga e
não muda nada no custo, porque os bytes já foram lidos inteiros."""


@dataclass(frozen=True)
class Natureza:
    """Sinais determinísticos sobre um arquivo. Nenhum LLM, nada probabilístico."""

    familia_real: str = ""
    """Família detectada por assinatura. Vazio quando nenhuma casou."""

    extensao_mente: bool = False
    """A assinatura contradiz a extensão. Só afirmado para família binária."""

    digitalizado: bool = False
    """Sem camada de texto útil: imagem por página. Candidato a OCR (F4)."""

    tem_sumario_nativo: bool = False
    """O PDF traz índice (outline/TOC) embutido — estrutura de graça, melhor que
    a heurística de tamanho de fonte. Gravado agora, aproveitado quando houver
    medição que justifique trocar o motor de headings."""

    tem_tabela: bool = False
    """O documento produziu bloco de tabela ou planilha."""

    figuras_por_pagina: float = 0.0
    """Densidade de imagem. Alta com pouco texto é o padrão de scan; alta com
    texto é apresentação ou relatório ilustrado."""

    paginas: int = 0

    def como_colunas(self) -> dict[str, object]:
        """Para o registro: booleano vira 0/1, que é o que o SQLite guarda."""
        saida: dict[str, object] = {}
        for chave, valor in asdict(self).items():
            saida[chave] = int(valor) if isinstance(valor, bool) else valor
        return saida


EXTENSOES_DE_PLANILHA = (".xlsx", ".xlsm", ".xltx")

EXTENSOES_DE_TEXTO_BRUTO = (".txt", ".csv")
"""Dumps, not documents. A 269 MB `.txt` became 176 k chunks — 73% of one
index — and a 68 MB `.csv` froze the progress bar for hours. They share a
parser with short notes, so the size/chunk caps have to live at the gate."""


def mb_de_abas(dados: bytes) -> float | None:
    """Megabytes de XML de aba dentro de um XLSX, sem descomprimir nada.

    É o preditor de custo que funciona para planilha. O tamanho em disco não
    serve: uma planilha de 17,9 MB comprimidos carrega **124 MB de XML em 69
    abas** e leva duas horas para indexar, enquanto outra de 50 MB com poucas
    fórmulas passa em segundos. O tamanho descompactado está no índice central do
    zip, então a leitura é do cabeçalho e custa microssegundos.

    Devolve `None` quando não é um zip legível — arquivo corrompido ou formato
    que só parece planilha.
    """
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            return (
                sum(
                    i.file_size
                    for i in z.infolist()
                    if i.filename.startswith("xl/worksheets/") and i.filename.endswith(".xml")
                )
                / 1e6
            )
    except Exception:  # noqa: BLE001
        return None


def familia_por_assinatura(dados: bytes) -> str:
    """Família do conteúdo, ou string vazia se nenhuma assinatura casar."""
    for magica, familia in ASSINATURAS:
        if dados.startswith(magica):
            return familia

    cabeca = dados[:BYTES_DE_ASSINATURA]
    for linha in cabeca.split(b"\n", 40)[:40]:
        if any(linha.startswith(h) for h in CABECALHOS_EMAIL):
            return "email"
    return ""


def detectar(path: str, dados: bytes, doc=None) -> Natureza:  # noqa: ANN001
    """Junta o que a assinatura diz com o que o parser descobriu.

    `doc` é o `ParsedDoc`, quando existe — inclusive quando ele veio sem bloco
    nenhum, que é justamente o caso do PDF digitalizado: o parser preenche `meta`
    antes de desistir, e é de lá que sai a flag.
    """
    from .document import BlockKind

    real = familia_por_assinatura(dados)
    extensao = os.path.splitext(path)[1].lower()
    esperada = FAMILIA_POR_EXTENSAO.get(extensao, "")

    mente = bool(real) and bool(esperada) and real != esperada and esperada in FAMILIAS_BINARIAS

    meta = dict(getattr(doc, "meta", {}) or {})
    paginas = int(meta.get("paginas") or 0)
    com_imagem = int(meta.get("paginas_com_imagem") or 0)
    blocos = getattr(doc, "blocks", ()) or ()

    return Natureza(
        familia_real=real,
        extensao_mente=mente,
        digitalizado=meta.get("suspeita") == "digitalizado",
        tem_sumario_nativo=meta.get("sumario_nativo") == "1",
        tem_tabela=any(b.kind in (BlockKind.TABLE, BlockKind.SHEET) for b in blocos),
        figuras_por_pagina=(com_imagem / paginas) if paginas else 0.0,
        paginas=paginas,
    )
