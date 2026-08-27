"""Transcrição de reunião — `.vtt`, `.srt`, `.sbv`. O `F4-T`.

Existe porque a lacuna era invisível e caríssima: `retrieve/fonte.py` classifica
estas três extensões como grupo `reunião` e `retrieve/hybrid.py` escolhe peso de
ranqueamento por esse grupo, para um formato que o despachante **não lia**. Medido
em 27/08/2026 no índice sintético do `E1`: 200 documentos de reunião registrados,
**3** com chunk, e **0** das 100 perguntas da fatia com fonte indexada — a medição
da `F4-P.1` teria dado empate e fechado o pacote como "hipótese refutada".
Laudo em `docs/fatia-reuniao-invisivel.md`.

E é produto, não laboratório: `.vtt` e `.srt` são a saída nativa de Teams, Zoom e
Meet. Quem aponta a pasta das próprias reuniões tinha o arquivo **contado e não
indexado** — a barra somava, o registro guardava zero chunk, e a busca nunca o
devolvia.

Três decisões de formato, cada uma com o motivo:

1. **A legenda não é a unidade.** Um cue de transcrição tem 3 a 8 palavras; uma
   reunião de uma hora tem mais de mil. Emitir um `Block` por cue produziria
   milhares de trechos de ~40 caracteres, e este repositório já pagou por chunk
   curto demais (o email com URL longa que virou chunk de 82 caracteres). Os cues
   são fundidos em parágrafo até `ALVO_CHARS_POR_BLOCO`, ou até um silêncio de
   `SALTO_DE_ASSUNTO` segundos, que é a única fronteira que a transcrição oferece
   de graça.
2. **A marca de tempo é a procedência** (invariante 5). Cada bloco leva no
   `locator` o instante em que começa, no formato `MM:SS` ou `H:MM:SS` — é o que
   permite a alguém abrir a gravação no ponto.
3. **Legenda rolante é ruído, e é a maioria dos bytes.** Teams e Meet reemitem o
   cue crescendo palavra por palavra ("Bom", "Bom dia", "Bom dia a todos"). Sem
   desduplicar, o texto indexado é o mesmo trecho dezenas de vezes, e o ranqueador
   denso vê um documento que repete. `_absorver` mantém só a forma mais longa.

**O que este parser não faz:** diarização, correção de pontuação, e detectar
idioma. Também não reconstrói título — transcrição não tem heading, e inventar um
mudaria `contextual_text` sem número que o justifique.
"""

from __future__ import annotations

import re

from ..document import Block, BlockKind, ParsedDoc
from . import register
from .text import decode

ALVO_CHARS_POR_BLOCO = 1500
"""Tamanho de parágrafo que os cues fundidos perseguem.

Escolhido **abaixo** do orçamento de chunk padrão para o chunker não precisar
cortar no meio de uma fala. Não é limite rígido: a fala em curso termina, porque
cortar no meio de uma frase é pior que um bloco 10% maior."""

SALTO_DE_ASSUNTO = 8.0
"""Silêncio, em segundos, que fecha o parágrafo antes de ele atingir o alvo.

Numa reunião a pausa longa é troca de assunto — a única fronteira estrutural que
uma transcrição dá sem adivinhação. Oito segundos é conservador de propósito:
erra para o bloco maior, que o chunker resolve, em vez de fragmentar."""

_SETA = re.compile(
    r"^\s*(?P<ini>\d{1,3}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
    r"\s*(?:-->|,)\s*"
    r"(?P<fim>\d{1,3}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
)
"""A linha de tempo dos três formatos, num padrão só.

`-->` é VTT e SRT; a vírgula é SBV. O separador decimal é `.` no VTT/SBV e `,` no
SRT, então os dois entram. Hora é opcional (`01:23.000` existe em VTT curto)."""

_BLOCO_IGNORADO = re.compile(r"^\s*(NOTE|STYLE|REGION)\b", re.IGNORECASE)
"""Blocos de metadado do WebVTT. Correm até a linha em branco e não são fala."""

_VOZ = re.compile(r"<v[^>]*?\s+([^>]+?)\s*>", re.IGNORECASE)
"""`<v Fulano>` — como Teams e Meet marcam quem fala."""

_TAG = re.compile(r"</?[cibuv](?:\.[^>\s]+)?[^>]*>|</?\d{2}:\d{2}[^>]*>", re.IGNORECASE)
"""Marcação inline de estilo e de karaokê. `<c.colorE5E5E5>`, `<i>`, `<00:01.000>`."""

_ENTIDADES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&quot;": '"', "&#39;": "'"}

_FALANTE_SOLTO = re.compile(r"^([^:<>]{2,40}):\s+(\S.*)$")
"""`Fulano: bom dia` — a forma que Zoom exporta, sem tag de voz.

Conservador de propósito: até 40 caracteres antes dos dois-pontos, sem `<` nem
`>`, e é preciso haver texto depois. `_parece_nome` ainda recusa o que tem cara de
frase, senão "Resumo: fechamos o contrato" perderia a palavra `Resumo`."""

_FIM_DE_FRASE = re.compile(r"[.!?…]")


def _parece_nome(candidato: str) -> bool:
    """Filtro do falante solto: nome de gente, não começo de frase.

    Sem isto, toda linha com dois-pontos perderia o que vem antes deles. A regra
    é de forma, não de vocabulário: no máximo cinco palavras, nenhuma pontuação de
    fim de frase, e não termina em vírgula."""
    if _FIM_DE_FRASE.search(candidato) or candidato.endswith(","):
        return False
    palavras = candidato.split()
    return 1 <= len(palavras) <= 5


