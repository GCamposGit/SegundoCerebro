# Matriz de armadilhas — gerador sintético (`E1`/`E2`) — v2.0

Mapeamento fatia ↔ pacote do roadmap. **Toda ablação reporta a tabela por fatia;
média agregada não decide nada** (protocolo `E3`).

O gerador é [`eval/gerador/`](../eval/gerador/); o corpus **não** é versionado, o
gerador é. O corpus não é condição C: é a **camada 2** do protocolo do `E3`, e
ganho que só aparece aqui é ganho deste gerador — é para isso que a camada 3
(`C5`, benchmark externo) existe.

```bash
py -m eval.gerador --seed 42 --n-por-fatia 30 --out <dir>
py -m eval.adaptador_sintetico --entrada <dir> --saida <dir>/perguntas.jsonl
```

`--so-texto` (alias do antigo `--sem-docx`) desliga os quatro formatos binários e
roda em segundos — é o modo do CI. `--n-por-fatia 30` é o `eval.estatistica.N_MINIMO`.

| `--n-por-fatia` | documentos | perguntas | tempo |
|---:|---:|---:|---:|
| 30 | 1.174 | 651 | 29 s |
| 100 | 3.833 | 2.121 | 7 s (`--so-texto`) |

## Os três checklists, e nenhum é uma lista escrita à mão

É o método deste pacote, e vale mais que qualquer fatia individual: **a régua sai
de um contrato que o produto já declara.** Lista escrita de cabeça envelhece — o
décimo primeiro caso entra no produto e ninguém lembra de acrescentá-lo.

| Checklist | Régua | Teste | O que reprova |
|---|---|---|---|
| formatos | `parsers.supported_extensions()` | [`tests/test_formatos.py`](../tests/test_formatos.py) | parser novo sem fixture |
| modos de falha | `ingest.document.ParseStatus` | [`tests/test_pasta_hostil.py`](../tests/test_pasta_hostil.py) | status novo sem fixture |
| mecanismos | os módulos de `src/segundocerebro/retrieve/` | [`eval/test_ranking_sintetico.py`](../eval/test_ranking_sintetico.py) | mecanismo novo sem fatia |

Cada um tem uma tabela de **lacunas declaradas** — `SO_HOSTIL`,
`SEM_FIXTURE_POSSIVEL`, `SEM_FATIA_PROPRIA` — e cada tabela tem um **segundo teste
que a impede de crescer por conveniência**. A lacuna declarada é a única que não
vira dívida; a tabela sem guarda vira o lugar onde se joga o caso inconveniente.

## As dezenove fatias

| Fatia | Armadilha plantada | Mede | Perguntas em `n=30` |
|---|---|---|---:|
| `nomes_ruins` | contrato relevante em `IMG_9999.txt` | `nomes`, `C3.a`, `R6.1` | 30 |
| `versoes` | `v1..final_FINAL(2)`, valor só na final | `familias`, `C6` | 30 |
| `familia_sem_numero` | **a vigente não declara `_vN` e é mais nova que a `_v6`** | `familias`, `C6` | 30 |
| `temporal` | 3 revisões; vigente vs "em 2019" | `familias`, `R6.3` | 30 |
| `duplicatas` | mesma ata em 3 caminhos (status `duplicado`) | `hybrid`, `R1.3` | 30 |
| `cross_lingual` | pergunta PT → doc EN, e EN → PT | `hybrid`, `C4`, `R3.1` | 30 |
| `idioma_indeciso` | **documento `misto`; consulta `indefinido`** | `hybrid`, `C4.5` | 60 |
| `siglas` | definida 1×/2×, ambígua por pasta, nunca definida | `glossario`, `C2` | 30 |
| `glossario` | **pergunta pela sigla × doc por extenso, e o inverso** | `glossario` | 60 |
| `grafias` | **4 grafias da mesma norma; 2 PLs que não se unificam** | `grafo`, `identificadores` | 60 |
| `multihop` | encadear resumo → contrato | `grafo`, `neighbors` | 30 |
| `distratores` | 3 hard negatives na mesma pasta | `rerank`, `R6.2` | 30 |
| `estrutura_pastas` | taxonomia rica vs `Diversos/` | `nomes`, `R2.1` | 30 |
| `reuniao` | identificador só na **fala**; nome é data e hora | `nomes`, `F4-P` | 30 |
| `email` | assunto `RES: RES: ENC:`; resposta só no corpo | `F4-P`, parser de email | 30 |
| `chunk_hostil` | **URL de 12 mil chars; tabela de 900 linhas** | chunking, truncagem | 60 |
| `planilha_despejo` | 1 linha relevante em 4.000 (CSV) | `hybrid`, `C7` | 30 |
| `formatos` | um documento por parser registrado | os 17 parsers | 16 |
| `pasta_hostil` | um arquivo por modo de falha | indexador, `F6-E` | 5 |

As três últimas **não escalam com `n`**, e é deliberado: um documento prova que o
parser é exercitado e uma armadilha prova que o indexador a trata. Trinta cópias
só encareceriam a passada.

## Os três eixos de recorte

| Eixo | Como nasce | Vazio no dourado real? |
|---|---|---|
| `fatia` (idioma) | derivado de `idioma` × `idioma_fonte` | não — anotado por `eval.idioma` |
| `grupo_de_fonte` | derivado do caminho da fonte | não — sempre um dos quatro |
| `armadilha_fatia` | **anotação por construção** — só o gerador sabe o que plantou | **sim**, e é correto |

Medido em `--seed 42 --n-por-fatia 30`:

