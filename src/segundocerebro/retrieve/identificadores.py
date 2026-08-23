"""Extração de identificadores citados no texto — o insumo do grafo derivado.

    "conforme a ISO 42001 e o contrato CT-VCE-2024-0142"
    -> [("norma", "ISO 42001"), ("codigo", "CT-VCE-2024-0142")]

Existe porque este acervo não tem wikilink nenhum (`CLAUDE.md`): a única ligação
explícita entre dois documentos é o identificador que os dois citam. Um plano de
ação que termina em "certificação ISO 42001" e a norma ISO 42001, em outra pasta,
não têm nada em comum — nem nome, nem pasta, nem vocabulário — **exceto** esse
identificador. É a aresta que `ARCHITECTURE.md` §"Grafo derivado" descreve, e o
que a `neighbors` anda.

## Precisão vale mais que cobertura aqui, e a assimetria é grande

Uma aresta falsa é pior que uma aresta ausente. Ausente, o cliente não encontra o
documento e segue buscando; falsa, ele recebe um documento **com procedência
correta** ligado por um motivo inventado, e não tem como desconfiar — a
procedência é verdadeira, a relação é que não é. Por isso cada padrão aqui exige
estrutura suficiente para não casar por acidente, e o que está em dúvida fica
fora com o motivo registrado (ver `NAO_EXTRAIDOS`).

## Por que estes padrões e não um extrator genérico

A ablação do glossário (`docs/ablacao-f2.md`) ensinou que vocabulário genérico
mediu **zero** e o específico da empresa pagou o ganho inteiro. A tentação seria
concluir que identificador genérico também não paga. Não é o mesmo caso, e a
diferença importa:

- O genérico que falhou lá era mês abreviado — resolvia um descasamento que
  **não era gargalo**, porque os outros ranqueadores já achavam aqueles
  documentos.
- `ISO 42001` citado em dois documentos é uma ligação real em **qualquer**
  acervo, e é uma ligação que nenhum ranqueador desta pilha produz hoje.

O que generaliza é a **forma** do identificador (norma, lei, código
estruturado), não o vocabulário dele. Daí os padrões serem estruturais. O que é
específico da empresa continua vindo de onde já vinha: o glossário que o usuário
constrói (`glossario.py`), usado como fonte de entidade em `grafo.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..logger import get_logger

log = get_logger("retrieve.identificadores")


@dataclass(frozen=True)
class Identificador:
    """Um identificador citado, já normalizado para comparação.

    `tipo` separa espaços de nomeação que não devem se confundir: a lei 42.001 e
    a norma ISO 42001 têm o mesmo número e nada a ver uma com a outra. Sem o
    tipo, seriam a mesma aresta.
    """

    tipo: str
    valor: str
    """Forma canônica, para casar entre documentos que escrevem diferente."""


# `\b` antes de letra maiúscula não basta: em "aISO" o `\b` não existe, mas em
# "da ISO" existe — o que separa os dois casos é exigir início de palavra de
# verdade, e é o que `(?<![0-9A-Za-zÀ-ÿ])` faz. Usar lookbehind em vez de `\b`
# porque `\b` trata acento como fronteira, e "à ISO" tem acento colado.
INICIO = r"(?<![0-9A-Za-zÀ-ÿ])"
FIM = r"(?![0-9A-Za-zÀ-ÿ])"

PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # --- normas técnicas -----------------------------------------------------
    # `ISO 42001`, `ISO/IEC 27001`, `ABNT NBR 14001`, `NBR ISO 9001`, `NR 12`.
    # O corpo é obrigatório e numérico: `ISO` sozinho é sigla, não identificador
    # de norma, e casá-lo ligaria todo documento que menciona a palavra.
    (
        "norma",
        re.compile(
            INICIO
            # `ABNT NBR ISO 9001`, `NBR ISO 9001`, `NBR 14001` e `ISO 9001` são
            # todas grafias válidas, e `NBR` é organismo por si — não só prefixo
            # de ISO. Deixá-lo apenas como prefixo opcional fazia `NBR 14001`
            # não casar, e uma norma ABNT sem ISO é comum em acervo de engenharia.
            + r"(?:ABNT\s+)?(?:NBR\s+)?(?:ISO(?:/IEC|/TS|/TR)?|IEC|NBR|NR|ASTM|EN)"
            # Até 9 dígitos, e não 6, por causa do ano colado: `ISO-420012023` é
            # `42001` + `2023` sem separador, forma que este acervo usa em nome de
            # arquivo. Com o teto em 6 a expressão **falhava inteira** ali — o
            # backtracking tentava 6, 5, 4 dígitos e a fronteira `FIM` recusava
            # todos, porque sempre sobrava dígito depois. `_numero_de_norma`
            # devolve o número sem o ano.
            # `(?:\.\d{3})*` porque `ISO 14.001` existe no acervo e, sem isso, a
            # expressão casava só o `14` — a fronteira aceitava o ponto — e
            # produzia `ISO 14`, que não liga com `ISO 14001`. Medido: 15
            # documentos ficaram órfãos por causa disso.
            r"[\s/-]{0,3}(\d{2,9}(?:\.\d{3})*(?:[-:]\d{1,4})?)" + FIM,
            re.IGNORECASE,
        ),
    ),
    # --- leis, projetos de lei, decretos, resoluções -------------------------
    # `Lei 14.133/2021`, `PL 2338/2023`, `Decreto 10.278/2020`, `Lei nº 13.709`.
    # O ano depois da barra é o que dá confiança; sem barra, exige o ponto de
    # milhar (`14.133`), senão "Lei 5" viraria identificador.
    (
        "lei",
        re.compile(
            INICIO + r"(?:Lei(?:\s+Complementar)?|PL|PLP|Decreto|Resolu[çc][ãa]o|Portaria|MP)"
            r"(?:\s+n[º°.]?)?\s*(\d{1,3}(?:\.\d{3})+(?:/\d{4})?|\d{2,6}/\d{4})" + FIM,
            re.IGNORECASE,
        ),
    ),
    # --- códigos estruturados de documento e contrato ------------------------
    # `PO-VCE-007`, `CT-VCE-2024-0142`, `MA-VCE-001`, `NN-VCE-450.2025`.
    # Três blocos separados por hífen, o último numérico. Dois blocos só
    # (`VCE-007`) ficam fora: casariam `covid-19`, `escopo-3` e qualquer
    # palavra-número, que é justamente o ruído que uma aresta falsa produz.
    (
        "codigo",
        re.compile(
            INICIO + r"([A-Z]{2,4}-[A-Z0-9]{2,8}-\d{1,4}(?:[.\-/]\d{1,4})?)" + FIM,
        ),
    ),
    # --- CNPJ ----------------------------------------------------------------
    # Formatado, com pontuação. Sem a pontuação seriam 14 dígitos soltos, que num
    # acervo com planilhas casam valor financeiro e número de série.
    (
        "cnpj",
        re.compile(INICIO + r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})" + FIM),
    ),
    # --- processo administrativo / judicial ----------------------------------
    # Padrão CNJ: `0001234-56.2023.8.26.0100`. Estrutura rígida o bastante para
    # não haver dúvida.
    (
        "processo",
        re.compile(INICIO + r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})" + FIM),
    ),
)

NAO_EXTRAIDOS = """Padrões deliberadamente fora, e o motivo de cada um.

