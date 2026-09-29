# Extração canônica, gráficos e imagens

**29/09/2026.** `GRAFICO-CACHE` foi entregue no PR #126 (commit `7646303`).
`BUSCA-BURACO` foi entregue no PR #128 (merge `562b682`). `GRAFICO-EMBED` foi entregue no PR #130 (merge `83397b5`).
`IMAGEM-RASTER` foi entregue no PR #132, `PLANILHA-CELULA` no PR #133 e
`PLANILHA-LEITURA` no PR #134 (merge `748808d`). `CANONICO-BACKFILL` está em execução;
`HARDWARE-INICIO` continua proposto.
O OCR de imagens segue condicionado a um kernel CUDA executado; sem prova, não lê imagens.
O diagnóstico compartilhado de hardware e embedding segue em
`HARDWARE-INICIO`. O ticket que um agente pega é o bloco `[[pacote]]` em
[`pacotes-ativos.toml`](pacotes-ativos.toml); este arquivo é o contrato.
[`ROADMAP.md`](../ROADMAP.md) continua história.

Não há mudança de peso, de chunker nem de `[padrao]`. Aceite é fixture
sintética (vocabulário VCE). Índice e pastas reais não entram no Git e não são
o teste do pacote. Passada no índice vivo, quando existir, é passo operacional
depois do merge, com `--so-extensao`, nunca reindexação da árvore inteira.

## Como pegar um ticket

1. Escolha o primeiro da ordem cujo `dependencias` já está `entregue` e cujo
   path não tem outro escritor. `GRAFICO-CACHE` está entregue. `BUSCA-BURACO`
   também está entregue e não toca parser. `GRAFICO-EMBED` está entregue no PR #130.
2. No máximo um pacote `em_execucao` por path; só um escritor pode editar um
   path compartilhado por vez.
3. Branch `codex/<id>` a partir de `main`. Não commitar em `main`.
4. O teste novo tem de falhar com o código antigo e passar com o novo.
5. Subir a versão do parser se o texto emitido ou os metadados persistidos mudarem.
   `.pptx`/`.pptm` sobem para `4` e `.ppt` para `5` em `GRAFICO-EMBED`, pois o
   Parse Store mantém metadados junto ao texto. Refatoração sem mudança persistida
   não sobe versão.

## O que já está no produto

A réplica `.md` ao lado do arquivo foi recusada: escreveria na pasta do
usuário. O substituto é o Parse Store (`ingest/parse_store.py`): Markdown
canônico mais blocos, comprimido dentro do índice. `get_document` e
`pack_folder` leem dali. `search` lê trechos e vetores, não o store.

