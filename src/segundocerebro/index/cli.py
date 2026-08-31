"""A superfície de linha de comando do indexador — só as flags e o que as lê.

    py -m segundocerebro.index.indexer --base <id> --perfil normal

Saiu de `indexer.py` em 29/08/2026, e é o corte mais barato daquele arquivo: 124
das suas 1.753 linhas eram `add_argument`, e elas mudam por um motivo — a
interface de quem chama — que não tem nada a ver com o motivo pelo qual o laço de
indexação muda.

`main()` **fica** em `indexer.py`, de propósito. Ele é o `[project.scripts]`
`segundocerebro-indexar`, e mover o ponto de entrada obrigaria quem já instalou a
reinstalar para o comando voltar a existir — que é exatamente o degrau da `F6`
que este projeto não pode quebrar por arrumação.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import LimitesDeIndexacao
from .embeddings import MODELOS
from .esforco import PERFIS_DE_ESFORCO
from .orcamento import PRESETS_LEIGO

LIMITE_CHUNKS_PADRAO = 800
"""Safety net for `.txt` that sneak under the byte cap and still explode.

~800 chunks × 1 800 chars is about 1,4 MB of text — a long report, not a dump.
CSV left this cap in C7.d (digest, not hundreds of blobs). Does not apply to
PDF/DOCX/PPTX: those are the knowledge formats, and a cap here would silently
drop timetable-style PDFs on a rebuild."""

LIMITE_TEXTO_MB_PADRAO = LimitesDeIndexacao().txt
"""Espelho de `LimitesDeIndexacao.txt`. A fonte é a config; isto documenta o CLI."""


def _extensoes(bruto: str | None) -> frozenset[str] | None:
    """`.txt,pdf` -> `{'.txt', '.pdf'}`. O ponto é opcional, porque digitar sem ele
    é o erro que a pessoa comete e recusar seria pedantismo."""
    if not bruto:
        return None
    itens = {p.strip().lower() for p in bruto.split(",") if p.strip()}
    return frozenset(e if e.startswith(".") else f".{e}" for e in itens) or None


def _limites_efetivos(
    limites: LimitesDeIndexacao,
    pular_texto_acima_de: float | None,
) -> dict[str, float]:
    """Mapa extensão → MB. A flag de CLI, se vier, só cobre .txt (C7.d)."""
    mapa = dict(limites.como_mapa())
    if pular_texto_acima_de is None:
        return mapa
    if pular_texto_acima_de <= 0:
        mapa.pop(".txt", None)
        return mapa
    mapa[".txt"] = pular_texto_acima_de
    return mapa


def construir_parser() -> argparse.ArgumentParser:
    """As flags do indexador. Uma função, para `main()` caber na tela."""
    parser = argparse.ArgumentParser(prog="segundocerebro.index.indexer")
    parser.add_argument("--base", help="qual base indexar (ver config.toml)")
    parser.add_argument(
        "--config",
        type=Path,
        help="arquivo de configuração; aceita config.toml e o census.toml legado. "
        "Ausente: procura config.toml, depois census.toml",
    )
    # As sobreposições abaixo têm default None de propósito: `None` é "a base
    # decide", e um default concreto aqui venceria silenciosamente o arquivo.
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", choices=sorted(MODELOS), help="sobrepõe o modelo da base")
    parser.add_argument("--limite", type=int, help="para depois de N documentos processados")
    parser.add_argument("--max-chars", type=int, help="sobrepõe o chunking da base")
    parser.add_argument("--threads", type=int, help="sobrepõe as threads da máquina")
    parser.add_argument(
        "--perfil",
        choices=(*PERFIS_DE_ESFORCO, *PRESETS_LEIGO),
        help="nível de esforço; sobrepõe o [maquina] perfil. Presets do leigo: "
        "automatico (cede ao usuário), noturno (tudo), discreto (mínimo). "
        "'leve' recusa rodar na bateria",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="R1.2: depois das ondas de texto, OCR nos PDF digitalizados. "
        "Exige o extra [ocr] (RapidOCR) ou Tesseract. Sem motor a passada "
        "é idêntica à de hoje",
    )
    parser.add_argument(
        "--dois-passes",
        action="store_true",
        dest="dois_passes",
        help="R3.2: parse+FTS primeiro (busca útil no mesmo dia) e embed depois. "
        "O índice final é o mesmo de uma passada só",
    )
    parser.add_argument(
        "--modelo-rascunho",
        choices=sorted(MODELOS),
        dest="modelo_rascunho",
        help="liga dois passes. MiniLM não cabe na tabela do e5-large (384d vs 1024d); "
        "o rascunho nesses casos é lexical",
    )
    parser.add_argument(
        "--parse-workers",
        type=int,
        dest="parse_workers",
        help="threads de parse. Padrão: 1 na CPU, metade dos núcleos (2–8) com "
        "SEGUNDOCEREBRO_PROVIDER=cuda. Com 2+ GPUs o embed sai da principal "
        "(um processo por placa); senão fica na thread principal",
    )
    parser.add_argument("--prefixo", help="indexa só caminhos que começam com este prefixo")
    parser.add_argument(
        "--so-extensao",
        dest="so_extensao",
        metavar=".txt,.pdf",
        help="indexa só estas extensões, separadas por vírgula. Recorta na **enumeração**: "
        "o que fica fora não é aberto nem registrado — é diferente de "
        "--pular-texto-acima-de e --pular-acima-de-n-chunks, que abrem, medem e adiam. "
        "Existe para partir uma passada por custo: em Meetings/ os 188 .pdf custam de 5 a "
        "11 h e trazem renderizado o que os .txt já trazem em texto, e medir entre as duas "
        "metades vale mais que descobrir depois. "
        "Desliga a reconciliação — o recorte não é evidência de que o resto sumiu",
    )
    parser.add_argument(
        "--pular-planilha-acima-de",
        type=float,
        metavar="MB",
        help="adia planilhas cujo XML de abas passe deste tamanho, em MB. O preditor é o XML "
        "descompactado, não o tamanho em disco: 17,9 MB comprimidos podem esconder 124 MB em 69 "
        "abas e custar duas horas. Fica registrado como `adiado` e é repescado numa passada sem o limite",
    )
    parser.add_argument(
        "--pular-texto-acima-de",
        type=float,
        metavar="MB",
        default=None,
        help=(
            "adia .txt maiores que isto, em MB, sem abrir o arquivo. "
            "Ausente: vale o [base.limites] (padrão 2 MB em .txt; CSV não entra "
            "nesta flag — C7.d). 0 desliga. Fica como `adiado` e é repescado "
            "numa passada sem o limite"
        ),
    )
    parser.add_argument(
        "--pular-acima-de-n-chunks",
        type=int,
        metavar="N",
        default=LIMITE_CHUNKS_PADRAO,
        help=(
            f"adia .txt que gerem mais de N trechos (padrão: {LIMITE_CHUNKS_PADRAO}). "
            "0 desliga. O teto de megabytes pega o caso comum; este é a rede de segurança. "
            "CSV vira digesto (C7.d). Não se aplica a PDF/DOCX/PPTX"
        ),
    )
    parser.add_argument(
        "--apenas-onda",
        type=int,
        choices=(1, 2, 3, 4),
        help="indexa só esta onda de prioridade (1=pequenos vigentes, 4=cauda). "
        "Ausente: as quatro, nesta ordem, numa passada só",
    )
    parser.add_argument(
        "--exigir-exclusoes",
        action="store_true",
        dest="exigir_exclusoes",
        help="recusa a passada se alguma exclusão declarada não casar com nada. "
        "Sem isto o defeito só sai como aviso: regra inerte não devolve erro, a "
        "passada corre inteira e menos arquivos é justamente o que se pediu — em "
        "26/08/2026 custou 3 h 22 min e uma medição contaminada. Padrão avisa em "
        "vez de recusar porque escopo legitimamente vazio existe (pasta que este "
        "acervo ainda não tem)",
    )
    parser.add_argument(
        "--sem-reconciliar",
        action="store_true",
        help="não remove do índice os documentos que sumiram do disco; deixa fantasma para trás",
    )
    parser.add_argument(
        "--forcar-reconciliacao",
        action="store_true",
        help="reconcilia mesmo quando a proporção a remover passa da trava de segurança — "
        "use só depois de conferir que a raiz e o prefixo estão certos",
    )
    return parser
