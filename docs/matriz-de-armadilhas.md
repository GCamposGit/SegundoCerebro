# Matriz de armadilhas — gerador sintético (`E1`/`E2`) — v1.0

Mapeamento fatia ↔ pacote do roadmap. **Toda ablação reporta a tabela por fatia;
média agregada não decide nada** (protocolo `E3`).

Versão v0.1 veio no pacote `E1`; a v0.2 é de 25/08/2026 e registra o que o
[laudo](avaliacao-pacote-e1.md) mudou. O gerador é
[`eval/gerador/`](../eval/gerador/); o corpus **não** é versionado, o gerador é.

```bash
py -m eval.gerador --seed 42 --n-por-fatia 30 --out <dir> --sem-docx
```

`--n-por-fatia 30` é o `eval.estatistica.N_MINIMO`, que é o piso que o `E5` exige
por fatia. Até 25/08/2026 esse comando **não terminava** — ver a tabela de
escala abaixo.

## As onze fatias

| Fatia | Armadilha plantada | Mede | Critério |
|---|---|---|---|
| `nomes_ruins` | contrato relevante em `IMG_9999.txt` | `C3.a`, `R6.1`, peso do nome | qualquer |
| `versoes` | `v1..final_FINAL(2)`, valor só na final | `C6`, `R1.3` | qualquer (canônico) |
| `duplicatas` | mesma ata em 3 caminhos | `R1.3`, duplicatas@10 | qualquer |
| `cross_lingual` | pergunta PT → doc EN, e EN → PT | `C4`, `R3.1`, `R6.2` | qualquer |
| `siglas` | definida 1×/2×, ambígua por pasta, nunca definida | `C2` | qualquer |
| `planilha_despejo` | 1 linha relevante em 4.000 (CSV) | `C7` | qualquer |
| `multihop` | encadear resumo → contrato | `neighbors`/grafo | **todas** |
| `temporal` | 3 revisões; vigente vs "em 2019" | `R6.3`, `C6` | qualquer |
| `distratores` | 3 hard negatives na mesma pasta | `R6.2` rerank | qualquer |
| `estrutura_pastas` | taxonomia rica vs `Diversos/` | `R2.1` | pareado |
| `reuniao` | identificador só na **fala**; nome do arquivo é data e hora | `F4-P`, `C3.a` | qualquer |
| `email` | assunto `RES: RES: ENC:`; resposta só no corpo | `F4-P`, parser de email | qualquer |
| `venenosos` | PDF truncado, ZIP renomeado, 0 byte | `R1.4` quarentena | **sem pergunta** |

`venenosos` sem pergunta nenhuma é decisão, não lacuna: ela mede robustez do
indexador e não ranking, e não fingir que mede ranking é o que a mantém honesta.

## Escala — o que o `E1.a` destravou

O `E1` declarava ≥ 2.000 documentos e ≥ 500 perguntas. Medido com `--seed 42
--sem-docx`, antes e depois do conserto do espaço de siglas
([`fatias.TETO_DE_SIGLAS`](../eval/gerador/fatias.py)):

| `--n-por-fatia` | antes | depois |
|---|---|---|
| 26 | 559 docs · 260 perguntas | 559 · 260 |
| 27 | **trava** | 579 · 269 |
| 30 (`N_MINIMO`) | **trava** | 643 · 300 |
| 100 | **trava** | **2.112 · 1.000** |

A escala declarada existia; o que não existia era um `n` em que ela coubesse. O
laudo tratou "o comando não termina" (achado 1) e "a escala declarada não existe"
(achado 2) como dois achados — a medição mostra que o segundo era **consequência**
do primeiro, e os dois fecham juntos.

`planilha_despejo` continua sendo a exceção que não escala com `n`: são sempre 3
CSVs de 4.000 linhas, por construção.

## Campos de cada pergunta (`perguntas.sintetico.jsonl`)

```
id, armadilha_fatia, pergunta, resposta_esperada, docs_relevantes,
criterio (qualquer|todas), tipo, idioma, idioma_fonte, armadilha,
feature_alvo, meta
```

`meta` carrega `familia`, `docs_distratores`, `condicao`/`par_id`, `canonico`,
`subtipo`. Métricas que saem daí sem mudar o harness: duplicatas@10
(`meta.familia`), precisão contra distratores (`meta.docs_distratores`), Δ
taxonomia vs plana (`meta.par_id`). O adaptador os preserva no arquivo, fora de
`Pergunta` — o harness ignora chave que não conhece.

**`armadilha_fatia`, não `fatia`** (achado 8). São **três** eixos de recorte, com
projeto deliberadamente diferente, e a colisão de nome obrigaria a reescrever o
`C4.5`:

| Eixo | Como nasce | Vazio no dourado real? |
|---|---|---|
| `fatia` (idioma) | derivado de `idioma` × `idioma_fonte` | não — anotado por `eval.idioma` |
| `grupo_de_fonte` | derivado do caminho da fonte | não — sempre um dos quatro |
| `armadilha_fatia` | **anotação por construção** — só o gerador sabe o que plantou | **sim**, e é correto |

## O adaptador, e o eixo que não pode colapsar

[`eval/adaptador_sintetico.py`](../eval/adaptador_sintetico.py) converte para o
formato do harness e **recusa** um conjunto em que qualquer eixo declarado tenha
pergunta no balde "não declarado":