`PARSER-TEXTO-OCULTO` (PR #119) colhe texto que o python-pptx não visita:
SmartArt (`ppt/diagrams`, tag `a:t`), caixas, cabeçalho e o título de gráfico
quando ele também está numa tag `t`. O locator `grafico` já existe.

OCR de página de PDF entra quando há pouco texto e uma imagem
(`pagina_precisa_ocr`). PNG/JPEG embutidos em PPTX e DOCX passam pelo RapidOCR
somente quando a sonda roda um kernel CUDA; o pacote `IMAGEM-RASTER` limita o
custo e declara o corte. Arquivos de imagem soltos e EMF/WMF/WDP/SVG continuam
fora.

## Gráficos e imagens — o que falta

O walker de slide lê forma com `text_frame`, grupo e tabela. Gráfico é
`graphicFrame`: não tem `text_frame`. Abrir o PPTX com python-pptx e ler
`.text` reproduz o vazio. Os números do gráfico nativo estão no XML do chart,
na tag `c:v` (`c:numCache` / `c:strCache`), que `ooxml_texto.py` não colhe —
ele só aceita a tag local `t`.

Censo estrutural em 24/09/2026, na base já indexada, só nomes de parte ZIP e
contagem de tags, sem texto e sem caminho:

| Recorte (`ok`, arquivo local) | Contagem |
|---|---:|
| PPTX | 103 |
| PPTX com parte `charts/` | 31, e os 31 têm pelo menos um `c:v` |
| Desses 31, com pelo menos um chart sem `c:v` | 29 |
| Desses 31, com tag `t` no chart (o que o produto já pode ver) | 17 |
| PPTX com `embeddings/` | 50 |
| PPTX com raster em `media/` | 94 (2.100 PNG, 230 JPEG, 99 JPG) |
| PPTX com EMF/WMF | 58 |
| PPTX com diagrama (SmartArt, já coberto) | 4 |
| DOCX com raster | 108 de 366 |
| XLSX com chart | 34 de 324, também com `c:v` |

Leitura: o conserto barato é colher `c:v` e devolver série, categoria e valor
num bloco `grafico`. Isso alcança todo deck `ok` que tem gráfico nativo com
cache. Não alcança o chart sem cache (a planilha embutida em `embeddings/`)
nem o gráfico colado como foto. Foto é OCR, e é o pacote seguinte, não o
primeiro: há milhares de rasters, muitos decorativos, e EMF/WDP/SVG não são
entrada do RapidOCR.

No XLSX o chart costuma repetir células que o parser de planilha já viu. O
buraco novo é o PPTX. Coluna de medida em aba grande continua de fora do
índice de propósito; isso é `PLANILHA-CELULA`, não este diagnóstico.

## Ordem

| Ordem | Id | Pode começar | Por quê nesta posição |
|---|---|---|---|
| 1 | `GRAFICO-CACHE` | entregue no PR #126 | O número do gráfico nativo entra no texto |
| 1 | `BUSCA-BURACO` | entregue no PR #128 | A busca declara quando o índice não representa o documento completo |
| 2 | `GRAFICO-EMBED` | entregue no PR #130 (`83397b5`) | Chart sem `c:v`, lendo o xlsx embutido e preservando o aviso de digesto |
| — | `HARDWARE-INICIO` | proposto | Diagnóstico compartilhado para embedding e etapas sem sonda local, sem pin desta máquina |
| 3 | `IMAGEM-RASTER` | entregue no PR #132 | OCR só com kernel CUDA, até 12 imagens válidas por arquivo e 2 Mpx por imagem |
| 2 | `PLANILHA-CELULA` | entregue no PR #133 | Guarda a célula que o digesto descarta, sem novo vetor |
| 3 | `PLANILHA-LEITURA` | entregue no PR #134 (`748808d`) | Tool MCP com cursor sobre essa tabela |
| último operacional | `CANONICO-BACKFILL` | em execução; a passada só depois dos bumps de parser | Preenche o store do que já está nos trechos. Rodar antes congela texto velho |

`CANONICO-BACKFILL` não inclui PPTX. PPTX só volta ao índice na passada
operacional posterior ao bump, restrita a `.pptx,.pptm`.

## Contratos

### `GRAFICO-CACHE`

Problema: número e rótulo em `c:v` não viram bloco. Título em `a:t` já vira.

Perguntas: qualquer pasta com PPTX nativo; efeito mínimo é o fixture, não um
Δ de ranking; empate não se aplica — o teste é binário.

Paths: `ingest/parsers/ooxml_texto.py`, `ingest/parsers/slides.py`,
`tests/test_ingest.py`. Dono: notebook. Dependências: nenhuma.

Aceite: um PPTX sintético com `c:ser`, categoria e `c:v` produz bloco
`locator=grafico` contendo série, categoria e valor. O mesmo arquivo sem a
parte de chart continua só com o texto do frame. Tag `t` dentro de `w:del`
continua de fora. Subir `.pptx`/`.pptm` para a versão 3 e `.ppt` para a 4.

Fora: embeddings, OCR, reindexação viva, trocar o RapidOCR (`F4-O.4`).

### `GRAFICO-EMBED`

Problema: chart com fórmula `c:f` e sem `c:v` guarda a grade em
`ppt/embeddings/*.xlsx`. O parser de planilha já sabe ler esses bytes; ninguém
os entrega.

Paths: `ingest/parsers/slides.py`, `ingest/parsers/ooxml_texto.py` e teste em
`tests/test_ingest.py`. Dono: notebook. Depende de `GRAFICO-CACHE`.

Aceite: fixture com chart sem cache e um xlsx embutido devolve o valor
plantado, com locator `grafico`. Fixture que já tem `c:v` não duplica o
número. Aba embutida acima do limiar de digesto declara a mesma limitação que
a planilha solta. `.pptx`/`.pptm` passam de parser 3 para 4 e `.ppt` de 4 para 5
para invalidar metadados persistidos antes desta mudança.

Fora: OCR da figura do gráfico. Objeto OLE que não é xlsx.

### `IMAGEM-RASTER`

Problema: print e gráfico colado como PNG/JPEG não têm XML de texto. OCR hoje
só rasteriza página de PDF pobre em texto.

Medição real em 24/09/2026, RapidOCR do ambiente, sem gravar texto e sem abrir
placeholder. Inventário dos PPTX/DOCX locais com status `ok`: 2.756
PNG/JPEG/JPG em `media/`. 543 ficam abaixo de
100 px no lado menor. 2.202 passam desse piso. 431 desses passam de 2 milhões
de pixels ou de 1,5 MB e ficaram fora da amostra cronometrada.

O modelo em CPU levou 14 s para carregar, uma vez. Doze imagens estratificadas
por tamanho, já com o modelo quente: mediana **8,8 s**, média **15,9 s**,
máximo **44,6 s**. Nove das doze devolveram algum texto. Mediana vezes os
2.202 já dá **5,4 h** de CPU, e os 431 maiores não entraram na mediana.

A mesma amostra, nos mesmos tamanhos de pixel, rodou de novo na RTX 4070
Laptop com `onnxruntime-gpu` 1.29.0 e cuDNN 9, flags `det_use_cuda`,
`cls_use_cuda` e `rec_use_cuda`. As três sessões ficaram em
`CUDAExecutionProvider`. Aquecimento 3,8 s. Primeira passagem: mediana
**0,85 s**, média **1,12 s**, máximo **3,0 s**, soma **13,4 s**. A segunda,
com a placa já quente, mediana **0,79 s**. As mesmas nove imagens produziram
texto. A mediana da CPU era 10 vezes essa. Os 2.202 rasters do piso, por
essa mediana, caberiam em cerca de **31 min** nesta placa, ainda antes de
reembedar, e os 431 grandes continuam de fora da conta.

O `pip install` padrão continua em CPU e o extra `[gpu]` segue no pin Maxwell
1.18 do Desktop. O lote GPU já medido de 12 imagens levou 13,4 s no total, com
máximo observado de 3,0 s por imagem. A implementação limita cada documento a 12 imagens válidas: esse
limite é o tamanho do lote já medido e não uma afirmação de latência máxima de
qualquer arquivo real. Cada imagem também fica abaixo de 2 milhões de pixels e
1,5 MB; os ícones menores que 100 px continuam fora. O teste sintético marcado
`cuda` valida o kernel e reconhece o identificador plantado na máquina que tem
GPU. Nenhuma passada em índice ou acervo real faz parte do aceite do código.

Paths: `ingest/ocr.py`, `ingest/raster_ocr.py`, `ingest/parsers/slides.py`,
`ingest/parsers/word.py` e `tests/test_raster_ocr.py`. Dono: notebook. Depende
de `GRAFICO-EMBED`.

Aceite: slide cujo único conteúdo é um PNG com identificador VCE ganha bloco
com esse identificador e locator `imagem`. PNG e JPEG passam pelo mesmo caminho;
slide que já tem o mesmo texto no frame não ganha segunda cópia. Imagem abaixo
do piso de pixels não chama nem carrega o motor. Só imagens com até 2 Mpx e
1,5 MB são candidatas, e no máximo 12 imagens válidas por arquivo chegam ao
motor; quando há mais, `ocr_raster_limite` declara o corte. EMF, WMF, WDP e SVG
ficam declarados como não lidos. Falha de uma imagem não apaga texto já extraído.
Máquina sem kernel CUDA declara `sem_gpu` e não tenta OCR em CPU.

Fora: página de PDF que já tem parágrafo e também uma figura. Arquivo de
imagem solto (`.png` na pasta). Troca de motor. OCR dos 2.202 rasters.

### `BUSCA-BURACO`

Problema: `search` devolve trecho sem dizer se o documento está em digesto,
`placeholder`, `vazio` ou sem canônico. O agente abre o original.

Paths: `mcp/busca.py`, `mcp/overview.py`, `acesso/overview.py`, teste de
contrato da tool. Dono: notebook. Dependências: nenhuma. Não altera ordem de
ranking: o teste compara a lista de ids antes e depois no mesmo índice
sintético.

Aceite: hit cujo documento tem `abas_em_digesto`, status `placeholder` ou
`vazio` traz a limitação no payload. `overview` conta documentos `ok` sem
entrada de Parse Store encontrável pela chave atual, sem abrir o original.
Descrição de `search` diz para usar `incluir_versoes_antigas` na minuta antiga
e para não tratar ausência de trecho como licença para ler o arquivo por fora.

### `PLANILHA-CELULA`

Problema: aba acima de 5.000 linhas ou 20.000 células vira valores distintos
das primeiras colunas, e coluna de medida é descartada. `read_note` não tem a
linha.

Paths: `ingest/parsers/sheets.py`, `index/esquema.py`, o ponto de gravação do
indexador que persistir a tabela, teste de parser. Dono: desktop (esquema e
gravação; o parser de planilha fica declarado neste pacote). Dependências:
nenhuma de código. Não emitir um vetor por linha.

Aceite: fixture acima do limiar guarda aba, linha, coluna e o valor de medida
plantado. O número de blocos embedáveis continua o do digesto. Apagar a tabela
não apaga o original. Arquivo pequeno, que já é janela de linhas, não passa a
gravar a tabela inteira de novo.

### `PLANILHA-LEITURA`

Problema: a célula guardada precisa de uma leitura com cursor. Sem tool, o
agente continua no script.

Paths: módulo novo em `mcp/` e `acesso/`, mais o registro da tool em
`mcp/server.py` se a lista de tools for explícita. Dono: notebook. Depende de
`PLANILHA-CELULA`.

Aceite: a tool devolve o valor plantado, com arquivo e locator, e cursor
quando o recorte excede o orçamento. Uma chamada não devolve a aba inteira.
Nome da tool entra na descrição que manda `search` usar a leitura em vez de
abrir o xlsx.

### `CANONICO-BACKFILL`

Problema: em 24/09/2026, 788 documentos `ok` não têm canônico que a chave
atual abre. TXT, MD e MSG estão na versão 1 nos dois lados, então o indexador
nunca mais os visita e `get_document` reparseia o original (teto 50 MB, 60 s).
PDF e DOCX da passada recente estão cobertos. XLSX está no parser 1 com o
código no 2: isso é repesca normal do indexador, não este comando.

Paths: módulo novo `index/canonico_backfill.py` e a flag na CLI. Não crescer
`indexer.py` além do teto já declarado. Dono: desktop. Dependências de código:
nenhuma. A passada viva espera os bumps de parser acima.

Aceite: fixture TXT indexado, store apagado, comando regrava o `.canon.zz` e
não muda a contagem de vetores. Extensão cujo `documentos.parser` difere do
código não entra nessa passada. `.ppt`, `.pptx` e `.pptm` ficam explicitamente
fora.

Uso: `segundocerebro-backfill-canonico --base <id>` (ou `--config` e `--indice`
para sobrepor os caminhos). O registro `registro.db` é aberto somente para
leitura; a única escrita é no Parse Store. O comando não inicia embedding, não
altera chunks/vetores e não hidrata placeholders de nuvem. A passada real fica
para depois dos bumps de parser; a fixture valida o fluxo agora.

### `HARDWARE-INICIO`

Problema: o produto tem de arrancar numa máquina que nunca vimos e numa pasta
que nunca vimos. As duas máquinas de desenvolvimento já divergem, e essa
divergência é o ensaio do usuário novo. Nesta venv o OCR foi medido em CPU
porque o wheel era o de CPU. O Python de base da mesma máquina já tinha outro
ONNX com CUDA. O Desktop tem um terceiro pin, o 1.18, porque a GTX 980 Ti não
aceita o wheel novo. Nada disso pode virar o padrão do clone.

O que já existe e não basta: `index/cuda_runtime.py` diagnostica o embedding
quando alguém pede CUDA, e o padrão continua CPU. O OCR não consulta esse
diagnóstico. Nome de provider na lista não é prova de que o kernel roda: a
1.29 anunciou `CUDAExecutionProvider` e o primeiro Conv falhou até o cuDNN 9
estar carregável.

Contrato de inicialização compartilhada, para uso de CUDA pelo embedding e por
qualquer etapa que não tenha uma sonda local própria:

- Um diagnóstico na inicialização do indexador e do servidor, compartilhado
  por parse, OCR e embedding. Relata CPU, GPU (nome, compute, VRAM), build do
  ONNX, providers que de fato executam um kernel mínimo, e o motivo da recusa.
- Cada etapa pergunta a esse diagnóstico. Parse de Office fica em CPU. OCR e
  embedding usam CUDA só quando o kernel mínimo passou e cabe na VRAM. Máquina
  sem placa, ou placa que falhou ao carregar, fica em CPU e diz isso.
- A rota de parser por tipo de arquivo (nativo, LibreOffice, OCR, recusa)
  sai do mesmo diagnóstico e do arquivo. A escolha fica gravada. Duas máquinas
  não podem escrever texto diferente com a mesma versão de parser sem isso
  aparecer no registro.
- Nenhum pin de placa entra na dependência padrão. O extra Maxwell continua
  overlay daquela classe de GPU. Uma placa nova ganha diagnóstico, não um
  `requirements` novo com o nome dela.
- Aceite em hardware injetado, não nesta 4070 e não nas 980 Ti: só CPU nunca
  escolhe CUDA; provider listado que não executa cai para CPU com o motivo;
  duas GPUs injetadas podem escolher dispositivos diferentes; o registro da
  etapa mostra o dispositivo que ela usou. Os dois setups rodam o mesmo teste
  antes de marcar `entregue`.

Paths previstos: `index/cuda_runtime.py`, `index/embeddings.py`,
`ingest/ocr.py`. Dono: desktop, com o notebook repetindo o teste na máquina
sem o pin Maxwell. Dependências de código: nenhuma. `IMAGEM-RASTER` mantém uma
sonda limitada ao motor de OCR e ao teto registrado acima; este pacote continua
necessário para unificar diagnóstico e seleção de dispositivo com embedding.

Fora: gravar `onnxruntime-gpu==1.29` ou o cuDNN desta venv no `pyproject`.
Trocar o `model_id` do embedding por causa da placa. Ligar CUDA no clone que
só tem CPU.

## Entrega de `GRAFICO-CACHE` — 26/09/2026

Entregue no PR #126 (commit `76463036ea118d01b6c595e10e434172ed5a8be0`).
`.mcp.json` não entra no Git. A venv usada na validação da branch em 24/09
tinha `onnxruntime-gpu` 1.29.0 e os pacotes `nvidia` de cuDNN/cuBLAS 12.
O clone padrão continua em CPU e o extra `[gpu]` continua com o pin Maxwell 1.18.

Já no código, coberto por teste sintético:

- `GRAFICO-CACHE`: `c:v` vira bloco `grafico`. `.pptx`/`.pptm` na versão 3,
  `.ppt` na 4.
- `GRAFICO-EMBED`: `embeddings/*.xlsx` entra no mesmo bloco quando o valor
  ainda não está no cache. Linha repetida não duplica.
- OCR de PNG/JPEG embutido em PPTX e DOCX, só se `gpu_para_ocr()` executa um
  kernel e a sessão fica em `CUDAExecutionProvider`. Piso de 100 px, teto de
  2 milhões de pixels e 1,5 MB. Ícone não chama o motor. EMF, WMF, WDP e SVG
  ficam em `imagem_nao_lida`. Falha de uma imagem não apaga o texto do slide.
  Sem GPU funcional o meta diz `sem_gpu` e o motor não roda.
- A versão gravada no registro ganha o sufixo `+raster` só nesse caso
  (`.pptx` `3+raster`, `.docx` `2+raster`). Máquina só com CPU não reindexa
  o que já está na versão atual.
- `preparar()` também registra as DLLs com `add_dll_directory` e acha o
  `site-packages` da venv. A sonda desta máquina, pelo código novo, deu
  verdadeiro em 24 s, com as três sessões em CUDA.

A passada no índice vivo ainda não foi executada. Trata-se de operação
posterior ao merge, separada do aceite do pacote; se executada, usar
`--so-extensao .pptx,.pptm,.docx,.docm` e `PYTHONPATH=src`.
Os 431 rasters acima do teto continuam de fora. PDF que já tem parágrafo e
uma figura continua sem OCR. Embedding ainda decide a placa pelo diagnóstico
antigo (`diagnosticar`), não por esta sonda de kernel.

## Entregas de `IMAGEM-RASTER` e `PLANILHA-CELULA` — 29/09/2026

`IMAGEM-RASTER` foi entregue no PR #132 (head `6a6cb8034bf4bb808964296fe8d315838eff99d3`).
Os testes e a CI do PR passaram. Esta instalação Windows não conseguiu provar
execução real do kernel CUDA porque o ONNX Runtime não carregou a DLL local;
por isso o código continua exigindo a sonda positiva e não executa OCR em CPU.
Não houve passada em índice ou acervo real. O limite de 12 imagens por arquivo,
2 Mpx e 1,5 MB por imagem permanece parte do contrato.

`PLANILHA-CELULA` foi entregue no PR #133 (head
`b138b1e89cb819cb4e9322d15a5ae1c86907caa4`). A CI passou em 8 de 8 verificações.
Na fixture sintética de 1.201 × 22, o índice guarda 26.422 células, inclusive
`Medições!V1201 = 12345.67`, e mantém os mesmos cinco blocos/chunks. Células
ficam no SQLite, sem vetor por célula; nenhuma tabela ou acervo real foi lido.

## O que esta fila não reabre

Réplica `.md` na pasta do usuário. NER de pessoa, data ou valor solto.
Varredura de peso. Troca do motor de OCR. Meta de 80% do Parse Store no
rebuild. Reembedar PDF e DOCX que já estão no parser 2.