Ficam registrados porque a próxima pessoa vai propor exatamente estes, e o
argumento contra é medição, não gosto:

- **Número puro longo** (ex.: um número de pedido de dez dígitos do ERP). Num acervo com 686
  planilhas, dez dígitos casam valor, CEP concatenado, número de série e código
  de barras. Precisão baixa e sem como distinguir sem contexto.
- **Código de dois blocos** (`VCE-007`, `CT-0142`). Casa `covid-19`,
  `escopo-3`, `top-10`. O terceiro bloco é o que separa identificador de
  palavra-hifenizada.
- **Nome de pessoa e organização por NER.** Exigiria modelo, e modelo no caminho
  de indexação é custo que a invariante 1 não paga de graça. A fonte de entidade
  do grafo é o glossário que o usuário já constrói — específico, curado, e
  medido como o que paga (`docs/ablacao-f2.md`).
- **Data.** Toda data casa em todo documento; ligaria o acervo inteiro. A
  dimensão temporal do grafo, se entrar, vem de `mtime`, não do texto.
"""


ANO = re.compile(r"(19|20)\d{2}$")

PROMULGADAS = frozenset({"LEI", "DECRETO", "PORTARIA", "RESOLUCAO", "RESOLUÇÃO"})
"""Espécies cuja numeração é única — o ano citado junto é redundante.

