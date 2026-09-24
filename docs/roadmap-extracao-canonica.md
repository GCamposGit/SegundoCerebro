# Extração canônica, gráficos e imagens

**24/09/2026.** `GRAFICO-CACHE` está em execução na branch `codex/grafico-cache`.
Os outros sete seguem propostos. `IMAGEM-RASTER` continua bloqueado. A escolha
de CPU ou GPU em máquina desconhecida é `HARDWARE-INICIO`, ainda sem código. O ticket que um agente pega
é o bloco `[[pacote]]` em [`pacotes-ativos.toml`](pacotes-ativos.toml); este
arquivo é o contrato. [`ROADMAP.md`](../ROADMAP.md) continua história.

Não há mudança de peso, de chunker nem de `[padrao]`. Aceite é fixture
sintética (vocabulário VCE). Índice e pastas reais não entram no Git e não são
o teste do pacote. Passada no índice vivo, quando existir, é passo operacional
depois do merge, com `--so-extensao`, nunca reindexação da árvore inteira.

## Como pegar um ticket

1. Escolha o primeiro da ordem cujo `dependencias` já está `entregue`. Hoje o
   único sem dependência de código que destrava o sintoma de gráfico é
   `GRAFICO-CACHE`. `BUSCA-BURACO` pode andar em paralelo: não toca parser.
2. No máximo um pacote `em_execucao` por path. `GRAFICO-CACHE`,
   `GRAFICO-EMBED` e `IMAGEM-RASTER` dividem `slides.py`. Não marque dois como
   `pronto` ou `em_execucao` ao mesmo tempo.
3. Branch `codex/<id>` a partir de `main`. Não commitar em `main`.
4. O teste novo tem de falhar com o código antigo e passar com o novo.
5. Subir a versão do parser se o texto emitido mudar. `.pptx`/`.pptm` estão em
   `3` e `.ppt` em `4` desde o `GRAFICO-CACHE`. Refatoração que não muda texto
   não sobe versão.

## O que já está no produto

A réplica `.md` ao lado do arquivo foi recusada: escreveria na pasta do
usuário. O substituto é o Parse Store (`ingest/parse_store.py`): Markdown
canônico mais blocos, comprimido dentro do índice. `get_document` e
`pack_folder` leem dali. `search` lê trechos e vetores, não o store.

