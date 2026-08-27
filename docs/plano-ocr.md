# Plano — OCR completo (F4-O / R1.2)

**Data:** 27/08/2026 · **Dono do código:** desktop · **Dono do número no dourado:** notebook

O F4-O.0 (PR da fila, `ingest/ocr.py`) entregou a **porta**: scan marcado
`digitalizado` entra numa fase *depois* das quatro ondas de texto; extra `[ocr]`
opcional; sem extra a indexação é a de hoje. Isso **não** é OCR de produção.

O dossiê (`R1.2`) pede recall@5 ≥ 2/3 em `g015`/`g025`/`g048`. Esse número é do
acervo corporativo e só o notebook o mede. O desktop fecha o método que pega a
classe na base de amanhã — pasta que nunca vimos, PDF antigo, foto de ofício.

Este arquivo é o pacote restante. Sem ele o ROADMAP trata a porta como fase
fechada, e o leigo com `--ocr` acha que o contrato de 2003 vira trecho buscável.

---

## O que o F4-O.0 prova, e o que não prova

Prova (suíte padrão, motor **falso** `SEGUNDOCEREBRO_OCR_FAKE`):

- PDF com camada de texto não entra no OCR
- `--ocr` desligado deixa o scan `vazio`
- a fase OCR só corre depois do parse das ondas de texto
- extra ausente é no-op, não exceção

Não prova:

- RapidOCR lê português
- a API do pacote `rapidocr-onnxruntime>=1.3,<2` é a que o código chama
- 144 dpi (`Matrix(2,2)`) chega para letra de ofício
- página-foto no meio de um PDF nativo é alcançada
- um scan de 80 páginas cabe na RAM do notebook
- g015/g025/g048 saem de `fora_de_escopo`

Os testes plantam a string e conferem que ela volta. É o mesmo modo de falha do
`schtasks` da F3.5: verde contra um comando que a máquina recusa — aqui, verde
contra um motor que a suíte padrão **não carrega**.

---

## A classe (regra 12)

Não é “consertar três perguntas do dourado”. A classe é:

> **Página de PDF cuja camada de texto não existe ou não basta, e o conteúdo
> visível está no bitmap.**

Três formas, a terceira é a que o limiar por *arquivo* não pega:

1. arquivo inteiro é scan (hoje: `digitalizado` → fila OCR)
2. arquivo misto: umas páginas nativas, outras foto (hoje: média de chars alta
   ⇒ **não** marca, páginas-imagem invisíveis)
3. letra pequena / 200 dpi / carimbo no canto — raster fraco, motor devolve lixo
   plausível

O remendo “ligar RapidOCR no arquivo `digitalizado`” não fecha (2) nem (3).

---

## Três pacotes, um de cada vez

Não misturar motor real, geometria da página e número do dourado no mesmo PR.
Hipótese sem efeito mínimo não gera varredura. Empate encerra.

### F4-O.1 — o motor de verdade lê o que plantamos · desktop

| Campo | Valor |
|---|---|
| Serve base desconhecida | `--ocr` com o extra instalado extrai um contrato em português de um PDF que é só imagem; se não extrai, o extra não se vende como leitura |
| Hipótese | RapidOCR, no raster padrão, recupera um identificador plantado (forma VCE, tipo `NN-VCE-001`) numa página renderizada como imagem |
| Efeito mínimo | o identificador aparece no texto extraído, **exato**, em 1 página / 1 arquivo. Não é MRR. Binário |
| Orçamento | uma passada, semente fixa, marker `ocr` (fora da suíte padrão — o extra não vai no CI) |
| Encerramento | identificador ausente ⇒ hipótese refutada; troca de motor (Tesseract `por+eng`, ou modelo RapidOCR explícito) é **outro** pacote, com a mesma porta. “Tenta outro checkpoint” sem porta nova não reabre |
| Classe | teste que rasteriza Markdown/texto conhecido → pixmap → RapidOCR de verdade, **sem** `OCR_FAKE`. Mock de motor não conta |

Paths previstos: `ingest/ocr.py` (API do RapidOCR pinada pelo teste),
`tests/test_ocr_motor.py` com marker `ocr`. Não toca `retrieve/`, despachante,
`[padrao]`.

Se a API do `rapidocr_onnxruntime` não for a tuple/dict que o código adivinha,
o teste quebra **aqui**, barato, em vez de no acervo de 10 GB.

**Medido em 27/08/2026**, desktop, `rapidocr-onnxruntime==1.4.4`, raster
`Matrix(2, 2)`, fixture VCE gerado no teste, **sem** `OCR_FAKE`. Identificador
`NN-VCE-001` volta exato; a frase plantada também. API observada:
`(linhas, elapsed)` com `linhas = [[box, text, confidence], ...]`. Hipótese
**não** refutada. O.2 pode começar depois deste merge. Ofício antigo, página
mista e dpi continuam O.2; o dourado continua O.3.

### F4-O.2 — a unidade é a página, o raster cabe na máquina · desktop

Só começa com F4-O.1 verde. Senão estamos afinando dpi de um motor que não lê PT.

