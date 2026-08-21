"""Email: `.msg` do Outlook e `.eml`/MIME — 48 documentos que estavam de fora.

O acervo indexado tinha **48 arquivos `.msg` com status `sem_parser`** e um
arquivo com extensão `.pdf` cujo conteúdo é MIME de email (o caso de "extensão
mente" que `natureza.py` já detectava e ninguém aproveitava). Nenhum deles tinha
um único chunk, e isso é mais grave do que parece: o ranqueador de nome é
construído sobre `paths_com_chunks()`, então um documento sem chunk é invisível
para **todos** os ranqueadores da pilha, inclusive o que só olha o nome do
arquivo. Três perguntas do conjunto dourado corporativo estavam anotadas
`fora_de_escopo: email` justamente por isso, e mediam zero por construção.

## Por que o corpo é partido por mensagem, e não guardado inteiro

Um `.msg` deste acervo raramente é uma mensagem: é uma **thread** de dez ou vinte
respostas, com o histórico citado embaixo. Guardado como um bloco só, o
`heading_path` fica vazio e o chunker corta a thread em pedaços de mil caracteres
sem título nenhum — o pior caso possível para o vetor, porque a decisão que
importa (a última mensagem) fica diluída na negociação inteira. Partindo pelos
cabeçalhos de citação, cada mensagem vira bloco com o assunto na trilha, e
`contextual_text` volta a ter contexto para prefixar.

Os cortes são os que o Outlook em português e em inglês realmente escreve
(`De:`/`From:` seguido de `Enviada em:`/`Sent:`, `-----Mensagem original-----`,
`Em <data>, X escreveu:`). Quando nenhum casa, o corpo continua inteiro — é uma
mensagem só, e forçar corte inventaria estrutura.

## O que ficou de fora, com motivo

- **RTF comprimido** (`PR_RTF_COMPRESSED`, tag `1009`). Exigiria descompressão
  LZFu, e neste acervo não há `.msg` que traga só RTF: todos têm corpo em texto
  ou em HTML. Se aparecer, o documento não fica perdido — o envelope (assunto,
  participantes, anexos) ainda produz bloco, e o status é `ok`, não `vazio`.
- **Anexo como documento próprio.** Um `.msg` com contrato anexado deveria virar
  dois documentos no índice, não um. Mas o portão de leitura (`reader.py`) recebe
  **um caminho** e devolve **um** `ParseResult`, e mudar isso mexe no laço do
  indexador, que é do outro setup (`docs/colaboracao.md` §1). Por ora o **nome**
  do anexo entra no bloco de cabeçalho, que é onde a convenção deste acervo põe
  número de contrato e de pedido.
- **Corpo de imagem** (assinatura escaneada, print de tela). É OCR, que é o outro
  pedaço que falta da F4.

O container do `.msg` é lido pelo `olefile`, não à mão: CFB tem FAT, mini-FAT e
DIFAT, e ler errado um mini-stream devolve bytes plausíveis do lugar errado —
falha silenciosa, que é a classe de defeito que este projeto já pagou caro. O que
é nosso é a camada MAPI, que é uma tabela de nomes de stream: `extract_msg`
resolveria as duas, mas traz seis pacotes transitivos para fazer a metade que
custa dez linhas.
"""

from __future__ import annotations

import datetime as dt
import html
import io
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..document import Block, ParsedDoc
from . import register
from .text import decode

# --- MAPI: nomes de stream dentro do .msg -------------------------------------

PREFIXO_PROPRIEDADE = "__substg1.0_"
PREFIXO_ANEXO = "__attach_version1.0_"
STREAM_DE_PROPRIEDADES = "__properties_version1.0"

TIPO_UNICODE = "001F"
TIPO_ANSI = "001E"
TIPO_BINARIO = "0102"
TIPO_SYSTIME = 0x0040

