# `F4-O.3` bloqueada: sob pressão de memória o indexador **quarentena o acervo**

**Data:** 28/08/2026 · **Máquina:** notebook corporativo i7-1355U (2P+8E), 16,8 GB,
Windows 11, recém-reiniciado com o máximo de memória livre possível · **Índice:**
corporativo, 2.156 documentos, 98.326 chunks · **Motor:** `rapidocr-onnxruntime`
instalado e verde

O pacote não fechou, e o que o bloqueia **não é** o dourado, **não é** o motor de
OCR e **não é** o corpus. É o indexador nesta máquina — e o modo de falha é o pior
da régua de prontidão: ele não trava nem falha, ele **destrói o índice devagar,
mostrando 0% de CPU.**

## O que foi verificado antes de medir

| verificação | resultado |
|---|---|
| motor real de OCR (`pytest -m ocr`, do `F4-O.1`) | **4 passando**, 21 s, nesta máquina |
| documentos digitalizados no acervo | **37**, todos `status=vazio`, zero chunk |
| PDFs que precisariam de reparse por versão de parser | **0 de 665** — o `F4-O.2` não subiu a versão |
| perguntas `fora_de_escopo: ocr` no dourado | 3 (`g015`, `g025`, `g048`) |
| índice congelado como braço `antes` | `index-sem-ocr`, 0,91 GB, cópia byte a byte |

Ou seja: o trabalho real da passada eram **37 documentos**. A estimativa de "11 d
20 h" que o indexador imprime é o pior caso não calibrado, e não é o problema.

## As duas passadas, e a mesma assinatura

| passada | escopo | resultado |
|---|---|---|
| 1 | acervo inteiro (2.153 arquivos) | trava em < 1 min. `MemoryError` no subprocesso de parse, durante `import fastembed` |
| 2 | `--so-extensao .pdf` (666 arquivos) | trava igual. **Sem** `MemoryError`: o parse isolado **estoura 61 s** e o documento vai para **quarentena** |

Nas duas, o processo principal fica em **0% de CPU** segurando ~2 GB, e o contador
de chunks não se move. Monitorado por 100 s na segunda: zero progresso, cinco
processos vivos, nenhum consumindo CPU.

## A cadeia causal, com a evidência

1. **`isolamento.deve_isolar` manda todo PDF para um subprocesso.** É por extensão,
   e não há chave para desligar.
2. **O filho reimporta o pacote inteiro.** O traceback é explícito:
   `multiprocessing.spawn` → `_fixup_main_from_name` →
   `runpy.run_module('segundocerebro.index.indexer')` → `indexer.py:47` →
   `embeddings.py:27` → `import fastembed`. **Para parsear um documento, o filho
   carrega o encoder.**
3. **O OpenBLAS não consegue alocar no filho** —
   `OpenBLAS error: Memory allocation still failed after 10 retries, giving up` —
   porque o pai já segura o `e5-large` e a máquina está em ~85–90%.
4. **O filho nunca responde.** O pai espera o timeout de 61 s e **quarentena o
   documento**.
5. **Repete para o próximo.** A 61 s por documento, 666 PDFs são 11 h de timeout
   puro — e cada um deles sai do índice.

O ponto 5 é o que faz isto ser grave e não apenas lento: **a passada não falha, ela
esvazia o índice a um documento por minuto**, com a barra andando e a CPU em zero.
Pela régua de prontidão, item 2, *falhar é aceitável; travar ou mentir em silêncio,
não* — e isto é a terceira coisa, que a régua não previa: **destruir em silêncio.**

Medido nas duas tentativas antes de eu matar: 1 documento saiu de `ok`, 5 chunks
perdidos, 2 quarentenas novas. O índice foi **restaurado byte a byte** de
`index-sem-ocr`, e conferido: 1.900 `ok`, 98.326 chunks, `erro` de volta a 4.

## O teto de RAM do `F4-O.2` não vale nesta plataforma