| Campo | Valor |
|---|---|
| Serve base desconhecida | ofício com capa nativa e miolo scan não some; scan de dezenas de páginas não estoura o notebook |
| Hipótese | (a) página com imagem grande e < N chars extraíveis entra na fila mesmo quando o arquivo no total tem texto; (b) raster ≥ 200 dpi (não 144) no identificador plantado em corpo 10 pt; (c) uma página de cada vez na RAM, teto do `orcamento.py` |
| Efeito mínimo | (a) PDF sintético misto: a página-foto vira trecho, a nativa **não** passa pelo OCR; (b) identificador 10 pt recuperado a 200 dpi e **não** a 72 dpi no mesmo fixture — senão o dpi não é a alavanca; (c) pico de RAM da fase OCR ≤ teto derivado, medido no teste com N páginas sintéticas, sem Job Object de 8 GB de verdade |
| Orçamento | um braço por hipótese, três testes, sem grade de dpi |
| Encerramento | (a) ou (b) empata ⇒ não adota essa alavanca, registra. Não “mede mais páginas” |
| Classe | detector **por página** no parser de PDF (não só média do arquivo); raster página a página (hoje `_imagens_das_paginas` copia o documento inteiro); dpi/orçamento lidos de `index/orcamento.py` |

Paths previstos: `ingest/parsers/pdf.py` (sinal por página — **sobe versão do
parser** se o texto extraído das páginas nativas não mudar; se mudar, bump),
`ingest/ocr.py`, `index/orcamento.py` (teto de RAM por página, sem novo preset
de leigo). `parsers/__init__.py` só se a versão exigir — combinar, é um de cada
vez.

Não reconstruir heading a partir do OCR neste pacote: isso muda chunk e pede
número. Um bloco por página com `locator=p. N` continua até o F4-O.3 dizer o
contrário.

**Medido em 27/08/2026**, desktop, três braços, um por hipótese:

- **(a) adotada.** PDF misto (capa nativa + página-foto): a nativa vira trecho
  sem passar pelo motor; a foto entra na fila e vira trecho com o extra. Sem
  `--ocr` a capa já é buscável. Versão do parser de PDF **não** subiu: o texto
  das páginas nativas não mudou.
- **(b) refutada.** Identificador `NN-VCE-001` em corpo 10 pt, Helvetica,
  RapidOCR 1.4.4: lê em **72 dpi e em 200 dpi**. 200 dpi não é a alavanca.
  Raster de produção permanece `Matrix(2,2)` = 144 dpi. Não se mede outra
  fonte/tamanho neste pacote.
- **(c) adotada.** Raster é um gerador: 8 páginas-scan, pico de 1 pixmap vivo.
  Teto = `ram_parse_mb` do `orcamento.py` (256 MB na máquina de 8 GB). Página
  que não cabe cai para 72 dpi, nunca abaixo.

### F4-O.3 — o dourado corporativo, como regressão · notebook

| Campo | Valor |
|---|---|
| Serve base desconhecida | **não**, sozinho. É o piso deste acervo. Fecha o dossiê (`g015`/`g025`/`g048`) e não escolhe `[padrao]` (regra 10) |
| Hipótese | com F4-O.1+O.2 em `main` e `--ocr`, recall@5 do trio ≥ 2/3, e recall@1 agregado do `dourado-v1` não cai além do ruído |
| Efeito mínimo | fatia = as três perguntas `fora_de_escopo: ocr` (n=3). 2/3 é o dossiê. n=3 é ruído alto: o veredito é **binário por pergunta** (entrou no top-5 ou não) + Δ agregado do dourado com IC95 do `E5`. Sem o IC, não se adota |
| Orçamento | uma medição `--entregue`, com e sem OCR, no índice corporativo. Braço assimétrico |
| Encerramento | empate no agregado **ou** menos de 2 das 3 no top-5 ⇒ não promove OCR a padrão de passada. Fica `[indexacao] ocr` opt-in. “Meça mais perguntas” não reabre |
| Classe | as três perdem `fora_de_escopo: ocr` **ou** o relatório declara que o motor não alcança este acervo |

Desktop não inventa esses números. O notebook puxa `main` com O.1+O.2, mede,
escreve o doc. Sem O.1 verde, O.3 não começa.

---

## Ordem e o que não fazer

```
F4-O.0  porta (já)          ──► F4-O.1  motor real
                                 │
                                 ▼
                            F4-O.2  página + dpi + RAM
                                 │
                                 ▼
                            F4-O.3  dourado (notebook)
```

- **Não** ligar `ocr = true` em `[padrao]` / `config.example.toml` antes do O.3.
  O padrão continua desligado: custo e qualidade não foram medidos.
- **Não** varrer motores (EasyOCR, Docling, Paddle) no O.1. Um motor, uma porta.
  Docling é `R1.5`, pacote outro.
- **Não** OCR no parser barato da primeira onda. A fase depois do texto fica.
- **Não** commitar PDF de acervo. Fixture = VCE, gerado no teste.
- **Não** tratar Tesseract como extra do pip até o O.1 decidir. `pytesseract`
  hoje **não** está no `[ocr]`; o fallback no código é declaração, não rota
  testada.

---

## O que o leigo vê, até lá

`docs/comecar.md` depois do O.1: o extra lê com RapidOCR e um identificador
impresso volta intacto; ofício antigo e página mista ainda não foram medidos.
Sem extra o resto não muda.

---

## Paths deste planejamento

`docs/plano-ocr.md` (este), `ROADMAP.md` (F4-O partido em 0/1/2/3),
`docs/colaboracao.md` §6, `docs/comecar.md` (uma ressalva). Zero código de
motor. `ROADMAP.md` é um de cada vez e volta no merge.