TAG_ASSUNTO = "0037"
TAG_CORPO = "1000"
TAG_CORPO_HTML = "1013"
TAG_REMETENTE = "0C1A"
TAG_REMETENTE_EMAIL = "0C1F"
TAG_EM_NOME_DE = "0042"
TAG_PARA = "0E04"
TAG_CC = "0E03"
TAG_ANEXO_NOME_LONGO = "3707"
TAG_ANEXO_NOME_CURTO = "3704"

ID_ENVIO = 0x0039
"""`PR_CLIENT_SUBMIT_TIME` — quando o remetente mandou."""

ID_ENTREGA = 0x0E06
"""`PR_MESSAGE_DELIVERY_TIME` — reserva, para a mensagem sem hora de envio."""

CABECALHOS_DE_PROPRIEDADE = (32, 24)
"""Tamanho do cabeçalho do stream de propriedades: 32 no topo, 24 embutido.

Os dois são tentados porque errar o cabeçalho desalinha os registros de 16 bytes
e faz o `FILETIME` sair de um lugar arbitrário. O desempate é a plausibilidade da
data, e não a especificação — arquivo real nem sempre a segue."""

EPOCA_FILETIME = dt.datetime(1601, 1, 1, tzinfo=dt.UTC)
ANO_MINIMO = 1990
ANO_MAXIMO = 2100

FORMATO_DE_DATA = "%d/%m/%Y %H:%M"

# --- corte de thread ----------------------------------------------------------

CORTE_ORIGINAL = re.compile(
    r"^\s*[-_*]{2,}\s*(mensagem original|original message|mensagem encaminhada|forwarded message)",
    re.IGNORECASE,
)
ABRE_CITACAO = re.compile(r"^\s*>*\s*(de|from|remetente)\s*:\s*\S", re.IGNORECASE)
CAMPO_DE_CITACAO = re.compile(
    r"^\s*>*\s*(enviada?(\s+em)?|sent|data|date|para|to|assunto|subject|cc|cco|bcc)\s*:",
    re.IGNORECASE,
)
ESCREVEU = re.compile(r"^\s*>*\s*(em|on)\s+.{4,120}?\s(escreveu|wrote)\s*:\s*$", re.IGNORECASE)

LINHAS_DE_CONFIRMACAO = 4
"""Um `De:` sozinho não é corte — "De: acordo com o item 4" existe em português.
O corte exige um segundo campo de cabeçalho logo abaixo, e quatro linhas cobrem o
`De/Enviada/Para/Assunto` do Outlook mesmo quando um deles quebra em duas."""

# --- HTML --------------------------------------------------------------------

