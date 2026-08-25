# Matriz de armadilhas — gerador sintético (`E1`/`E2`) — v0.3

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

| Eixo | Antes do `E1.b` | Depois |
|---|---|---|
| `fatia` | `{não declarado: 260}` | `{mesma-língua: 270, cross-lingual: 30}` |
| `grupo_de_fonte` | `{escritório: 234, misto: 26}` | `{escritório: 270, misto: 30}` |
| `armadilha_fatia` | não existia (colidia com `fatia`) | 10 baldes × 30 |

`grupo_de_fonte` **continua sem `reunião` e sem `email`** — é a condição 3, e é do
`E1.c`. Enquanto ela não fechar, este corpus não mede o grupo que a `F4-P` decide.

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
| 3 | fatia de reunião e de email, com a interseção cross-lingual | `E1.c` |
| 4 | distribuição de formato calibrada pelo censo (`E6.1`) | `E1.c` |

A condição 2 fechou no `E1.b`, e o gerador passou a **não conseguir** emitir
código inválido: `perg()` valida contra `harness.IDIOMAS_ACEITOS` na emissão, e
`pt->en` levanta erro dizendo que travessia sai de cruzar os dois campos. Produtor
que não emite inválido é melhor que consumidor que rejeita depois.

**O que ainda impede este corpus de decidir a `F4-P`** é a condição 3: sem fatia
de reunião e de email, o `grupo_de_fonte` só tem `escritório` e `misto`, e o alvo
declarado da `F4-P` é `reunião`.

## Fora do escopo (extensões v0.3)

- legado OLE (`.doc`/`.ppt`/`.xls` via LibreOffice headless) — depende de `R1.1`
- OCR (PDF-imagem com texto conhecido) — `R1.2`
- planilha-modelo (rótulo esparso, fórmula sem cache) — `C7`
- CSV grande de 50–100 MB — flag `--escala`
- perfil de 100k documentos (portas de latência) — `R4.x`
