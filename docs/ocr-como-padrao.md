# OCR é parte da indexação, não um extra que o leigo descobre depois

**Decisão de produto, 02/09/2026.** Um PDF digitalizado que entra `vazio` com a
barra verde é o defeito da régua de ouro: o leigo aponta uma pasta, indexa, e
só percebe na primeira pergunta que o ofício não está. `--ocr` e
`pip install .[ocr]` são o mesmo silêncio com roupa de opção.

O `F4-O.3` mediu o motor neste acervo e **não** autorizou `[padrao]` de ranking.
Isso não autoriza deixar o scan de fora. Ranking é invariante 4; visibilidade do
documento é a porta de entrada. Os dois não se trocam.

## O que estava quebrado, com número

1. **O motor não entra na instalação.** `rapidocr-onnxruntime` era extra. Sem ele
   a passada é idêntica à de hoje e o log diz `pip install [ocr]` — que o leigo
   não lê.
2. **A flag default é off.** `[indexacao] ocr = false`. Quem não sabe a flag
   indexa 200 scans como `vazio`.
3. **O filho do indexador carrega o encoder.** `indexer.py` → `cli.py` →
   `embeddings.py` → `fastembed`. Spawn no Windows reimporta o `__main__`. No
   1355U isso quarentenava o acervo (28/08). `eval.ocr_fila` andou porque o
   módulo **não** importa o encoder.
4. **O teto de parse (1024 MB) mata o OCR.** Job Object de `ram_parse_mb`
   devolve `recurso` numa página de 0,26 MB. Medido 02/09. ONNX/OpenBLAS pede
   arena, não o tamanho do PDF. O teste a 560 MB que aborta OpenBLAS prova
   classificação de falha, **não** que OCR seja opcional.
5. **O motor não lê tudo.** 22/37 digitalizados viraram trecho; as três fontes
   do dossiê continuaram `vazio`. Isso é qualidade do motor, e fica visível
   (status `vazio` depois de tentar `ocr:1`), não escondido atrás de uma flag.

## Correção, em ordem

| Fatia | O que muda | Pronto quando |
|---|---|---|
| **A — o filho é leve** | `cli.py` não importa `embeddings`; `indexer.py` não importa `Embedder` no módulo | teste AST: import de `indexer` não carrega `fastembed` |
| **B — o teto de parse não vale no OCR** | `parse_isolado(..., ocr=True)` **sem** `ram_mb` | 1 página VCE isolada sai `ok`, não `recurso` |
| **C — aborto OpenBLAS é recurso** | stderr com `OpenBLAS` + `Memory allocation` prefixa `MOTIVO_RECURSO` | o teste a 560 MB classifica; não exige o motor caber em 560 MB |
| **D — default on** | `Indexacao.ocr = True`; RapidOCR nas `dependencies`; `--sem-ocr` para recusar | `pip install -e .` + indexar sem flag percorre a fila digitalizado |
| **E — motor ausente é erro** | `motor_de_ocr() is None` com OCR ligado: `log.error`, não no-op | a passada não mente "indexado" com scan na fila |

O extra `[ocr]` permanece como alias, para quem já tem o comando antigo.

## O que isto não decide

Não troca RapidOCR por PP-OCRv6 (F4-O.4, futuro). Não zera as 15 páginas que o
motor atual não leu — declara a tentativa (`ocr:1` ou a fila continua visível).
Não mexe em peso de ranking.

## Classe

> Scan na pasta do leigo que termina `vazio` sem o produto ter tentado OCR, ou
> com a tentativa morta por teto de parse/encoder no filho, é falha da
> indexação, não opção do usuário.

Porta: `tests/test_ocr_padrao.py` — módulo do indexador sem `fastembed`; default
`ocr=True`; `parse_isolado` de OCR sem `ram_mb=`.
