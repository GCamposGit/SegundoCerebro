# O pacote E1 conferido contra o harness — 24/08/2026

Laudo do notebook sobre `pacote-e1-gerador-sintetico.zip`, entregue junto de
[`relatorio-avaliacao-resiliente.md`](relatorio-avaliacao-resiliente.md). O
relatório está certo no diagnóstico; o código que veio com ele não sustenta o que
o próprio relatório pede, e **oito achados são de execução, não de leitura**.

Este arquivo existe porque o gerador passou a ser do notebook (ver
[`colaboracao.md`](colaboracao.md) §6). Sem ele o conserto seria arqueologia.

## Como reproduzir

```bash
py -m eval.gerador --seed 42 --n-por-fatia 26 --out <dir> --sem-docx
```

`--n-por-fatia 26` e não 30, e o motivo é o achado 1.

---

## 1. O comando do próprio README não termina

`_sigla()` gera a tripla `chr(65 + (b*m) % 26)` para `m` em `(7, 11, 17)`. Os três
multiplicadores são coprimos de 26, então `b mod 26` é **bijeção** sobre a tripla:
o espaço de siglas tem exatamente **26 elementos**, não 26³. Em `i = 26` o
conjunto `vistos` já contém os 26 e o `while True` nunca sai.

```
0 AAA · 1 HLR · 2 OWI · … · 24 MES · 25 TPJ
i=26 → não retorna
```

`--n-por-fatia 30` é o comando do `README-INTEGRACAO.md` e é também o piso que o
`E5` exige para significância (n ≥ 30 por fatia). **O piso do E5 é inalcançável
pelo gerador do E1.**

**A suíte que veio no zip passa** — cinco testes verdes — porque todos usam
`n ≤ 11`. É a lição da F3.5-D repetida com outro nome: teste verde contra um
caminho que a máquina não executa. Ali era `schtasks` simulado; aqui é um `n` que
ninguém pediu.

**Conserto:** espaço de siglas de tamanho suficiente (três letras independentes
dão 17.576) e **teto explícito** — quando acabar, erro, nunca laço.

## 2. A escala declarada não existe, e tem teto

No maior `n` que roda:

| | E1 declara | Medido em `n = 26` | |
|---|---:|---:|---:|
| documentos | ≥ 2.000 | **559** | 28% |
| perguntas | ≥ 500 | **260** | 52% |

Não é trabalho faltando: é teto. Acima de 26 o gerador não termina.

Distribuição por fatia em `n = 26`:

| Fatia | docs | perguntas |
|---|---:|---:|
| nomes_ruins | 26 | 26 |
| versoes | 104 | 26 |
| duplicatas | 78 | 26 |
| cross_lingual | 26 | 26 |
| siglas | 53 | 26 |
| planilha_despejo | 3 | 26 |
| multihop | 52 | 26 |
| temporal | 78 | 26 |
| distratores | 104 | 26 |
| estrutura_pastas | 26 | 26 |
| venenosos | 9 | 0 |
| **total** | **559** | **260** |

`planilha_despejo` não escala com `n`: são sempre 3 CSVs de 4.000 linhas,
independentemente de quantas perguntas se peça deles.

## 3. A fatia cross-lingual sai de tamanho zero

É o defeito exato contra o qual [`eval/golden/README.md`](../eval/golden/README.md)
escreveu contrato em 24/08/2026, e ele tem **duas causas independentes**.

A primeira é dura e aparece na hora:

```
ValueError: código de idioma não reconhecido: ['en->pt', 'pt->en']
             — use um de ['en', 'indefinido', 'misto', 'pt']
```

O gerador escreve a *travessia* (`pt->en`) num campo que guarda o idioma **da
pergunta**. `IDIOMAS_ACEITOS` é vocabulário fechado de propósito.

A segunda é silenciosa e é a grave. Depois de mapear os códigos à mão
(`pt->en` → `idioma="pt"`), as 260 perguntas carregam:

```
fatia de idioma: {'não declarado': 260}
```