Fora daqui ficam `PL`, `PLP` e `MP`: a numeração de proposta reinicia a cada ano,
então o ano é parte da identidade e não pode ser descartado."""


def _numero_de_norma(numero: str) -> str:
    """Número da norma sem a edição — e sem o ano colado.

    Duas coisas, as duas medidas no acervo real em 20/08/2026:

    **A edição sai.** `ISO 42001:2023` e `ISO 42001` são a mesma norma citada com
    e sem o ano de publicação, e produziam identificadores diferentes — ou seja,
    dois documentos que falam da mesma norma **não se ligavam**. Para aresta, a
    edição não importa: `ISO 27001:2013` e `ISO 27001:2022` são vintages do mesmo
    padrão, e ligar os dois é certo.

    **O ano colado também sai.** A convenção de nome deste acervo produz
    `ISO-420012023_-Web.pdf`, e `420012023` é `42001` seguido de `2023` sem
    separador — anotado no conjunto dourado como caso real. Sem tratar, o número
    ficaria truncado em `420012` pela gulodice do quantificador, o que é pior que
    não extrair: um identificador que não existe em documento nenhum.

    O corte só acontece quando o resto tem tamanho de número de norma (4 ou 5
    dígitos). `1234` sozinho não é interpretado como `12` + ano.
    """
    # O ponto é separador de milhar aqui (`ISO 14.001`), nunca parte do número.
    numero = numero.split(":")[0].split("-")[0].replace(".", "")
    if len(numero) in (8, 9) and ANO.search(numero):
        return numero[: len(numero) - 4]
    return numero


def _canonico(tipo: str, bruto: str) -> str:
    """Forma comparável entre documentos que escrevem o mesmo id diferente.

    `ISO 42001`, `iso/iec 42001` e `ISO-42001` são o mesmo identificador e têm
    que produzir a mesma aresta. Só o que é ruído de escrita cai: caixa,
    separador e o `nº`. O número **nunca** é normalizado — `14.133` e `14133`
    ficam distintos porque não há garantia de que o ponto seja milhar.
    """
    texto = " ".join(bruto.split())
    if tipo == "norma":
        # Preserva o organismo (ISO, NBR, NR) e junta com um espaço só: é o
        # organismo + número que identifica, não a pontuação entre eles.
        partes = re.split(r"[\s/-]+", texto)
        organismos = [p.upper() for p in partes if not p[:1].isdigit()]
        numeros = [p for p in partes if p[:1].isdigit()]
        # `ABNT NBR ISO 9001` e `ISO 9001` são a mesma norma citada com mais ou
        # menos formalidade; ficar só com o organismo mais específico é o que faz
        # as duas grafias casarem. ISO/IEC vira ISO pelo mesmo motivo.
        principal = next(
            (o for o in ("ISO", "IEC", "NBR", "NR", "ASTM", "EN") if o in organismos),
            organismos[-1] if organismos else "",
        )
        if not numeros:
            return principal
        return f"{principal} {_numero_de_norma(numeros[0])}"
    if tipo == "lei":
        especie, numero = texto.split(None, 1) if " " in texto else (texto, "")
        numero = numero.replace("nº", "").replace("n°", "").replace("n.", "").strip()
        especie = especie.upper()
        # Norma **promulgada** tem numeração única e o ano é decoração: a LGPD é
        # a `Lei 13.709` tanto quanto a `Lei 13.709/2018`, e manter o ano partia
        # a mesma lei em dois identificadores que não se ligavam — medido em 40 e
        # 15 documentos, no acervo real.
        #
        # **Projeto** de lei é o contrário: a numeração reinicia a cada ano, e
        # `PL 2338/2023` e `PL 2338/2019` são propostas diferentes. Aqui o ano é
        # identidade, e descartá-lo criaria aresta falsa entre textos sem
        # relação. A regra segue a numeração legislativa, não a conveniência.
        if especie in PROMULGADAS:
            numero = numero.split("/")[0]
        return f"{especie} {numero}".strip()
    if tipo == "codigo":
        return texto.upper()
    return texto


def extrair(texto: str, *, limite: int = 40) -> list[Identificador]:
    """Identificadores citados em `texto`, sem repetição e em ordem de aparição.

    `limite` existe porque um chunk patológico — sumário de norma, tabela de
    contratos — cita dezenas de identificadores, e cada um deles viraria aresta
    para todo documento do acervo que os cite. Um chunk que menciona 40
    identificadores não está *falando sobre* nenhum deles; está listando. Cortar
    é mais honesto que produzir centenas de arestas fracas.
    """
    if not texto:
        return []
    vistos: dict[tuple[str, str], None] = {}
    for tipo, padrao in PADROES:
        for achado in padrao.finditer(texto):
            valor = _canonico(tipo, achado.group(0))
            if not valor:
                continue
            vistos.setdefault((tipo, valor), None)
            if len(vistos) >= limite:
                log.debug("chunk com mais de %d identificadores — cortado", limite)
                return [Identificador(t, v) for t, v in vistos]
    return [Identificador(t, v) for t, v in vistos]
