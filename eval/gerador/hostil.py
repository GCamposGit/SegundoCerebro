"""A pasta hostil — um arquivo para cada coisa que pode dar errado ao indexar.

Absorve a **`F6-E`** do `ROADMAP.md`, que pedia *"uma pasta montada de propósito
com o que uma base desconhecida tem e a nossa não"*. O gerador **é** o montador
de pastas; manter as duas separadas produziria duas fixtures da mesma classe,
divergindo.

## O checklist não é uma lista, é o enum do produto

A `F6-E` listava dez armadilhas de cabeça. Lista escrita à mão envelhece: o
décimo primeiro caso entra no produto e ninguém lembra de acrescentá-lo aqui.

O produto já declara o catálogo completo do que pode acontecer com um documento —
`ingest.document.ParseStatus`, nove valores, cada um com o motivo escrito. Este
módulo cobre **todos**, e `tests/test_pasta_hostil.py` confere a cobertura
**contra o enum**: status novo sem fixture reprova o teste, e o autor do status
descobre no mesmo dia.

| `ParseStatus` | Fixture | Medido em 25/08/2026 |
|---|---|---|
| `ok` | as outras dezoito fatias | — |
| `vazio` | `.txt` de 0 byte · **PDF digitalizado** (válido, sem texto) | 0 blocos, 0 chars |
| `erro` | PDF truncado · ZIP renomeado `.docx` | `FileDataError` · `KeyError: [Content_Types].xml` |
| `sem_parser` | `.xlsb` e `.xyz` — os dois existem no censo real | `parser_for` devolve `None` |
| `placeholder` | `FILE_ATTRIBUTE_OFFLINE` via `SetFileAttributesW` | `attrs=0x1000`, `cloud_only=True` |
| `adiado` | `.csv` acima do corte de `[base.limites]` | decidido pelo `stat`, sem abrir |
| `travado` | `~$` do Word **no corpus**; o lock real é do teste | ver abaixo |
| `duplicado` | fatia `duplicatas` — mesmos bytes em três caminhos | — |
| `sumiu` | **fora, declarado** — ver abaixo | — |

**`travado` não cabe em arquivo estático**, e fingir que cabe seria o defeito que
este repositório mais conhece. `FileLocked` nasce de um `PermissionError` num
`open()`, o que exige **outro processo segurando o arquivo agora**. O corpus traz
o `~$documento.docx` que o Word deixa ao abrir — que é o artefato real, e é o que
uma pasta de trabalho viva tem — e o lock de verdade é criado pelo teste, com
`CreateFileW` e `dwShareMode=0`. Mock de utilitário do sistema não prova permissão
(F3.5-D); aqui vale a mesma regra.

**`sumiu` fica fora e o motivo é a definição.** É a corrida entre enumerar e
abrir: o arquivo existia na varredura e não existe mais no processamento. Uma
pasta estática não tem corrida. Registrado aqui em vez de silenciado, porque a
lacuna declarada é a única que não vira dívida.

## Por que quase nada aqui tem pergunta

O aceite da `F6-E` é do **indexador**, não do ranking: *a indexação termina, o
registro diz por documento o que aconteceu, e nada entra no índice como se tivesse
texto quando não tem*. Falhar é aceitável; travar ou mentir em silêncio, não. Isso
se mede com status, não com recall — e uma pergunta cuja resposta provadamente não
está no índice não é pergunta de ranking: ela só empurraria a métrica para baixo
por um motivo que nada tem a ver com ordenar.

As exceções são **as três em que a hostilidade está no nome e não no conteúdo**,
onde o documento é perfeitamente legível e tem de ser encontrado:

- caminho acima de 260 caracteres (o acervo real tem 34, o maior com 293);
- nome com emoji e com acento;
- planilha cujo **rótulo** é achável mesmo quando o valor calculado não existe.

E duas anotadas `fora_de_escopo`, que é como o harness registra "não é mensurável
nesta fase" sem esconder a pergunta: o PDF digitalizado (`ocr`) e o valor que só
existe como fórmula (`formula_sem_cache`).
"""