Porque **`idioma_fonte` nunca é emitido**. A fatia cross-lingual fica de tamanho
zero e o relatório sai parecendo aprovado — palavra por palavra o que o
`README.md` do dourado avisou que aconteceria, e o motivo de
[`fatia-cross-lingual.md`](fatia-cross-lingual.md) existir.

**Conserto:** emitir os dois campos. Na fatia cross-lingual, `idioma` é o da
pergunta e `idioma_fonte` o do documento; nas outras dez, os dois são `pt` —
declarar `pt` é diferente de omitir, e a omissão é que mata a fatia.

## 4. Zero perguntas de reunião e de email

Medido com `grupo_de_pergunta` de [`eval/fonte.py`](../eval/fonte.py):

```
grupo de fonte: {'escritório': 234, 'misto': 26}
```

Nenhum `.msg`, nenhum `.eml`, nenhum `.vtt`, nenhuma pasta de transcrição. Os 26
`misto` são a fatia de duplicatas, que espalha a mesma ata entre `Atas/`,
`Backup/` e `Antigo/` — mistura de grupos por acidente, não fatia de reunião.

Isto importa mais que os outros sete juntos: **o alvo declarado da `F4-P` é o
grupo `reunião`** (MRR 0,287 → 0,452, ver
[`ablacao-caminho-entregue.md`](ablacao-caminho-entregue.md)). O corpus sintético,
como veio, **não mede o pacote que ele deveria destravar**. Rodá-lo antes da
`F4-P` não compra nada para a `F4-P`.

**Conserto:** duas fatias novas — transcrição de reunião (`.vtt`/`.txt` sob
`Meetings/`, com o vocabulário falado que faz o ranqueador de nome errar) e email
(`.eml` de verdade, que o parser de 21/08 já lê). E a interseção que o
`colaboracao.md` §6 registra: **3 das 11 perguntas de reunião do dourado real são
cross-lingual** — a fatia sintética tem de cruzar os dois eixos, não só somá-los.

## 5. A distribuição de formato está invertida

Com `python-docx` instalado, `n = 26`:

| | `.txt` | `.md` | `.docx` | `.csv` | `.pdf` |
|---|---:|---:|---:|---:|---:|
| gerado | 338 | 108 | 107 | 3 | 3 |

Os 3 `.pdf` são os truncados da fatia de venenosos: **zero PDF com conteúdo**,
zero `.xlsx`, zero `.pptx`. O acervo real é **74% PDF+DOCX** (`docs/censo.md`), e
os parsers que o produto executa de verdade são `pymupdf4llm` e o de OOXML.

Um corpus 80% `.txt` mede um caminho de código que o produto quase não usa. O
`E6` diz que as distribuições do censo devem parametrizar o gerador; hoje não
parametrizam nada.

## 6. O hash do manifesto depende da máquina

Mesma seed, mesmo `n`:

```
--sem-docx        agregado ad7030086dbed99b…
com python-docx   agregado 54873c29b838d32f…
```

O hash é lógico (sobre o texto-fonte, correto — `.docx` embute timestamp), mas a
entrada inclui o **caminho**, e o caminho inclui a extensão, que depende de
`detectar_caps()`. `caps` fica registrado no manifesto, então é detectável — mas
o invariante como escrito ("mesma seed ⇒ mesmo corpus") só vale **com capacidade
fixa**.

Consequência prática para o `E3`: o test-set selado sela **seed + caps**, não
seed. Um selo gerado no desktop com `python-docx` não reproduz no CI sem ele, e o
modo de falha é um hash diferente sem nenhuma explicação à vista.

## 7. A suíte do zip levaria nomes reais para um repositório público

`tests/test_gerador_sintetico.py` carrega uma `DENYLIST` com **dez nomes de
cliente e fornecedor por extenso**, no arquivo versionado.

[`tests/test_saneamento.py`](../tests/test_saneamento.py) existe exatamente para
isso, e a docstring dele já nomeia este anti-padrão:

> Um teste que trouxesse os nomes por extenso seria o próprio vazamento, com a
> agravante de ficar no arquivo que existe para impedi-lo.

O mecanismo certo já está no repo desde então: `nomes-proibidos.txt` na raiz,
**fora do Git**, uma lista por máquina, e o teste pula quando o arquivo não
existe — é o que mantém o CI e um clone novo verdes.

**Este é o único achado que trata como bloqueio de merge.** O conserto é reusar
`test_saneamento.termos()` em vez de escrever a lista.

Na mesma varredura: `relatorio-avaliacao-resiliente.md` cita **uma vez** o nome
da empresa do usuário, que não aparece em **nenhum** arquivo versionado hoje.
Trocado por descrição genérica ao commitar, e o termo entra no
`nomes-proibidos.txt` local para a suíte pegar o próximo.

## 8. O formato não encaixa no harness, e o encaixe é do notebook

| `perguntas.sintetico.jsonl` | `eval.harness.Pergunta` | O que fazer |
|---|---|---|
| `docs_relevantes` | `fontes` | renomear |
| `criterio: qualquer\|todas` | derivado de `tipo == "multihop"` | só `multihop` usa `todas` hoje — compatível |
| `armadilha`: string descritiva | `armadilha`: bool | a string vira `notas`, o bool vira `True` |
| `idioma: pt->en` | `idioma` + `idioma_fonte` | achado 3 |
| `fatia`: armadilha plantada | `fatia`: idioma | **colisão de nome** |
| `feature_alvo`, `meta` | — | campo novo |

A colisão do achado 8 não é cosmética. O harness já tem **dois** eixos de recorte
com projeto deliberadamente diferente — `idioma_fonte` é anotação estática porque
não é derivável sem abrir o índice; `grupo_de_fonte` é derivado porque o caminho
já está no dourado. A armadilha plantada é um **terceiro** eixo, e ele é anotação
por construção: só o gerador sabe o que plantou. Nome sugerido: `armadilha_fatia`,
com `fatia` reservado ao idioma, para não reescrever `C4.5`.

---

## O que está certo e não se mexe

O laudo acima é longo porque defeito precisa de detalhe. O acerto de projeto é
maior que a soma deles:

- **Ground truth por construção.** Para um sistema de recuperação — não de
  geração — plantar o fato e a pergunta juntos por código é melhor que o padrão
  de 2025-26 (RAGAS e sucessores): sem juiz LLM, sem anotação que envelhece, sem
  contaminação. É a decisão central do E1 e ela está certa.
- **RNG por fatia** (`random.Random(f"{seed}:{nome}")`). É o detalhe que permite
  acrescentar fatia sem invalidar as existentes — e portanto sem invalidar
  histórico. Poucos geradores acertam isso.
- **Hash lógico e não binário**, com o motivo escrito (`.docx` embute timestamp).
  Diagnóstico certo; o achado 6 é sobre a entrada do hash, não sobre a escolha.
- **Colisão de caminho levanta erro** em vez de sobrescrever em silêncio.
- **Fatia de venenosos sem pergunta nenhuma.** Ela mede robustez do indexador e
  não ranking, e não fingir que mede ranking é o que a mantém honesta.
- **Congelar o dourado real em vez de substituí-lo** (`E3.1`). Preserva a série
  F1→F2, que é a razão de o harness existir antes dos recuperadores.

## O que o laudo muda na ordem

`E5` (IC bootstrap) **antes** da `F4-P`, e o motivo é o achado 4. A `F4-P` decide
sobre `reunião` (n = 11) e `cross-lingual` (n = 12); com n = 11 uma pergunta são 9
pontos. O sintético hoje não mede nenhum dos dois grupos, então rodá-lo primeiro
não protegeria a `F4-P` de nada — o que protege é o intervalo de confiança sobre o
dourado corporativo, que é o piso já declarado.

Ordem registrada em [`colaboracao.md`](colaboracao.md) §6 e no
[`ROADMAP.md`](../ROADMAP.md): **`E5` → `F4-P` → `E1` endurecido**.