`isolamento._worker_parse` aplica o orçamento com
`resource.setrlimit(RLIMIT_AS, ...)` sob `if ram_bytes > 0 and os.name != "nt"`.
No Windows não há `resource`, então **o teto simplesmente não é aplicado** — e o
Windows é a plataforma do produto. O `plano-ocr.md` já declarava que a hipótese (c)
seria medida "sem Job Object de 8 GB de verdade"; esta medição é a evidência de que
a diferença importa: é exatamente o filho sem teto que derruba a passada.

Não é crítica ao pacote — é o número que faltava para decidir se o Job Object vale
o custo. Agora há um.

## O que isto muda para quem instala amanhã

Direto, e é a régua de ouro: **um notebook de 16 GB com o navegador aberto é a
máquina do leigo**, não um caso extremo. Nesta máquina, recém-reiniciada e com o
máximo de memória livre que ela dá, a passada com `--ocr` não completa e piora o
índice. O leigo veria a barra andando e a busca piorando.

Os dois testes de `tests/test_ocr.py` que oscilam entre passar e falhar nesta
sessão são a **canária** desse mesmo defeito. Rodando só
`tests/test_ocr.py tests/test_watcher.py`, a cadeia aparece inteira em miniatura:

```
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
WARNING isolamento: parse isolado morreu código 1: ...oficio.pdf
WARNING indexer:    quarentena (subprocesso morreu (código 1), tentativa 1): oficio.pdf
```

É o mesmo mecanismo do acervo, num PDF de 0,02 MB. Vale tratar como sinal, não
como ruído.

**E a fragilidade se espalhou, com uma ressalva de método.** Depois de instalar o
extra `[ocr]`, a suíte completa passou de 3 falhas para 8: entraram 6 testes de
`tests/test_watcher.py`. Eles passam **isolados** (13/13) e passam junto com
`test_ocr.py` (24/24) — só caem sob a pressão acumulada de 1.250 testes, com a
máquina a 81% em repouso.

A causa provável é o extra ter subido a linha de base de memória por processo, mas
**eu não isolei isso** — não desinstalei o extra para medir os dois estados, porque
o extra não vai no CI (`plano-ocr.md`) e portanto a conclusão não mudaria nenhuma
decisão de vocês. Fica registrado como observação com a causa declarada como não
verificada, e não como achado.

## Estado da `F4-O.3`

**Bloqueada, não refutada.** Nada foi medido sobre `g015`/`g025`/`g048`: elas
continuam `fora_de_escopo: ocr`, e a anotação **não** foi removida — removê-la sem
a fonte indexada criaria a fatia vazia que o `F4-P.1` acabou de ensinar a não
criar.

O que já está pronto para quando a passada completar:

- o índice `antes` congelado (`index-sem-ocr`), fora do Git;
- `eval.comparar --indice-depois`, entregue neste PR — a medição é "com e sem OCR",
  que é diferença de **índice** e não de recuperador, e a ferramenta só aceitava um
  índice para os dois braços.

## O que destrava, em ordem de custo

1. **Não isolar o parse quando o filho não couber** — ou reusar um processo de
   parse em vez de um por documento. O custo real não é o OCR: é reimportar o
   encoder por documento.
2. **Job Object no Windows**, para o teto do `orcamento.py` valer onde o produto
   roda. Sem ele o `RLIMIT_AS` é um teto que só existe em teste de POSIX.
3. **Falhar alto quando o filho morre por memória**, em vez de quarentenar. Um
   documento que não pôde ser lido por falta de RAM não é um documento defeituoso,
   e tratá-los igual é o que transforma pressão de memória em perda de índice.

Os três são de `index/` e `isolamento.py`, que são do desktop. Reportado, não
consertado (regra 8).

## A classe (regra 12)

> **Falha de recurso no subprocesso é indistinguível de documento defeituoso, e o
> tratamento dos dois é o mesmo: quarentena.** Um corpus inteiro pode sair do
> índice sem uma linha de erro, porque cada caso isolado parece um arquivo ruim.

Não fecho a classe neste PR porque o conserto é do outro lado. O que entrego é a
evidência e o número: 61 s por documento, 666 documentos, 0% de CPU, e o índice
piorando durante todo o processo.
