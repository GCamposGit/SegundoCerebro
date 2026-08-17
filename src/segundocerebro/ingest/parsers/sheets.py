"""XLSX — 686 files, the second format of the corpus.

The census on the wider root promoted spreadsheets from 2% to 21,7%, so this
parser stopped being optional. The rule that matters: **one row is not one
chunk**. A row reads "4600009999 | 12/03 | 148.500,00" and means nothing on its
own. The unit is sheet + header + a window of rows, with the header repeated in
every window so each block stands alone.

`data_only=True` returns the value Excel last calculated, not the formula text.
A file never opened by Excel has no cached value and yields empty cells — that
is recorded in the metadata rather than silently producing a blank document.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

from ...logger import get_logger
from ..document import Block, BlockKind, ParsedDoc
from . import register

log = get_logger("ingest.parsers.sheets")

# Janela adaptativa. A amostra de 222 arquivos do acervo mostrou que 48
# planilhas geravam 4116 blocos contra 2684 de 100 PDFs: com janela fixa de 30
# linhas, planilha seria a maioria do índice com 21% dos arquivos, e cada
# embedding custa tempo de CPU numa máquina sem GPU.
#
# A distinção que resolve: uma aba de resumo (dezenas de linhas) é conteúdo, e
# cada faixa merece precisão. Uma aba de despejo de dados (milhares de linhas)
# é tabela: o que se precisa dela é *encontrá-la* e saber a faixa, não embutir
# cada linha num vetor. Para essas, janela grande mais um cartão de aba.
LINHAS_POR_BLOCO = 30
LINHAS_POR_BLOCO_GRANDE = 200
LIMIAR_ABA_GRANDE = 200
MAX_COLUNAS = 40
MIN_CELULAS_PARA_CABECALHO = 2
LINHAS_DE_EXEMPLO_NO_CARTAO = 2

# Aba enorme: janelar por linha é inviável e cortar em N linhas perde dados.
#
# Medido em 80 planilhas do acervo (1037 abas com dados): a mediana tem 230
# linhas e 22 colunas, mas 4,6% das abas passam de 5000 linhas e concentram
# 3,1 MILHÕES de linhas que o corte anterior descartava em silêncio. Duas abas
# batem no limite do Excel, 1.048.576 linhas.
#
# Nem janelar resolve: 3 colunas x 1 milhão de linhas ainda seriam milhares de
# chunks de uma aba só. O que se pergunta a uma exportação de dados é "esta aba
# tem o fornecedor X?", e isso se responde com o conjunto de VALORES DISTINTOS
# das colunas identificadoras — que é compacto e cobre a aba até o fim, sem
# limite de linha. O valor exato de uma célula sai depois, via read_note na
# faixa, que é o desenho da arquitetura: recuperação dá procedência, o cliente
# aprofunda.
# O digesto é completo para coluna CATEGÓRICA (três fornecedores repetidos em um
# milhão de linhas ficam totalmente cobertos) e limitado para coluna de chave
# única, onde cada linha traz um valor novo. Isso não tem solução barata: um
# milhão de identificadores distintos seriam milhares de chunks. O teto fica
# declarado no metadado do documento em vez de silencioso.
LIMIAR_ABA_ENORME = 5000

# O limiar por linha sozinho deixa passar a aba larga, e largura multiplica.
#
# Medido em 13/08/2026: uma aba de 4.279 linhas × 22 colunas ficou abaixo das
# 5.000 linhas, foi para o caminho de janelas, e produziu **3.277 chunks de um
# arquivo só** — cada linha ocupando quase todo o orçamento de 488 tokens, com o
# cabeçalho repetido comendo 40% de cada vetor. São 3.277 vetores quase
# idênticos, uma hora e meia de e5-large, e nenhuma pergunta que eles respondam
# melhor que o digesto.
#
# 20 mil células é ~4× a aba mediana do acervo (230 linhas × 22 colunas ≈ 5.000).
# Acima disso o janelamento renderia mais de cem chunks, e a lógica que já vale
# para a aba enorme passa a valer: o que se pergunta a um despejo de dados é se
# ele contém o valor X, e isso o digesto de valores distintos responde cobrindo a
# aba inteira, sem limite de linha.
LIMIAR_CELULAS_ABA_ENORME = 20_000

COLUNAS_CHAVE = 4
MAX_LINHAS_VARREDURA = 200_000
MAX_VALORES_DISTINTOS = 8000
CHARS_POR_BLOCO_DIGESTO = 2000

# Coluna de medida (dinheiro, percentual, índice) não é identificador: ninguém
# busca "9000,0". Detectada pela presença de separador decimal.
DECIMAL = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d+$|^-?\d+[.,]\d+$")
FRACAO_PARA_SER_MEDIDA = 0.3


def _formatar(valor) -> str:  # noqa: ANN001 — openpyxl devolve tipos variados
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y") if (valor.hour, valor.minute) == (0, 0) else valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _linha_util(valores: list[str]) -> bool:
    return sum(1 for v in valores if v) > 0


def _coluna(indice: int) -> str:
    """1 -> A, 27 -> AA."""
    nome = ""
    while indice > 0:
        indice, resto = divmod(indice - 1, 26)
        nome = chr(65 + resto) + nome
    return nome


def _parece_medida(valores: list[str]) -> bool:
    """True for a money/percentage/index column — not an identifier."""
    if not valores:
        return False
    decimais = sum(1 for v in valores if DECIMAL.match(v))
    return decimais / len(valores) > FRACAO_PARA_SER_MEDIDA


def _e_aba_alta(aba) -> bool:  # noqa: ANN001
    """Altura declarada no XML da planilha, quando dá para confiar nela.

    Atalho para não materializar 200 mil linhas: se a aba se declara altíssima,
    vai direto para o digesto. `max_row` vem do elemento `<dimension>` e em
    `read_only` pode faltar ou vir errado, então serve como gatilho para o caso
    fácil e **nunca** como garantia de que a aba é pequena — a área é conferida
    depois, com as linhas na mão.
    """
    return (aba.max_row or 0) > LIMIAR_ABA_ENORME


def _e_despejo_de_dados(linhas: list[tuple[int, list[str]]]) -> bool:
    """Área real, contada nas linhas já lidas.

    Altura e área falham em casos diferentes, e os dois existem no acervo: 200
    mil linhas em 3 colunas estoura a altura; 4.279 linhas em 22 colunas não
    estoura a altura e estoura a área. Esta é a segunda checagem, a que não
    depende de metadado — medida porque `max_row` e `max_column` em `read_only`
    não são confiáveis, e a aba de 94 mil células passou batido pelo gatilho de
    altura.
    """
    if not linhas:
        return False
    colunas = max(len(v) for _, v in linhas)
    return len(linhas) * min(colunas, MAX_COLUNAS) > LIMIAR_CELULAS_ABA_ENORME


def _blocos_de_digesto(  # noqa: ANN001
    titulo: str, linhas_formatadas, blocos: list[Block], truncadas: list[str], parciais: list[str]
) -> None:
    """Digest of distinct values in the identifying columns, covering every row.

    Indexes the first columns down to the end of the sheet instead of capping
    rows — the cap silently dropped 3,1 million rows across the corpus.

    Recebe linhas **já formatadas** para servir aos dois chamadores: a aba alta,
    que entrega um gerador e nunca materializa o conteúdo, e a aba larga, cujas
    linhas já estão em memória porque foi preciso lê-las para descobrir a área.
    """
    cabecalho: list[str] = []
    distintos: dict[int, dict[str, None]] = {}
    linhas_uteis = 0

    for numero, valores in enumerate(linhas_formatadas, start=1):
        if numero > MAX_LINHAS_VARREDURA:
            truncadas.append(titulo)
            break
        if not _linha_util(valores):
            continue

        if not cabecalho and sum(1 for v in valores if v) >= MIN_CELULAS_PARA_CABECALHO:
            cabecalho = valores
            # colunas identificadoras: as primeiras com cabeçalho preenchido
            chaves = [i for i, v in enumerate(valores) if v][:COLUNAS_CHAVE]
            distintos = {i: {} for i in chaves}
            continue

        linhas_uteis += 1
        for i in distintos:
            if i < len(valores) and valores[i] and len(distintos[i]) < MAX_VALORES_DISTINTOS:
                distintos[i][valores[i]] = None

    if not cabecalho:
        return

    titulo_cabecalho = " | ".join(c for c in cabecalho if c)
    blocos.append(
        Block(
            heading_path=(titulo,),
            text=(
                f"Aba '{titulo}' com {linhas_uteis} linhas de dados "
                f"e {sum(1 for c in cabecalho if c)} colunas.\n"
                f"Colunas: {titulo_cabecalho}"
            ),
            locator=f"{titulo} (resumo da aba)",
            kind=BlockKind.SHEET,
        )
    )

    for indice, valores in distintos.items():
        if not valores:
            continue
        rotulo = cabecalho[indice] or _coluna(indice + 1)
        lista = list(valores)
        if _parece_medida(lista[:200]):
            continue
        if len(lista) >= MAX_VALORES_DISTINTOS:
            parciais.append(f"{titulo}!{_coluna(indice + 1)} ({MAX_VALORES_DISTINTOS} de {linhas_uteis}+)")
        pedacos: list[list[str]] = [[]]
        tamanho = 0
        for valor in lista:
            if tamanho + len(valor) > CHARS_POR_BLOCO_DIGESTO and pedacos[-1]:
                pedacos.append([])
                tamanho = 0
            pedacos[-1].append(valor)
            tamanho += len(valor) + 3
        for i, pedaco in enumerate(pedacos, start=1):
            sufixo = f" {i}/{len(pedacos)}" if len(pedacos) > 1 else ""
            blocos.append(
                Block(
                    heading_path=(titulo, rotulo),
                    text=(
                        f"Valores distintos na coluna '{rotulo}' "
                        f"(coluna {_coluna(indice + 1)}, {len(lista)} valores):\n"
                        + " · ".join(pedaco)
                    ),
                    locator=f"{titulo}!{_coluna(indice + 1)} (valores distintos{sufixo})",
                    kind=BlockKind.SHEET,
                )
            )


VALIDACOES = re.compile(
    rb"<(?:\w+:)?dataValidations\b.*?</(?:\w+:)?dataValidations>"
    rb"|<(?:\w+:)?dataValidations\b[^>]*/>",
    re.DOTALL,
)
"""`<dataValidations>` de uma aba, com ou sem prefixo de namespace.

