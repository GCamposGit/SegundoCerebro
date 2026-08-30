"""Este documento precisa ser processado de novo? — a política, sem o laço.

Saiu de `indexer.py` em 29/08/2026. É a regra que decide o que uma passada
retomada refaz, e ela muda por um motivo próprio: um status novo, um parser
corrigido, um formato que passou a ter motor. O laço de indexação muda por outro.

Três dos cinco símbolos daqui já eram importados diretamente pela suíte
(`STATUS_PARA_REPESCAR`, `_precisa_indexar`), o que é o sinal usual de que a
fronteira já existia e faltava o arquivo.
"""

from __future__ import annotations

import os
from typing import NamedTuple

from ..ingest.chunking import CHUNKER_VERSION
from ..ingest.document import ParseResult, ParseStatus
from ..ingest.ocr import VERSAO as OCR_VERSAO
from ..ingest.parsers import parser_version_for
from .isolamento import deve_isolar


STATUS_PARA_REPESCAR = frozenset(
    {
        ParseStatus.LOCKED.value,
        ParseStatus.CLOUD_ONLY.value,
        ParseStatus.ERROR.value,
        ParseStatus.UNSUPPORTED.value,
        ParseStatus.DEFERRED.value,
    }
)
"""Status cuja causa está fora do arquivo, e por isso pode ter mudado sozinha.

Sem isto o documento é pulado para sempre: `_precisa_indexar` compara tamanho,
mtime, modelo e chunker, e um arquivo que estava aberto no Word passa nos quatro.
O ROADMAP promete o oposto — "registrar status `travado` e reindexar na próxima
passada, nunca descartar em silêncio" — e a promessa não estava implementada.
Encontrado em 13/08/2026, com um `.docx` travado durante a reconstrução.

- `travado`: o Word fechou desde então
- `placeholder`: o arquivo pode ter sido hidratado
- `erro`: leitura rasgada é transitória; corrupção de verdade custa uma tentativa
  por passada, e é preço baixo para não abandonar documento em silêncio
- `sem_parser`: quase sempre custo zero, porque o despachante recusa pela
  extensão antes de ler byte — e é o que faz um parser novo alcançar o que ficou
  para trás, já que `CHUNKER_VERSION` não cobre versão de parser

`vazio` fica de fora de propósito: é determinístico dados os mesmos bytes e o
mesmo parser. PDFs digitalizados são a fila da fase OCR (R1.2), não desta
repesca — reparseá-los como PDF barato apagaria o texto do OCR."""


def _precisa_indexar(estado, arquivo, model_id: str, parser: str) -> bool:  # noqa: ANN001
    if estado is None:
        return True
    if estado.status in STATUS_PARA_REPESCAR:
        return True
    bytes_mudaram = estado.tamanho != arquivo.size or abs(estado.mtime - arquivo.mtime) > 1e-6
    if (estado.parser or "").startswith("ocr:"):
        # Cheap PDF parse would wipe OCR text back to vazio. The OCR phase
        # owns these rows unless the file itself changed.
        return bytes_mudaram
    if estado.model_id != model_id or estado.chunker != CHUNKER_VERSION:
        return True
    # Parser corrigido alcança o que já está indexado. Sem esta linha, o único
    # caminho era apagar linha do registro à mão — foi o que um `.msg` de 343
    # chunks exigiu em 21/08/2026, e é o que o comentário acima admitia faltar.
    if estado.parser != parser:
        return True
    if bytes_mudaram:
        return True
    return False


def _parser_gravado(resultado: ParseResult, rel: str) -> str:
    if resultado.doc is not None and resultado.doc.meta.get("fonte") == "ocr":
        return resultado.doc.meta.get("parser") or OCR_VERSAO
    return parser_version_for(os.path.splitext(rel)[1])


class _AlvoDoMapa(NamedTuple):
    """O mínimo que `_precisa_indexar` lê de um arquivo enumerado.

    Nomeado e no topo do módulo porque a alternativa — declarar uma classe
    dentro do laço — criava um tipo novo por arquivo por ciclo, milhares por
    passada, para carregar três campos.
    """

    rel: str
    size: int
    mtime: float


def _venenoso(resultado: ParseResult) -> bool:
    """The class R1.4 isolates: crash, timeout, empty binary, parser abort."""
    if resultado.status is not ParseStatus.ERROR:
        return False
    detalhe = (resultado.detail or "").lower()
    if detalhe.startswith("arquivo de 0 bytes"):
        return True
    if "timeout" in detalhe or "subprocesso morreu" in detalhe:
        return True
    return deve_isolar(resultado.path)


def preservar_no_erro_de_ocr(store, progresso, rel: str, estado, resultado: ParseResult) -> bool:  # noqa: ANN001
    """A fase de OCR falhou num documento que já tinha texto? Então nada se apaga.

    `True` quando o chamador deve **pular** o `aplicar` — e é o ponto do
    conserto (30/08/2026). A fase de OCR reparseia o que já está indexado, e
    `aplicar` faz `remover_documento` antes de regravar: falhar ali apagava
    chunks **e vetores** que as ondas de texto tinham produzido. O documento
    saía do acervo por causa de uma segunda passada que era só um bônus.

    A quarentena entra, para a próxima tentativa saber o que houve; o estado de
    antes fica de pé. Documento sem chunk nenhum segue o caminho normal — ali
    não há o que preservar.
    """
    if resultado.status is ParseStatus.OK or estado is None or estado.n_chunks <= 0:
        return False
    store.registrar_quarentena(rel, hash=estado.sha256 or "", motivo=resultado.detail)
    progresso.quarentena += 1
    return True
