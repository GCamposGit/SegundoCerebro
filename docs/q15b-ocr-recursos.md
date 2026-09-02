# Q15.b — falha nativa de memória não é documento vazio

Setup: Desktop, Windows, 02/09/2026. Corpus: somente PDFs sintéticos VCE.
Notebook original desativado; sem acervo ou dourado privado.

## Contrato e pesquisa

Defeito para base desconhecida: um scan legível podia terminar `vazio`, sem
quarentena, quando o processo de OCR não conseguia alocar memória.
Aceite binário: OCR sem texto e com falta de memória deve produzir erro de
recurso, nunca vazio; com memória suficiente o mesmo identificador deve ser
lido. Branco legítimo continua vazio; texto anterior e nova tentativa sobrevivem.
Qualquer violação bloqueia encerramento. Não mede ranking nem varre modelos.

Orçamento: reprodução intercalada 560/2048/560 MB, matriz barata de exceções e
páginas, teste real de subprocesso Windows e regressão completa. Classe
generalizada: falhas nativas encapsuladas confundidas com ausência de texto,
incluindo combinações com páginas brancas ou ilegíveis.

Paths fechados: `src/segundocerebro/ingest/ocr.py`,
`src/segundocerebro/ingest/ocr_recursos.py`, `tests/test_ocr_recursos.py`,
`tests/test_ocr_motor.py`, `tests/test_falha_de_ambiente.py`, `ROADMAP.md`,
`CLAUDE.md` e este documento. Diagnóstico temporário em diretório `index-*`
ignorado pelo Git. Não altera modelos, DPI, limites, parsers, ranking,
chunking, isolamento de processos ou dados privados.

Pesquisa com dois subagentes econômicos, conferida nas fontes primárias:

- [RapidOCR 1.4.4, infer_engine.py](https://github.com/RapidAI/RapidOCR/blob/v1.4.4/python/rapidocr_onnxruntime/utils/infer_engine.py): encapsula erro de inferência preservando `__cause__`. Reutilizar essa cadeia, sem interpretar o traceback inteiro nem trocar a biblioteca.
- [ONNX Runtime 1.18, alocador](https://github.com/microsoft/onnxruntime/blob/v1.18.0/onnxruntime/core/framework/bfc_arena.cc): falhas de alocação podem virar status/exceções nativas, não `MemoryError` Python. Classificar tipo nativo mais sinal específico de alocação; não todo erro de inferência.
- [OpenCV, códigos de erro](https://github.com/opencv/opencv/blob/4.12.0/modules/core/include/opencv2/core/base.hpp): `StsNoMem` é código estruturado -4. Preferir código a texto genérico.
- [Microsoft, limite de memória do Job Object](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information): limita memória comprometida do processo. O limite existente permanece; completion ports não são necessários para a exceção observada.

## Reprodução antes da correção

Python 3.12.10, RapidOCR 1.4.4, ONNX Runtime 1.18.0, CPU; processo isolado real,
sem motor falso e sem cache. Scan de uma página gerado no J.f:

- 560 MB: `vazio`, zero caracteres.
- 2048 MB: `ok`, 504 caracteres.
- 560 MB: novamente `vazio`, zero caracteres.

O erro original era `onnxruntime...RuntimeException`, com falha de alocação
durante um nó Clip. O RapidOCR o encapsulava em `ONNXRuntimeError`; o `except`
genérico por página descartava a falha. Não era um retorno vazio do detector.
Antes da correção: quatro falhas nos testes de contrato; o teste real Windows
também reprovou a 560 MB, com controles de texto e página branca aprovados.

## Resultado e limites

Após a correção, o mesmo scan de 504 caracteres, na mesma sequência de limites,
retornou `erro` de recurso / `ok` com 504 caracteres / `erro` de recurso.
Não aumentamos o teto para mascarar o defeito.

- 68 testes focados de OCR/ambiente/cache aprovados.
- 9 testes com o extra OCR real aprovados, incluindo identificação, branco,
  subprocessos limitados e ciclo indexar → quarentena → rotina sem OCR →
  recuperação. Só o encoder é dublê nesse ciclo; OCR, cache e registro são reais.
- A matriz barata cobre sinais ONNX, código OpenCV, exceções encadeadas/cíclicas,
  negativos e páginas sem texto. Os testes novos reprovaram antes do conserto.
- Suíte completa: **1.703 aprovados, 17 pulados, 60 desmarcados**, em 237,37 s.
  Entre os pulados, um teste antigo de OCR declarou falta de recurso (janela
  de aproximadamente 2 GB livres); os nove testes específicos com motor real
  não pularam. Os demais incluem corpus/dourado privado e lista local ausentes.
- Ruff e Pyright aprovados.

Reutiliza a política existente: erro de recurso não aposenta o arquivo; a
próxima tentativa respeita o backoff e requer uma passada com OCR. PDF misto
mantém texto nativo e fica elegível para OCR, sem carimbar uma extração completa.
Quando outras páginas OCR produziram texto, mantém-se a política anterior de
resultado parcial com aviso; completude/reprocessamento de OCR parcial não é
uma nova garantia deste pacote. Falhas sem sinal reconhecido de memória seguem
o tratamento anterior de página ilegível; não classificar tudo como RAM.

`ocr:1` permanece: não mudou a extração bem-sucedida nem a política de cache de
resultados parciais. O falso vazio antigo usava a rota nativa; uma passada com
OCR já ignora esse cache. O teste de cache confirma que uma falha não grava um
novo sucesso e que a recuperação posterior passa a ser reutilizável.

O pacote corrige o diagnóstico e a nova tentativa, não faz o modelo caber em
560 MB. Sem ganho de retrieval declarado (dourado privado indisponível), sem
mudança do resultado histórico de desempenho de J.f e sem novo modelo OCR.