from __future__ import annotations

from .nucleo import Doc, mkdoc, moeda, perg
from . import vocabulario as V

PASTA = "99. Quarentena"
"""Onde as armadilhas moram. Nome com número de ordenação de propósito: é como
pasta de trabalho é nomeada, e `eval.fonte.PREFIXO_DE_ORDENACAO` tem de tolerar."""

CORTE_CSV_MB = 2
"""O corte de `[base.limites]` para `.csv`. O arquivo `adiado` passa disso."""

SEM_PARSER = (".xlsb", ".xyz")
"""Extensões que o censo real tem e o produto não lê. `.xlsb` são 13 arquivos e
`.xyz` são 4, com 269,7 MB — não é hipótese, é o acervo."""


def _profundo(niveis: int = 4, largura: int = 80) -> str:
    r"""Sub-caminho que estoura os 260 caracteres do Windows **sozinho**.

    Quatro níveis de 94 caracteres dão ~380 no **relativo**, antes de somar a
    raiz. É deliberado: com três níveis o total dependia de onde o corpus fosse
    gerado, e numa base curta (`C:\corpus`) a fixture deixaria de ser hostil sem
    ninguém perceber — armadilha que só arma às vezes é pior que armadilha
    nenhuma, porque o teste verde passa a não significar nada.

    O acervo real chega a 293 do mesmo jeito: pasta de projeto dentro de pasta de
    cliente dentro de pasta de ano, cada uma com o nome por extenso."""
    return "/".join("Arquivo morto " + chr(97 + i) * largura for i in range(niveis))


