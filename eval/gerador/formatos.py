"""Uma pergunta por parser registrado — cobertura garantida, não sorteada.

## Por que uma fatia própria, e não peso no `picker`

A distribuição do censo (`nucleo.DISTRIBUICAO_DO_CENSO`) serve ao **realismo**: um
corpus 80% `.txt` mede um caminho de código que o produto quase não usa. Mas
realismo é distribuição, e distribuição não garante cobertura — `.pptm` são 3
arquivos em 3.156 no acervo real, 0,1%, e num corpus de 200 documentos isso
arredonda para zero na metade das seeds.

**Parser não exercitado é ponto cego**, e ponto cego não escala com `n`. Então a
cobertura é garantida aqui, um documento por extensão registrada, e o `picker`
continua cuidando do realismo. Os dois papéis são diferentes e ficam separados.

A lista **não é escrita à mão**: sai de `parsers.supported_extensions()`, que é o
que o indexador consulta. `tests/test_formatos.py` confere os dois conjuntos —
**parser novo sem fixture reprova**, e quem registrou o parser descobre no mesmo
dia em vez de o corpus ficar cego por uma fase inteira.

## O que cada extensão custou para gerar, medido em 25/08/2026

| Extensão | Como | Resultado |
|---|---|---|
| `.docx` `.docm` | `python-docx`, extensão trocada | lê, marca encontrada |
| `.xlsx` `.xlsm` | `openpyxl` | lê |
| `.pptx` `.pptm` | `python-pptx` | lê |
| `.pdf` | `pymupdf` | lê |
| `.txt` `.csv` `.md` `.markdown` `.rtf` | texto | lê |
| `.eml` | `email` da stdlib | lê |
| **`.msg`** | `cfb.msg_de` — CFB com streams MAPI | lê, 2 blocos |
| **`.doc` `.ppt`** | `cfb.escrever_cfb` com o stream do formato | lê via `ole_texto` |
| **`.xls`** | — | **não se gera aqui**, ver abaixo |

**`.xls` válido fica de fora, e é declarado.** O parser é o `xlrd`, que exige BIFF
de verdade; um CFB com um stream `Workbook` inventado morre com
`XLRDError: Expected BOF record`. Escrever BIFF exigiria `xlwt`, que não é
dependência do projeto e não vale uma para gerar fixture. O `.xls` aparece no
corpus em duas formas **hostis**, que são as que o `F4-L` persegue: o CFB que o
`xlrd` recusa e o HTML com extensão trocada (`hostil.py`). A lacuna declarada é a
única que não vira dívida.
"""

from __future__ import annotations

from . import vocabulario as V
from .cfb import escrever_cfb, msg_de
from .nucleo import Doc, mkdoc, moeda, perg
from .transcricao import POR_EXTENSAO, falas_de

PASTA = "11. Formatos"

SO_HOSTIL = {".xls"}
"""Extensões que o corpus só tem em forma hostil, com o motivo no módulo.

Conferido em teste contra `supported_extensions()`: tirar uma daqui sem
acrescentar a fixture reprova, e acrescentar uma sem motivo escrito também."""

VIA_PICKER = {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx", ".pptx"}
"""Já garantidas pela distribuição do censo — mas ganham fixture aqui do mesmo
jeito. Custa um documento e tira a cobertura da mão do sorteio."""

STREAM_OLE = {".doc": "WordDocument", ".ppt": "PowerPoint Document"}
"""Onde o texto mora dentro do container OLE de cada formato legado."""


def _corpo(rng, cid: str, valor: int) -> str:
    return (
        f"REGISTRO {cid}\n"
        f"Contratada: {rng.choice(V.EMPRESAS)}.\n"
        f"Objeto: {rng.choice(V.SERVICOS)} em {rng.choice(V.CIDADES)}.\n"
        f"Valor total: {moeda(valor)}.\n"
    )


def _documento(rng, extensao: str, cid: str, valor: int):
    """O documento daquela extensão, no formato que o parser dela espera."""
    texto = _corpo(rng, cid, valor)
    nome = f"Registro {cid}"

    if extensao == ".msg":
        # `.msg` é 3,5% do acervo real (110 arquivos) e o corpus não tinha
        # nenhum: a fatia de email usava `.eml`, que lá é 0%.
        bytes_msg = msg_de(
            assunto="RES: ENC: registro",
            de="Arquivo", email_de="arquivo@vce.example", para="juridico@vce.example",
            corpo=texto,
        )
        return Doc(f"{PASTA}/{nome}.msg", bytes_msg.decode("latin-1"), formato="cfb_pronto")

    if extensao in STREAM_OLE:
        bruto = escrever_cfb({STREAM_OLE[extensao]: texto.encode("utf-16-le")})
        return Doc(f"{PASTA}/{nome}{extensao}", bruto.decode("latin-1"), formato="cfb_pronto")

    if extensao in POR_EXTENSAO:
        # Prosa dentro de um `.srt` nao tem marca de tempo, e o parser de
        # transcricao devolve **vazio**: o documento entraria no corpus sem chunk
        # e a pergunta apontaria para nada -- que e o defeito que o `F4-T` acabou
        # de fechar. O corpo vira cue.
        return mkdoc(PASTA, nome, POR_EXTENSAO[extensao](falas_de(texto)), extensao.lstrip("."))

    return mkdoc(PASTA, nome, texto, extensao.lstrip("."))


def f_formatos(rng, n, ext):
    """Um documento e uma pergunta por extensão que o produto sabe ler.

    Não escala com `n` pelo mesmo motivo da pasta hostil: um documento prova que
    o parser é exercitado, e trinta cópias só encarecem a passada.
    """
    from segundocerebro.ingest.parsers import supported_extensions

    docs, ps = [], []
    for i, extensao in enumerate(sorted(supported_extensions())):
        if extensao in SO_HOSTIL:
            continue
        cid = f"CT-FT-{i:03d}"
        valor = rng.randrange(90, 9500) * 1000
        documento = _documento(rng, extensao, cid, valor)
        docs.append(documento)
        ps.append(perg(
            f"q-ft-{i:03d}", "formatos",
            f"Qual o valor total do registro {cid}?", moeda(valor),
            [documento.caminho],
            armadilha=f"o conteudo so existe dentro de um {extensao}",
            feature_alvo=f"parser {extensao}",
        ))
    return docs, ps