`PARSER-TEXTO-OCULTO` (PR #119) colhe texto que o python-pptx não visita:
SmartArt (`ppt/diagrams`, tag `a:t`), caixas, cabeçalho e o título de gráfico
quando ele também está numa tag `t`. O locator `grafico` já existe.

OCR é de página de PDF. Entra página com menos de 15 caracteres e uma imagem,
ou com menos de 100 caracteres e uma imagem (`pagina_precisa_ocr`). Página com
título e uma figura fica de fora. PNG, JPEG, EMF e SVG soltos não têm parser.
Nada em `ppt/media` ou `word/media` passa pelo RapidOCR.

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
| 1 | `GRAFICO-CACHE` | agora | Único diff que faz o número do gráfico nativo existir no texto |
| 1 | `BUSCA-BURACO` | agora, em paralelo | Outros paths. Evita o agente abrir o original quando o índice declara o buraco |
| 2 | `GRAFICO-EMBED` | depois de `GRAFICO-CACHE` | Chart sem `c:v`, lendo o xlsx já embutido com o parser de planilha |
| — | `HARDWARE-INICIO` | proposto, antes de ligar OCR na placa | Diagnóstico na arranque e dispositivo por etapa, sem pin desta máquina |
| 3 | `IMAGEM-RASTER` | bloqueado | Na CPU, 5,4 h. Na 4070, cerca de 31 min para os 2.202 rasters, e o produto ainda não escolhe a placa |
| 2 | `PLANILHA-CELULA` | em paralelo com 2–3, sem mexer em `slides.py` | Guarda a célula que o digesto descarta, sem novo vetor |
| 3 | `PLANILHA-LEITURA` | depois de `PLANILHA-CELULA` | Tool MCP com cursor sobre essa tabela |
| último operacional | `CANONICO-BACKFILL` | código em paralelo; a passada só depois dos bumps de parser | Preenche o store do que já está nos trechos. Rodar antes congela texto velho |

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

Paths: `ingest/parsers/slides.py`, teste em `tests/test_ingest.py`. Pode nascer
um módulo novo se `slides.py` não couber no teto. Dono: notebook. Depende de
`GRAFICO-CACHE`.

Aceite: fixture com chart sem cache e um xlsx embutido devolve o valor
plantado, com locator `grafico`. Fixture que já tem `c:v` não duplica o
número. Aba embutida acima do limiar de digesto declara a mesma limitação que
a planilha solta.

Fora: OCR da figura do gráfico. Objeto OLE que não é xlsx.

### `IMAGEM-RASTER`

Problema: print e gráfico colado como PNG/JPEG não têm XML de texto. OCR hoje
só rasteriza página de PDF pobre em texto.

**Não aprovado para implementação.** Medição real em 24/09/2026, RapidOCR do
ambiente, sem gravar texto e sem abrir placeholder. Inventário dos PPTX/DOCX
locais com status `ok`: 2.756 PNG/JPEG/JPG em `media/`. 543 ficam abaixo de
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

Isso não aprova o pacote. O wheel de GPU e o cuDNN estão só na venv desta
máquina. O `pip install` padrão continua no `onnxruntime` de CPU, e o extra
`[gpu]` do repositório continua o pin Maxwell 1.18 do Desktop. Sem a pasta
`nvidia/cudnn/bin` no caminho das DLLs, o Conv da 1.29 falha pedindo
`cudnn64_9.dll`. O produto chama `RapidOCR()` sem `use_cuda`, então esta
venv, mesmo com a placa visível, segue o OCR na CPU até o `HARDWARE-INICIO`
escolher o dispositivo. OCR dos 2.202 continua fora.

O próximo corte, ainda sem código de produto, é contar e cronometrar só a
imagem que está num slide sem texto de forma e sem `c:v`, com teto por
arquivo. Se essa fatia couber em minutos e não em horas, o aceite abaixo
volta a valer. Se não couber, o pacote encerra sem ligar o motor.

Paths, quando o teto existir: `ingest/ocr.py`, `ingest/parsers/slides.py`,
`ingest/parsers/word.py`, teste com motor falso (`SEGUNDOCEREBRO_OCR_FAKE`)
mais um teste marcado `ocr` com RapidOCR real num PNG pequeno gerado no
teste. Dono: notebook. Depende de `GRAFICO-EMBED`.

Aceite, suspenso até o teto: slide cujo único conteúdo é um PNG com
identificador VCE ganha bloco com esse identificador e locator `imagem`.
Slide que já tem o mesmo texto no frame não ganha segunda cópia. Imagem
abaixo do piso de pixels não chama o motor. EMF, WMF, WDP e SVG ficam
declarados como não lidos. Falha de memória do OCR não apaga o texto do
frame já extraído. O número de imagens que o parser manda ao motor por
arquivo fica no teto que a medição seguinte aprovar.

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
código não entra nessa passada. PPTX não entra.

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

Contrato, para revisitar antes de aprovar `IMAGEM-RASTER` e antes de qualquer
passada que ligue placa:

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
sem o pin Maxwell. Dependências de código: nenhuma. `IMAGEM-RASTER` espera
este pacote e um teto de imagens medido no dispositivo que o diagnóstico
realmente escolher.

Fora: gravar `onnxruntime-gpu==1.29` ou o cuDNN desta venv no `pyproject`.
Trocar o `model_id` do embedding por causa da placa. Ligar CUDA no clone que
só tem CPU.

## Estado da branch `codex/grafico-cache` — 24/09/2026

Ainda sem commit e sem PR. `.mcp.json` não entra. A venv desta máquina está
com `onnxruntime-gpu` 1.29.0 e os pacotes `nvidia` de cuDNN/cuBLAS 12. Isso
não está no Git. O clone padrão continua em CPU. O extra `[gpu]` continua
o pin Maxwell 1.18.

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

Ainda não rodou passada no índice vivo. O próximo passo operacional, depois
do merge, é `--so-extensao .pptx,.pptm,.docx,.docm` nesta máquina, com
`PYTHONPATH=src`, porque a instalação da venv não é um checkout editável.
Os 431 rasters acima do teto continuam de fora. PDF que já tem parágrafo e
uma figura continua sem OCR. Embedding ainda decide a placa pelo diagnóstico
antigo (`diagnosticar`), não por esta sonda de kernel.

## O que esta fila não reabre

Réplica `.md` na pasta do usuário. NER de pessoa, data ou valor solto.
Varredura de peso. Troca do motor de OCR. Meta de 80% do Parse Store no
rebuild. Reembedar PDF e DOCX que já estão no parser 2.