```
fatia            {mesma-língua: 541, não declarado: 60, cross-lingual: 50}
grupo_de_fonte   {escritório: 559, email: 32, misto: 30, reunião: 30}
armadilha_fatia  19 baldes
```

**`não declarado` é resposta legítima e não lacuna**, e a distinção custou uma
medição. `idioma.decidido()` exclui `misto` e `indefinido` de propósito — um
documento metade PT metade EN atende consulta nos dois idiomas, e contá-lo como
acerto cross-lingual inflaria justamente a métrica que existe para achar a
fraqueza da ponte. Por isso `conferir_eixos` confere o **campo anotado**, não o
balde derivado: *vazio é "ninguém olhou", `indefinido` é "olhou-se e não há
evidência"*.

### A interseção, que é o que a condição 3 pedia de verdade

| | mesma-língua | cross-lingual |
|---|---:|---:|
| escritório | 519 | 30 |
| **reunião** | 20 | **10** |
| **email** | 20 | **10** |

Uma em cada três (`fatias.CRUZA_IDIOMA`), que é a proporção do dourado real: 3 das
11 perguntas de reunião cruzam idioma. Somar os dois eixos mediria dois casos que
existem — e não o caso que a `F4-P` decide.

## Formato — calibrado pelo censo, e com os 17 parsers presentes

| | `.pdf` | `.xlsx` | `.docx` | `.pptx` | `.txt` | `.csv` |
|---|---:|---:|---:|---:|---:|---:|
| **censo real** | 47,8% | 21,8% | 14,7% | 8,0% | 0,4% | 0,2% |
| **gerado** | 46,9% | 21,7% | 15,1% | 7,0% | 0,6% | 0,4% |
| **no pacote original** | 0,5%¹ | 0% | 19,1% | 0% | 60,5% | 0,5% |

¹ os três PDFs do pacote eram os **truncados** da fatia de venenosos — zero PDF
com conteúdo.

São **20 extensões** no corpus: as 17 que o produto lê, mais `.xlsb`, `.xyz` (sem
parser, e os dois existem no censo real) e a cauda de formato. `.vtt`, `.eml`,
`.msg`, `.doc`, `.ppt` e os macro-habilitados entram por fatia; o resto pelo
sorteador.

**Duas responsabilidades separadas, e a separação é o ponto**: a distribuição do
censo serve ao **realismo**; a fatia `formatos` garante a **cobertura**. Realismo
não garante cobertura — `.pptm` são 0,1% do acervo e arredondam para zero em
metade das seeds, e parser não exercitado é ponto cego que não escala com `n`.

`.xls` **válido** fica de fora, declarado: o `xlrd` exige BIFF e recusa CFB
inventado (`XLRDError: Expected BOF record`); escrever BIFF pediria o `xlwt`, que
não é dependência. O `.xls` aparece nas duas formas **hostis**, que são as que o
`F4-L` persegue.

## A pasta hostil — todo `ParseStatus` coberto

Absorve a **`F6-E`**. Aceite: *a indexação termina, o registro diz por documento o
que aconteceu, e nada entra no índice como se tivesse texto quando não tem*.
Falhar é aceitável; travar ou mentir em silêncio, não.

| Status | Fixture | Medido em 25/08/2026 |
|---|---|---|
| `vazio` | `.txt` de 0 byte · **PDF digitalizado** (válido, sem texto) | 0 blocos, 0 chars |
| `erro` | PDF truncado · ZIP renomeado `.docx` | `FileDataError` · `KeyError` |
| `sem_parser` | `.xlsb`, `.xyz` | `parser_for` devolve `None` |
| `placeholder` | `FILE_ATTRIBUTE_OFFLINE` via `SetFileAttributesW` | `attrs=0x1000` |
| `adiado` | `.csv` acima do corte de `[base.limites]` | decidido pelo `stat` |
| `duplicado` | fatia `duplicatas` | — |
| `travado` | `~$` no corpus; o **lock real** é do teste (`CreateFileW`, `dwShareMode=0`) | — |
| `sumiu` | **fora, declarado**: é corrida, e pasta estática não tem corrida | — |

Mais o que é hostil **no nome** e legível no conteúdo, que por isso **tem
pergunta** e precisa ser encontrado: caminho de 504 caracteres, nome com emoji e
acento, e o rótulo de uma planilha cujo valor calculado não existe.

Duas perguntas ficam `fora_de_escopo`, que é como o harness registra "não é
mensurável nesta fase" sem apagar a pergunta: o PDF digitalizado (`ocr`) e o valor
que só existe como fórmula (`formula_sem_cache`, motivo novo no catálogo).

## O que o selo sela

`manifesto.json` sela **seed + `n_por_fatia` + `caps`**
([`nucleo.DIMENSOES_DO_SELO`](../eval/gerador/nucleo.py)). `caps` são quatro
formatos, não mais só o `docx`, e `conferir_selo()` confere as dimensões **antes**
do agregado — um agregado diferente é sintoma de todas as causas, e só uma delas é
"o gerador mudou".

## Fora do escopo (extensões v2.1)

- `.xls` válido, se o `xlwt` algum dia entrar por outro motivo
- OCR (PDF-imagem com texto conhecido) — `R1.2`
- CSV grande de 50–100 MB — flag `--escala`
- perfil de 100k documentos (portas de latência) — `R4.x`
- **pergunta sem resposta no corpus.** Um sistema de recuperação também tem de se
  comportar quando a resposta não existe, mas recall@k precisa de fonte esperada e
  o harness exige `fontes`. Medir isso pede outra métrica, não outra fatia.