```bash
py -m eval.adaptador_sintetico --entrada <dir do gerador> --saida <perguntas.jsonl>
```

A regra não é "≥ 2 baldes" — um corpus legitimamente monolíngue tem um balde só, e
isso é verdade, não defeito. O que nunca é legítimo é a pergunta cair no balde que
significa *ninguém preencheu*, porque ele não distingue "não se aplica" de
"esqueceram". Medido em `--seed 42 --n-por-fatia 30`:

| Eixo | Como veio no pacote | Depois do `E1.b`+`E1.c` |
|---|---|---|
| `fatia` | `{não declarado: 260}` | `{mesma-língua: 310, cross-lingual: 50}` |
| `grupo_de_fonte` | `{escritório: 234, misto: 26}` | `{escritório: 270, misto: 30, reunião: 30, email: 30}` |
| `armadilha_fatia` | não existia (colidia com `fatia`) | 12 baldes × 30 |

**E a interseção, que é o que a condição 3 pede de verdade** — somar os dois eixos
não mediria o caso que o acervo tem:

| | mesma-língua | cross-lingual |
|---|---:|---:|
| escritório | 240 | 30 |
| misto | 30 | 0 |
| **reunião** | 20 | **10** |
| **email** | 20 | **10** |

Uma em cada três (`fatias.CRUZA_IDIOMA`), que é a proporção do dourado real: 3 das
11 perguntas de reunião cruzam idioma.

## Formato — a condição 4, medida

`--seed 42 --n-por-fatia 30`, com as quatro bibliotecas presentes (703 documentos):

| | `.pdf` | `.xlsx` | `.docx` | `.pptx` | `.vtt` | `.eml` | `.md` | `.txt` | `.csv` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **censo real** | 47,8% | 21,8% | 14,7% | 8,0% | — | 3,5%¹ | 1,2% | 0,4% | 0,2% |
| **gerado** | 45,7% | 21,1% | 15,1% | 6,4% | 4,3% | 4,3% | 2,3% | 0,6% | 0,4% |
| **no pacote** | 0,5%² | 0% | 19,1% | 0% | 0% | 0% | 19,3% | 60,5% | 0,5% |

¹ o acervo real usa `.msg`; a fatia sintética usa `.eml`, que é MIME e que o
parser de 21/08 lê sem COM. ² os três PDFs do pacote eram os **truncados** da
fatia de venenosos — zero PDF com conteúdo.

Formato sem biblioteca nesta máquina vira `txt` **e fica registrado em `caps`**,
que é dimensão do selo desde o `E1.a`: um corpus `--so-texto` nunca se confunde com
o completo. E cada formato binário que o gerador escreve **volta pelo despachante
que o indexador usa**, em teste — escrever um PDF que o `pymupdf4llm` não lê seria
afirmar uma distribuição que o produto não enxerga.

## O que o selo sela

`manifesto.json` sela **seed + `n_por_fatia` + `caps`**, não só a seed
([`nucleo.DIMENSOES_DO_SELO`](../eval/gerador/nucleo.py)). O caminho de cada
documento carrega a extensão, e a extensão sai de `detectar_caps()`: mesma seed
com e sem `python-docx` produz corpora **diferentes de verdade**.

`conferir_selo()` confere as dimensões **antes** do agregado, e essa ordem é a
entrega — um agregado diferente é sintoma de todas as causas, e só uma delas é "o
gerador mudou". Sem isso o `E3` reprovaria um test-set selado dizendo "hash
diferente" quando a causa é `python-docx` ausente no CI.

## O que ainda falta para o `E1` entrar inteiro

As sete condições do [laudo](avaliacao-pacote-e1.md). O `E1.a` fecha **1, 5 e 6**;
as outras quatro são os pacotes seguintes:

| # | Condição | Pacote |
|---|---|---|
| 1 | `--n-por-fatia 30` termina, com teto que levanta erro | ✅ `E1.a` |
| 5 | selo é seed + `caps` | ✅ `E1.a` |
| 6 | nenhuma lista de nome real em arquivo versionado | ✅ `E1.a` |
| 2 | emitir `idioma` **e** `idioma_fonte` no vocabulário fechado do harness | ✅ `E1.b` |
| 7 | adaptador para `harness.Pergunta`, com `armadilha_fatia` como 3º eixo | ✅ `E1.b` |
| 3 | fatia de reunião e de email, com a interseção cross-lingual | ✅ `E1.c` |
| 4 | distribuição de formato calibrada pelo censo (`E6.1`) | ✅ `E1.c` |

As sete condições fecharam. O que cada uma trouxe está nas seções acima; o que
sobra são as extensões da v1.1, listadas no fim, e nenhuma delas bloqueia usar
este corpus como camada 2.

**O que este corpus continua não sendo:** condição C. Métrica de corpus sintético
não decide sozinha — ela é a camada 2 do protocolo do `E3`, e a camada 3 (`C5`,
benchmark externo amostrado) existe justamente para detectar endogamia deste
gerador. Um ganho que só aparece aqui é um ganho deste gerador.

## Fora do escopo (extensões v1.1)

- legado OLE (`.doc`/`.ppt`/`.xls` via LibreOffice headless) — depende de `R1.1`
- OCR (PDF-imagem com texto conhecido) — `R1.2`
- planilha-modelo (rótulo esparso, fórmula sem cache) — `C7`
- CSV grande de 50–100 MB — flag `--escala`
- perfil de 100k documentos (portas de latência) — `R4.x`