def _segundos(marca: str) -> float:
    """`00:12:30.500` → 750.5. Aceita com e sem hora, com `.` ou `,`."""
    marca = marca.strip().replace(",", ".")
    partes = marca.split(":")
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        return 0.0
    while len(valores) < 3:
        valores.insert(0, 0.0)
    horas, minutos, segundos = valores[-3:]
    return horas * 3600 + minutos * 60 + segundos


def _locator(total: float) -> str:
    """Instante como alguém o procuraria na gravação: `12:30`, `1:05:09`."""
    total = max(0, int(total))
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segundos:02d}"
    return f"{minutos:02d}:{segundos:02d}"


def _limpar(linha: str) -> tuple[str | None, str]:
    """Devolve `(falante, texto)` de uma linha de fala, já sem marcação."""
    falante = None
    m = _VOZ.search(linha)
    if m:
        falante = m.group(1).strip() or None
    linha = _VOZ.sub("", linha)
    linha = _TAG.sub("", linha)
    for entidade, char in _ENTIDADES.items():
        linha = linha.replace(entidade, char)
    linha = linha.strip()
    if falante is None:
        m2 = _FALANTE_SOLTO.match(linha)
        if m2 and _parece_nome(m2.group(1)):
            falante, linha = m2.group(1).strip(), m2.group(2).strip()
    return falante, linha


def _absorver(acumulado: list[str], texto: str) -> None:
    """Junta a fala nova, tratando legenda rolante como uma fala só.

    Teams reemite o cue crescendo. Se o texto novo contém o anterior, ele
    **substitui**; se o anterior já contém o novo, o novo é descartado. Qualquer
    outra coisa é fala nova.
    """
    if not texto:
        return
    if acumulado:
        ultimo = acumulado[-1]
        if texto == ultimo or ultimo.endswith(texto):
            return
        if texto.startswith(ultimo):
            acumulado[-1] = texto
            return
    acumulado.append(texto)


class _Cue:
    __slots__ = ("inicio", "fim", "falante", "texto")

    def __init__(self, inicio: float, fim: float, falante: str | None, texto: str) -> None:
        self.inicio = inicio
        self.fim = fim
        self.falante = falante
        self.texto = texto


def _cues(texto: str) -> list[_Cue]:
    """Extrai os cues dos três formatos, ignorando metadado e índice de SRT."""
    linhas = texto.splitlines()
    cues: list[_Cue] = []
    i = 0
    n = len(linhas)
    while i < n:
        linha = linhas[i]
        if _BLOCO_IGNORADO.match(linha):
            i += 1
            while i < n and linhas[i].strip():
                i += 1
            continue
        m = _SETA.match(linha)
        if not m:
            i += 1
            continue
        inicio = _segundos(m.group("ini"))
        fim = _segundos(m.group("fim"))
        i += 1
        falas: list[str] = []
        falante_do_cue: str | None = None
        while i < n and linhas[i].strip() and not _SETA.match(linhas[i]):
            falante, limpo = _limpar(linhas[i])
            if falante and falante_do_cue is None:
                falante_do_cue = falante
            if limpo:
                falas.append(limpo)
            i += 1
        corpo = " ".join(falas).strip()
        if corpo:
            cues.append(_Cue(inicio, max(fim, inicio), falante_do_cue, corpo))
    return cues


def _blocos(cues: list[_Cue]) -> list[Block]:
    """Funde cues em parágrafos, quebrando por tamanho ou por silêncio."""
    blocos: list[Block] = []
    falas: list[str] = []
    inicio_do_bloco: float | None = None
    fim_anterior: float | None = None
    falante_corrente: str | None = None

    def fechar() -> None:
        nonlocal falas, inicio_do_bloco, falante_corrente
        conteudo = "\n".join(falas).strip()
        if conteudo and inicio_do_bloco is not None:
            blocos.append(
                Block(
                    heading_path=(),
                    text=conteudo,
                    locator=_locator(inicio_do_bloco),
                    kind=BlockKind.TEXT,
                )
            )
        falas = []
        inicio_do_bloco = None
        falante_corrente = None

    for cue in cues:
        if inicio_do_bloco is None:
            inicio_do_bloco = cue.inicio
        elif (
            sum(len(f) for f in falas) >= ALVO_CHARS_POR_BLOCO
            or (fim_anterior is not None and cue.inicio - fim_anterior >= SALTO_DE_ASSUNTO)
        ):
            fechar()
            inicio_do_bloco = cue.inicio

        if cue.falante and cue.falante != falante_corrente:
            falante_corrente = cue.falante
            falas.append(f"{cue.falante}: {cue.texto}")
        else:
            _absorver(falas, cue.texto)
        fim_anterior = cue.fim

    fechar()
    return blocos


@register(".vtt", ".srt", ".sbv")
def parse_transcricao(dados: bytes, nome: str) -> ParsedDoc:
    """Transcrição → blocos de parágrafo com a marca de tempo como procedência.

    Documento sem nenhum cue reconhecível devolve zero blocos, e o indexador o
    marca `vazio` — que é o comportamento honesto para um `.vtt` que só tem
    cabeçalho, e o oposto de inventar um bloco com o nome do arquivo.
    """
    conteudo = decode(dados)
    blocos = _blocos(_cues(conteudo))
    return ParsedDoc(name=nome, blocks=tuple(blocos), meta={"formato": "transcrição"})
