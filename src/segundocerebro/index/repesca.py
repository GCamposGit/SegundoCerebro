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


def esperando_ocr(store) -> frozenset[str]:  # noqa: ANN001
    """Os documentos que pertencem à fase de OCR, e não a este laço.

    `Q15.a`, 31/08/2026, e o conserto só ficou certo depois de **medir a
    sequência** — a primeira versão consertava um caso que já funcionava.

    Medido, com o OCR falhando por `MemoryError` em quatro passadas seguidas
    sobre o mesmo scan:

    | passada | `--ocr` | status ao fim |
    |---|---|---|
    | 1 e 2 | sim | `erro` (`recurso: ...`) |
    | 3 e 4 | **não** | **`vazio`** |

    Com OCR o defeito não aparece: a fase de OCR é a última e regrava o `erro`
    por cima do `vazio` que o laço barato acabou de escrever. **Sem** OCR o laço
    barato é a última palavra, e ele rebaixa `erro` para `vazio` — que é o
    `Q15.a`. As duas palavras dizem coisas diferentes: `erro` é *"tentei ler e a
    máquina não deixou"*; `vazio` é *"li e não há texto"*. A segunda é falsa.

    A regra que fecha a classe não é sobre OCR: **passada que não pode melhorar o
    resultado não reprocessa, e nunca sobrescreve o que a passada capaz apurou.**
    Ela já estava escrita neste arquivo para `parser ocr:*` e para o `vazio` ficar
    fora de `STATUS_PARA_REPESCAR` — *"PDFs digitalizados são a fila da fase OCR,
    não desta repesca"*. Faltava valer para o `erro`.

    Não depende de a passada rodar OCR, e é aí que a primeira versão errou: o
    documento fica na fila com `digitalizado = 1` de qualquer jeito, e um status
    honesto que só sobrevive quando alguém lembra de passar `--ocr` não é uma
    garantia, é uma coincidência.

    A fila sai de `store.documentos_para_ocr`, que é a **mesma** consulta que a
    fase de OCR usa para escolher o que processar. Uma segunda regra aqui seria
    duas noções de "documento que espera OCR", e neste repositório regra derivada
    duas vezes já deu número menor e plausível.
    """
    return frozenset(rel for rel, _raiz in store.documentos_para_ocr(OCR_VERSAO))


def pular_por_quarentena(store, arquivo, sha: str, progresso, estimador, publicador) -> bool:  # noqa: ANN001
    """Este documento está em backoff de quarentena? Então a passada não o toca.

    Saiu do corpo de `indexar()` em 31/08/2026, junto com o `Q15.a`: a função
    está em `FUNCOES_ACIMA_DO_TETO` e a tabela só desce, então o que entra ali
    tem de ser pago com o que sai. Esta é a decisão de "reprocessar ou não" mais
    antiga do laço, e é deste módulo — não do laço — que ela é.
    """
    if not store.deve_pular_quarentena(arquivo.rel, sha):
        return False
    progresso.quarentena += 1
    progresso.registrar_falha("quarentena")
    estimador.pular(arquivo.rel, arquivo.size)
    if publicador is not None:
        publicador.anotar(falhas=progresso.falhas, quarentena=progresso.quarentena)
        publicador.publicar()
    return True


def _do_ocr_e_nao_deste_laco(estado, arquivo, em_ocr) -> bool:  # noqa: ANN001
    """Este `erro` é de um scan que espera OCR? Então o atalho de status não vale.

    `Q15.a`, e o recorte estreito veio de revisão. A função nomeia **só** a
    exceção ao atalho de `STATUS_PARA_REPESCAR` — não "não reprocessar nunca", que
    era o que a primeira versão fazia e que trocava um defeito por outro: um scan
    em `erro` deixava de ser alcançado por parser corrigido, por troca de modelo e
    por troca de chunker, porque a condição vinha antes dos três.

    O que o scan perde é a passada **gratuita** que o status lhe dava, e que só
    produzia `vazio` por cima do `erro` que a fase capaz apurou. Tudo que é motivo
    de verdade para reprocessar continua abaixo e continua valendo.
    """
    return bool(em_ocr) and estado.status == ParseStatus.ERROR.value and arquivo.rel in em_ocr


def _precisa_indexar(estado, arquivo, model_id: str, parser: str, em_ocr=frozenset()) -> bool:  # noqa: ANN001
    if estado is None:
        return True
    if estado.status in STATUS_PARA_REPESCAR and not _do_ocr_e_nao_deste_laco(
        estado, arquivo, em_ocr
    ):
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


EXTENSOES_COM_RASTER = frozenset({".pptx", ".pptm", ".ppt", ".docx", ".docm"})


def versao_efetiva(extensao: str) -> str:
    """Base parser version, plus ``+raster`` when this process can OCR pictures.

    CPU-only machines keep the plain version, so a deck already indexed there
    is not re-embedded. A machine whose CUDA kernel runs asks for ``+raster``
    and revisits those extensions once. The suffix is the record that the
    text may contain picture OCR.
    """
    base = parser_version_for(extensao)
    if extensao.lower() not in EXTENSOES_COM_RASTER:
        return base
    from ..ingest.ocr import gpu_para_ocr

    if gpu_para_ocr():
        return f"{base}+raster"
    return base


def _parser_gravado(resultado: ParseResult, rel: str) -> str:
    if resultado.doc is not None and resultado.doc.meta.get("fonte") == "ocr":
        return resultado.doc.meta.get("parser") or OCR_VERSAO
    return versao_efetiva(os.path.splitext(rel)[1])


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