Regex sobre XML é ruim em geral e aceitável aqui: o alvo é um bloco fechado,
gerado por máquina, e o conteúdo não é indexado — só precisa sair do caminho.
"""


def _sem_validacoes(dados: bytes) -> bytes | None:
    """Reescreve a pasta de trabalho sem validações. `None` se não havia nenhuma.

    Motivo, medido em 15/08/2026 sobre 3 arquivos do acervo: o openpyxl recusa
    `sqref="I:I"` — validação sobre a coluna inteira — com
    `TypeError: expected MultiCellRange`, porque o `CellRange` dele exige faixa
    com linhas. `I:I` é OOXML válido e o Excel o produz; quem gerou estes
    arquivos usa prefixo de namespace explícito (`<x:dataValidation>`), o que
    não muda nada para o openpyxl e muda tudo para quem procura no XML.

    A falha acontece no parse **preguiçoso** da aba, não em `load_workbook` — por
    isso não adianta proteger só a abertura, e por isso a nova tentativa
    reescreve os bytes em vez de trocar parâmetro.
    """
    import zipfile

    with zipfile.ZipFile(io.BytesIO(dados)) as zin:
        alterados: dict[str, bytes] = {}
        for nome in zin.namelist():
            if not (nome.startswith("xl/worksheets/") and nome.endswith(".xml")):
                continue
            bruto = zin.read(nome)
            limpo = VALIDACOES.sub(b"", bruto)
            if limpo != bruto:
                alterados[nome] = limpo
        if not alterados:
            return None

        saida = io.BytesIO()
        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                conteudo = alterados[item.filename] if item.filename in alterados else zin.read(item.filename)
                zout.writestr(item.filename, conteudo)
    return saida.getvalue()


@register(".xlsx", ".xlsm")
def parse_xlsx(dados: bytes, nome: str) -> ParsedDoc:
    """Uma nova tentativa sem validações, e só para a falha que ela resolve."""
    try:
        return _parse_xlsx(dados, nome)
    except TypeError as exc:
        if "MultiCellRange" not in str(exc):
            raise
        limpo = _sem_validacoes(dados)
        if limpo is None:
            raise
        log.info("%s: validações de dados removidas para contornar o openpyxl", nome)
        return _parse_xlsx(limpo, nome)


def _parse_xlsx(dados: bytes, nome: str) -> ParsedDoc:
    import openpyxl

    livro = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
    blocos: list[Block] = []
    abas_truncadas: list[str] = []
    abas_em_digesto: list[str] = []
    digestos_parciais: list[str] = []

    try:
        for aba in livro.worksheets:
            if _e_aba_alta(aba):
                abas_em_digesto.append(aba.title)
                _blocos_de_digesto(
                    aba.title,
                    ([_formatar(c) for c in linha[:MAX_COLUNAS]] for linha in aba.iter_rows(values_only=True)),
                    blocos,
                    abas_truncadas,
                    digestos_parciais,
                )
                continue

            linhas: list[tuple[int, list[str]]] = []
            for numero, linha in enumerate(aba.iter_rows(values_only=True), start=1):
                valores = [_formatar(c) for c in linha[:MAX_COLUNAS]]
                if _linha_util(valores):
                    linhas.append((numero, valores))

            if not linhas:
                continue

            # Segunda checagem, agora com a área real: `max_row` em `read_only`
            # não é confiável, e a aba de 4.279×22 passou batido pelo gatilho de
            # altura. Janelá-la renderia milhares de chunks quase idênticos.
            if _e_despejo_de_dados(linhas):
                abas_em_digesto.append(aba.title)
                _blocos_de_digesto(
                    aba.title, (v for _, v in linhas), blocos, abas_truncadas, digestos_parciais
                )
                continue

            # cabeçalho: primeira linha com pelo menos duas células preenchidas
            indice_cabecalho = next(
                (i for i, (_, v) in enumerate(linhas) if sum(1 for x in v if x) >= MIN_CELULAS_PARA_CABECALHO),
                None,
            )
            if indice_cabecalho is None:
                cabecalho: list[str] = []
                corpo = linhas
            else:
                cabecalho = [c for c in linhas[indice_cabecalho][1] if c]
                corpo = linhas[indice_cabecalho + 1 :]

            titulo_cabecalho = " | ".join(cabecalho)
            largura = _coluna(max((len(v) for _, v in linhas), default=1))

            if not corpo and cabecalho:
                blocos.append(
                    Block(
                        heading_path=(aba.title,),
                        text=titulo_cabecalho,
                        locator=f"{aba.title}!A{linhas[indice_cabecalho][0]}",
                        kind=BlockKind.SHEET,
                    )
                )
                continue

            aba_grande = len(corpo) > LIMIAR_ABA_GRANDE
            passo = LINHAS_POR_BLOCO_GRANDE if aba_grande else LINHAS_POR_BLOCO

            if aba_grande:
                # cartão da aba: o que permite achar a planilha sem indexar cada linha
                exemplos = "\n".join(
                    " | ".join(v).rstrip(" |") for _, v in corpo[:LINHAS_DE_EXEMPLO_NO_CARTAO]
                )
                cartao = (
                    f"Aba '{aba.title}' com {len(corpo)} linhas de dados.\n"
                    f"Colunas: {titulo_cabecalho}\n"
                    f"Primeiras linhas:\n{exemplos}"
                )
                blocos.append(
                    Block(
                        heading_path=(aba.title,),
                        text=cartao,
                        locator=f"{aba.title} (resumo da aba)",
                        kind=BlockKind.SHEET,
                    )
                )

            for inicio in range(0, len(corpo), passo):
                janela = corpo[inicio : inicio + passo]
                corpo_texto = "\n".join(" | ".join(v).rstrip(" |") for _, v in janela)
                texto = f"{titulo_cabecalho}\n{corpo_texto}" if titulo_cabecalho else corpo_texto
                primeira, ultima = janela[0][0], janela[-1][0]
                blocos.append(
                    Block(
                        heading_path=(aba.title,),
                        text=texto.strip(),
                        locator=f"{aba.title}!A{primeira}:{largura}{ultima}",
                        kind=BlockKind.SHEET,
                    )
                )
    finally:
        livro.close()

    meta = {"formato": "xlsx", "abas": str(len(livro.sheetnames))}
    if abas_em_digesto:
        meta["abas_em_digesto"] = ", ".join(sorted(set(abas_em_digesto)))
    if digestos_parciais:
        # cobertura incompleta declarada: coluna de chave única não cabe inteira
        meta["digesto_parcial"] = ", ".join(sorted(set(digestos_parciais)))
    if abas_truncadas:
        meta["truncadas"] = ", ".join(sorted(set(abas_truncadas)))
    if not blocos:
        # sem valor em cache: a planilha nunca foi aberta pelo Excel depois de gerada
        meta["aviso"] = "nenhum valor calculado em cache"
    return ParsedDoc(name=nome, blocks=tuple(blocos), meta=meta)