def f_pasta_hostil(rng, n, ext):  # noqa: ANN001, ARG001
    """Um arquivo por modo de falha. Quase nenhum com pergunta — ver o módulo.

    Não escala com `n`, e é deliberado: uma armadilha basta para provar que o
    indexador a trata, e trinta cópias só encareceriam a passada. É a mesma
    decisão que `planilha_despejo` toma, e o `E2` a registra.
    """
    docs: list[Doc] = []
    ps: list[dict] = []

    # --- vazio ---------------------------------------------------------------
    docs.append(Doc(f"{PASTA}/vazio_0_byte.txt", "", formato="vazio"))

    cid_ocr = "CT-OCR-001"
    digitalizado = Doc(
        f"{PASTA}/Scan_001.pdf",
        f"CONTRATO {cid_ocr}\nValor total: {moeda(4_200_000)}.\n",
        formato="pdf_digitalizado",
    )
    docs.append(digitalizado)
    ps.append(perg(
        "q-ht-ocr", "pasta_hostil",
        f"Qual o valor total do contrato {cid_ocr}?", moeda(4_200_000),
        [digitalizado.caminho],
        armadilha="PDF digitalizado: valido, zero texto extraivel, zero chunks",
        feature_alvo="F4-O/OCR", fora_de_escopo="ocr",
    ))

    # --- erro ----------------------------------------------------------------
    docs.append(Doc(f"{PASTA}/relatorio_truncado.pdf", "", formato="pdf_truncado"))
    docs.append(Doc(f"{PASTA}/planilha_antiga.docx", "", formato="zip_como_docx"))
    docs.append(Doc(
        f"{PASTA}/exportado_do_sistema.xls",
        "<html><body><table><tr><td>CT-HT-001</td></tr></table></body></html>",
        formato="html_como_xls",
    ))

    # --- sem_parser ----------------------------------------------------------
    for sufixo in SEM_PARSER:
        docs.append(Doc(f"{PASTA}/base_operacional{sufixo}", "conteudo opaco", formato="sem_parser"))

    # --- travado (o artefato; o lock de verdade e do teste) -------------------
    docs.append(Doc(f"{PASTA}/~$Contrato em edicao.docx", "", formato="owner_do_word"))

    # --- placeholder de nuvem ------------------------------------------------
    docs.append(Doc(
        f"{PASTA}/Apresentacao na nuvem.txt",
        "Conteudo que nao deveria ser lido: ler um placeholder baixa o arquivo.\n",
        formato="placeholder_de_nuvem",
    ))

    # --- adiado --------------------------------------------------------------
    # Acumulador explícito: a primeira versão fazia `sum(len(x) for x in linhas)`
    # dentro do `while`, que é O(n²) — 70 mil linhas viraram bilhões de operações
    # e a geração não terminou em 3 minutos. Mesma forma do laço de siglas do
    # `E1.a`: barato de escrever, caro de esperar, e invisível no `n` pequeno.
    alvo = CORTE_CSV_MB * 1024 * 1024 + 4096
    linhas = ["coluna_a;coluna_b;coluna_c"]
    tamanho = len(linhas[0])
    while tamanho < alvo:
        linha = f"linha {len(linhas):07d};valor;{rng.randrange(1000, 9999)}"
        linhas.append(linha)
        tamanho += len(linha) + 1
    docs.append(Doc(f"{PASTA}/extracao_completa.csv", "\n".join(linhas) + "\n", formato="grande"))

    # --- hostil no NOME, legivel no conteudo: estes tem de ser encontrados ----
    cid_longo = "CT-LP-001"
    valor_longo = rng.randrange(200, 9000) * 1000
    longo = mkdoc(
        f"{PASTA}/{_profundo()}",
        "Contrato " + "renegociado " * 4 + cid_longo,
        f"CONTRATO {cid_longo}\nContratada: {rng.choice(V.EMPRESAS)}.\n"
        f"Valor total: {moeda(valor_longo)}.\n",
        "txt",
    )
    docs.append(longo)
    ps.append(perg(
        "q-ht-longo", "pasta_hostil",
        f"Qual o valor total do contrato {cid_longo}?", moeda(valor_longo),
        [longo.caminho],
        armadilha="caminho acima de 260 caracteres; conteudo perfeitamente legivel",
        feature_alvo="F6-E/caminho longo",
    ))

    cid_emoji = "CT-UN-001"
    valor_emoji = rng.randrange(50, 900) * 1000
    emoji = mkdoc(
        PASTA, "Relatório anual ✅ — versão final (não mexer) º",
        f"RELATORIO ANUAL\nContrato {cid_emoji}.\nValor apurado: {moeda(valor_emoji)}.\n",
        "txt",
    )
    docs.append(emoji)
    ps.append(perg(
        "q-ht-unicode", "pasta_hostil",
        f"Qual o valor apurado do contrato {cid_emoji}?", moeda(valor_emoji),
        [emoji.caminho],
        armadilha="nome com emoji, acento e travessao; conteudo legivel",
        feature_alvo="F6-E/unicode no nome",
    ))

    # --- formula sem cache: o rotulo acha, o valor nao existe -----------------
    cid_form = "CT-FM-001"
    formula = Doc(
        f"{PASTA}/Orcamento consolidado {cid_form}.xlsx",
        f"Orcamento consolidado {cid_form}\nRubrica: obras civis\nTotal apurado:",
        formato="xlsx_formula_sem_cache",
    )
    docs.append(formula)
    ps.append(perg(
        "q-ht-rotulo", "pasta_hostil",
        f"Que rubrica o orcamento {cid_form} consolida?", "obras civis",
        [formula.caminho],
        armadilha="planilha com formula sem cache; o ROTULO tem de ser achavel",
        feature_alvo="C7.a",
    ))
    ps.append(perg(
        "q-ht-formula", "pasta_hostil",
        f"Qual o total apurado do orcamento {cid_form}?", "3",
        [formula.caminho],
        armadilha="o valor so existe como formula; data_only devolve None",
        feature_alvo="C7.a", fora_de_escopo="formula_sem_cache",
    ))

    # --- planilha de muitas abas: o motivador do `adiado` por XML de abas -----
    docs.append(Doc(
        f"{PASTA}/Consolidado por unidade.xlsx",
        "Consolidado por unidade\nUnidade;Receita;Despesa",
        formato="xlsx_muitas_abas",
    ))

    return docs, ps