INVISIVEL = re.compile(r"<(script|style|head)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
QUEBRA = re.compile(r"</?(br|p|div|tr|li|h[1-6]|table)\b[^>]*>", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
ESPACOS = re.compile(r"[ \t\xa0]+")
LINHAS_VAZIAS = re.compile(r"\n\s*\n\s*\n+")


ENDERECO = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+")
REFERENCIA_EMBUTIDA = re.compile(r"(?i)\bcid:\S+")
OPACO = re.compile(r"[A-Za-z0-9+/=_%\-]{60,}")
"""Sessenta caracteres sem espaço não existem em português. Existem em token de
rastreio, em base64 de imagem embutida e em id de mensagem."""

HOSPEDEIRO = re.compile(r"(?i)^(?:https?://)?(?:www\.)?([^/\s:]+)")


def _hospedeiro(m: re.Match[str]) -> str:
    encontrado = HOSPEDEIRO.match(m.group(0))
    return f"(link: {encontrado.group(1)})" if encontrado else ""


def limpar_corpo(texto: str) -> str:
    """Tira do corpo o que é endereço, e não texto — e é o que fez este parser
    ser medido duas vezes.

    O chunker respeita um orçamento de **token**, com o tokenizador real, e uma
    URL de rastreio de 400 caracteres opacos consome a janela inteira de 512
    tokens. Medido nos cinco emails de reembolso do acervo, com o tokenizador de
    verdade: **2.931 chunks de 82 caracteres** para 61.862 caracteres de corpo —
    chunk cheio de token e vazio de conteúdo. Depois da limpeza, **25 chunks**
    para os mesmos cinco arquivos, porque 78% daquele corpo era endereço.

    Três consequências, e nenhuma é cosmética:

    1. A indexação parou de andar: 9 núcleos por dez minutos num email só, e um
       deles entrou no índice com 343 chunks antes de alguém notar.
    2. O índice ganharia milhares de vetores de lixo competindo na fusão.
    3. Contar token nesse lixo custava 33 s de chunking por documento; os 48
       arquivos inteiros agora levam 13 s de parse **mais** chunking.

    O host fica — "veio da uber.com" é sinal fraco mas real; o resto do endereço
    não é conteúdo em nenhuma leitura razoável.

    Mora aqui, e não no chunker, porque é um fato sobre **email**: PDF e DOCX
    deste acervo não carregam token de rastreio. Mudar o chunker mexeria em todos
    os formatos e pediria a medição de todos (invariante 4).
    """
    limpo = ENDERECO.sub(_hospedeiro, texto)
    limpo = REFERENCIA_EMBUTIDA.sub("", limpo)
    limpo = OPACO.sub("…", limpo)
    limpo = ESPACOS.sub(" ", limpo)
    linhas = [linha.rstrip() for linha in limpo.splitlines()]
    return LINHAS_VAZIAS.sub("\n\n", "\n".join(linhas)).strip()


def texto_de_html(bruto: str) -> str:
    """Texto de um corpo HTML, sem dependência de parser de HTML.

    Não é para renderizar página: é para tirar o texto de um email que o Outlook
    escreveu. Bloco invisível sai antes de qualquer coisa, senão folha de estilo
    entra no vetor como se fosse conteúdo.
    """
    limpo = INVISIVEL.sub(" ", bruto)
    limpo = QUEBRA.sub("\n", limpo)
    limpo = TAG.sub("", limpo)
    limpo = html.unescape(limpo)
    limpo = ESPACOS.sub(" ", limpo)
    linhas = [linha.strip() for linha in limpo.splitlines()]
    return LINHAS_VAZIAS.sub("\n\n", "\n".join(linhas)).strip()


# --- a mensagem, independente do formato de origem ----------------------------


@dataclass(frozen=True)
class Mensagem:
    """O que os dois formatos têm em comum, e tudo de que os blocos precisam."""

    assunto: str = ""
    de: str = ""
    para: str = ""
    cc: str = ""
    data: str = ""
    corpo: str = ""
    anexos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def envelope(self) -> str:
        """As linhas de cabeçalho como texto, na ordem em que se lê um email."""
        campos = (
            ("De", self.de),
            ("Para", self.para),
            ("Cc", self.cc),
            ("Data", self.data),
            ("Assunto", self.assunto),
            ("Anexos", "; ".join(self.anexos)),
        )
        return "\n".join(f"{nome}: {valor}" for nome, valor in campos if valor.strip())


def partir_thread(corpo: str) -> list[str]:
    """Uma entrada por mensagem da thread, da mais nova para a mais antiga."""
    linhas = corpo.splitlines()
    cortes: list[int] = []
    for i, linha in enumerate(linhas):
        if CORTE_ORIGINAL.match(linha) or ESCREVEU.match(linha):
            cortes.append(i)
            continue
        if ABRE_CITACAO.match(linha) and any(
            CAMPO_DE_CITACAO.match(seguinte) for seguinte in linhas[i + 1 : i + 1 + LINHAS_DE_CONFIRMACAO]
        ):
            cortes.append(i)

    fatias: list[str] = []
    inicio = 0
    for corte in cortes:
        if corte > inicio:
            fatias.append("\n".join(linhas[inicio:corte]))
        inicio = corte
    fatias.append("\n".join(linhas[inicio:]))
    return [f.strip() for f in fatias if f.strip()]


def documento_de(msg: Mensagem, nome: str, formato: str) -> ParsedDoc:
    """Blocos com o assunto na trilha — é o que sobra depois de o chunker cortar."""
    trilha = (msg.assunto,) if msg.assunto else ()
    blocos: list[Block] = []

    envelope = msg.envelope
    if envelope:
        blocos.append(Block(heading_path=trilha, text=envelope, locator="cabeçalho"))

    fatias = partir_thread(msg.corpo) if msg.corpo.strip() else []
    for n, fatia in enumerate(fatias, start=1):
        locator = "mensagem" if len(fatias) == 1 else f"mensagem {n}"
        blocos.append(Block(heading_path=trilha, text=fatia, locator=locator))

    meta = {"formato": formato}
    for chave, valor in (("assunto", msg.assunto), ("de", msg.de), ("data", msg.data)):
        if valor:
            meta[chave] = valor
    if msg.anexos:
        meta["anexos"] = str(len(msg.anexos))
    if not msg.corpo.strip():
        # Sem isto, "email sem corpo" e "email que o parser não soube ler" ficam
        # indistinguíveis no registro — e pedem coisas opostas.
        meta["suspeita"] = "sem corpo textual"

    return ParsedDoc(name=nome, blocks=tuple(blocos), meta=meta)


# --- .eml / MIME -------------------------------------------------------------


def _texto_de_parte(parte) -> str:  # noqa: ANN001 — email.message.Message
    dados = parte.get_payload(decode=True)
    if dados is None:
        return ""
    charset = parte.get_content_charset()
    if charset:
        try:
            return dados.decode(charset, errors="replace")
        except LookupError:
            pass
    return decode(dados)


def mensagem_de_mime(dados: bytes) -> Mensagem:
    """Uma `Mensagem` a partir de MIME, usando só a biblioteca padrão."""
    import email
    import email.policy
    import email.utils

    raiz = email.message_from_bytes(dados, policy=email.policy.default)

    planos: list[str] = []
    htmls: list[str] = []
    anexos: list[str] = []
    for parte in raiz.walk():
        if parte.get_content_maintype() == "multipart":
            continue
        nome_anexo = parte.get_filename()
        if nome_anexo or parte.get_content_disposition() == "attachment":
            if nome_anexo:
                anexos.append(str(nome_anexo))
            continue
        if parte.get_content_type() == "text/plain":
            planos.append(_texto_de_parte(parte))
        elif parte.get_content_type() == "text/html":
            htmls.append(texto_de_html(_texto_de_parte(parte)))

    corpo = "\n\n".join(t for t in planos if t.strip()) or "\n\n".join(t for t in htmls if t.strip())

    data = ""
    bruta = raiz.get("Date")
    if bruta:
        try:
            quando = email.utils.parsedate_to_datetime(str(bruta))
        except (TypeError, ValueError):
            data = str(bruta)
        else:
            data = quando.strftime(FORMATO_DE_DATA)

    def cabecalho(nome: str) -> str:
        valor = raiz.get(nome)
        return str(valor).strip() if valor else ""

    return Mensagem(
        assunto=cabecalho("Subject"),
        de=cabecalho("From"),
        para=cabecalho("To"),
        cc=cabecalho("Cc"),
        data=data,
        corpo=limpar_corpo(corpo),
        anexos=tuple(anexos),
    )


# --- .msg / MAPI sobre CFB ---------------------------------------------------


def streams_de_cfb(dados: bytes) -> dict[str, bytes]:
    """Todo stream do container, com o caminho achatado por `/`.

    O `olefile` cuida do container; daqui para baixo é só tabela de nomes. A
    separação existe para que a camada MAPI — que é a nossa — seja testável sem
    depender de arquivo binário real.
    """
    import olefile

    achatado: dict[str, bytes] = {}
    with olefile.OleFileIO(io.BytesIO(dados)) as ole:
        for caminho in ole.listdir(streams=True, storages=False):
            with ole.openstream(caminho) as fh:
                achatado["/".join(caminho)] = fh.read()
    return achatado


def _valor(streams: Mapping[str, bytes], caminho: str, tag: str) -> str:
    """Uma propriedade MAPI de texto, em unicode ou na codepage antiga."""
    base = f"{caminho}{PREFIXO_PROPRIEDADE}{tag}"
    em_unicode = streams.get(f"{base}{TIPO_UNICODE}")
    if em_unicode is not None:
        return em_unicode.decode("utf-16-le", errors="replace").rstrip("\x00").strip()
    for tipo in (TIPO_ANSI, TIPO_BINARIO):
        bruto = streams.get(f"{base}{tipo}")
        if bruto is not None:
            return decode(bruto).rstrip("\x00").strip()
    return ""


def _data_de_propriedades(bruto: bytes | None) -> str:
    """A data de envio, varrendo os registros de 16 bytes do stream de propriedades.

    Devolve string vazia quando nenhuma data plausível aparece — email sem data
    legível continua sendo email, e inventar uma seria pior que não ter.
    """
    if not bruto:
        return ""
    for cabecalho in CABECALHOS_DE_PROPRIEDADE:
        achadas: dict[int, dt.datetime] = {}
        for pos in range(cabecalho, len(bruto) - 15, 16):
            tipo, ident = struct.unpack_from("<HH", bruto, pos)
            if tipo != TIPO_SYSTIME or ident not in (ID_ENVIO, ID_ENTREGA):
                continue
            (ticks,) = struct.unpack_from("<Q", bruto, pos + 8)
            if not ticks:
                continue
            try:
                quando = EPOCA_FILETIME + dt.timedelta(microseconds=ticks // 10)
            except (OverflowError, OSError):
                continue
            if ANO_MINIMO <= quando.year <= ANO_MAXIMO:
                achadas.setdefault(ident, quando)
        for ident in (ID_ENVIO, ID_ENTREGA):
            if ident in achadas:
                return achadas[ident].strftime(FORMATO_DE_DATA)
    return ""


def _anexos(streams: Mapping[str, bytes]) -> tuple[str, ...]:
    """Nome de cada anexo, na ordem das sub-storages `__attach_version1.0_#N`."""
    prefixos = sorted({chave.split("/")[0] for chave in streams if chave.startswith(PREFIXO_ANEXO)})
    nomes: list[str] = []
    for prefixo in prefixos:
        for tag in (TAG_ANEXO_NOME_LONGO, TAG_ANEXO_NOME_CURTO):
            nome = _valor(streams, f"{prefixo}/", tag)
            if nome:
                nomes.append(nome)
                break
    return tuple(nomes)


def mensagem_de_streams(streams: Mapping[str, bytes]) -> Mensagem:
    """Uma `Mensagem` a partir dos streams MAPI já lidos do container."""
    corpo = _valor(streams, "", TAG_CORPO)
    if not corpo:
        corpo = texto_de_html(_valor(streams, "", TAG_CORPO_HTML))

    de = _valor(streams, "", TAG_REMETENTE) or _valor(streams, "", TAG_EM_NOME_DE)
    endereco = _valor(streams, "", TAG_REMETENTE_EMAIL)
    if endereco and endereco.lower() not in de.lower():
        de = f"{de} <{endereco}>" if de else endereco

    return Mensagem(
        assunto=_valor(streams, "", TAG_ASSUNTO),
        de=de,
        para=_valor(streams, "", TAG_PARA),
        cc=_valor(streams, "", TAG_CC),
        data=_data_de_propriedades(streams.get(STREAM_DE_PROPRIEDADES)),
        corpo=limpar_corpo(corpo),
        anexos=_anexos(streams),
    )


# --- entradas registradas ----------------------------------------------------


@register(".eml")
def parse_eml(dados: bytes, nome: str) -> ParsedDoc:
    return documento_de(mensagem_de_mime(dados), nome, "eml")


@register(".msg")
def parse_msg(dados: bytes, nome: str) -> ParsedDoc:
    return documento_de(mensagem_de_streams(streams_de_cfb(dados)), nome, "msg")
