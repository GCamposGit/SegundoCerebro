# F4-O.3 — dourado de OCR, 02/09/2026

**Máquina:** notebook i7-14700HX, 34 GB, 15 GB livres, Windows 11, tomada.
**Índice:** corporativo, 2.156 documentos. **Motor:** RapidOCR 1.4.4, extra
instalado nesta sessão. **Não** é o 1355U de 28/08.

Laboratório: fecha o dossiê (`g015`/`g025`/`g048`) e **não** escolhe `[padrao]`
(regra 10). Relatório por pergunta fica gitignorado.

## O que a passada curta fez

37 documentos `digitalizado=1`, todos `vazio`, 399 páginas. Não foi o acervo
inteiro. `indexer --ocr` **não** rodou: `ram_parse_mb=1024` (Job Object) faz o
RapidOCR devolver `recurso` numa página de 0,26 MB — medido antes da fila.
O 28/08 (filho que reimporta o encoder) continua no laço do indexador; não foi
tocado (desktop, ainda commitando).

Instrumento: `eval/ocr_fila.py`, `__main__` leve, `parse_isolado` **sem**
`ram_mb`, encoder só no pai depois do parse. Classe: filho de OCR que carrega
`fastembed` mede a janela, não o motor. Porta:
`eval/test_ocr_fila.py::test_modulo_nao_importa_encoder_nem_indexer`.

| | |
|---|---:|
| fila | 37 |
| `ok` com `ocr:1` | 22 |
| continuam `vazio` | 15 |
| chunks novos | 218 (98.326 → 98.544) |
| documentos alcançáveis | 1.900 → 1.922 |

As 15 falhas não gravaram: o registro ficou com o detalhe antigo
(`digitalizado, sem camada de texto`). O motor não produziu trecho indexável.

`pytest -m ocr`: 7 passaram (o motor lê o fixture VCE). 2 falharam a 560 MB de
Job Object com aborto OpenBLAS **não** classificado como `recurso`. A branch
remota `codex/q15b-ocr-memory-failures` ainda existe; regra 8 — reportar, não
corrigir `isolamento.py`.

## Hipótese, teto, veredito

Hipótese: com `--ocr`, 2 das 3 perguntas `fora_de_escopo: ocr` entram no top-5,
e o recall@1 agregado do `dourado-v1` não cai além do ruído.

| id | fonte esperada depois da passada |
|---|---|
| g015 | 0/1 no índice (`vazio`, `digitalizado=1`, parser `1`) |
| g025 | 0/1 igual |
| g048 | 1/2 — a nativa já estava `ok`; o scan continua `vazio` |

**0 de 3 no top-5**, porque 2 de 3 fontes nem existem como trecho. O teto 2/3
não se cumpre. Não se tira `fora_de_escopo: ocr`.

Agregado, caminho entregue, `eval.comparar --entregue --indice index-antes-o3`
(cópia de antes da fila) contra o índice depois, n=59, 02/09/2026:

Δ recall@1 **+0,000 [+0,000, +0,000]** · Δ MRR **+0,000 [+0,000, +0,000]** ·
Δ nDCG@5 **+0,000 [+0,000, +0,000]**. Empate. Porta 5 passa (0 armadilha, 0
sumiu do 1º). Uma pergunta (g040) moveu 17→19; o Δ agregado é zero a três
casas. Cobertura do dourado recalculada: teto 38,4%, piso 3,3%.

## Encerramento

Menos de 2/3 no top-5 **e** empate no agregado. OCR **não** vira padrão de
passada. Fica `[indexacao] ocr` opt-in. “Meça mais perguntas” não reabre.

O motor alcança 22 dos 37 digitalizados desta base e **não** alcança as três
fontes do dossiê. Declaração do pacote: *motor não alcança este acervo* no
recorte que o dourado usa para decidir.

## O que o desktop precisa saber (regra 8)

1. `indexer --ocr` nesta máquina, com o teto de 1024 MB, classifica RapidOCR
   como `recurso` em PDF de uma página. A fila curta só andou porque o
   instrumento **não** passa `ram_mb`.
2. Spawn a partir de `python -m segundocerebro.index.indexer` continua
   reimportando `embeddings` no filho — o laudo de 28/08. Não mexi no laço.
3. Dois testes `-m ocr` a 560 MB ainda morrem em OpenBLAS abort sem
   `MOTIVO_RECURSO`.
