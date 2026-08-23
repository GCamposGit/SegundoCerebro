# Indexação no desktop — cortes, barra viva e GPU do monitor

22/08/2026. Branch `f36-rerank-gpu`. Setup desktop. **Não é a condição C.**
Nenhum número de recall daqui substitui o conjunto corporativo.

O laço do indexador, o schema `[base.limites]` e o painel saíram no mesmo
PR porque a barra morta e o dump de texto eram o mesmo incidente. Ranking
não mudou.

## O que o notebook precisa saber

- **Não** reescrever `indexer.py`, `painel/*` nem o schema de `config.py`
  enquanto este PR não estiver em `main`.
- `[padrao]` e `Chunking` **não** mudaram. O teto novo é tamanho de
  **arquivo em disco**, por tipo, na base. Arquivo acima fica `adiado` e é
  repescado numa passada sem o limite.
- `model_id` continua `e5-large:1024:fastembed0.8.0`. Hardware não entra.
- Cancelar no painel agora é lido **durante** o embed, a cada lote. Antes
  só valia entre documentos — um dump prendia a GPU por horas.
- Perfil `leve`: a placa que pinta o desktop não carrega o encoder
  (TDR / evento `nvlddmkm`). Uma GPU só, mesmo com monitor, continua
  usando essa GPU, mas não a 100%. `normal` usa todas, com a GPU 0
  abaixo de 100%. `maximo` usa todas a 100%. Trocar o perfil no painel
  vale no processo em curso (prioridade, CPU, ritmo); GPU nova só na
  próxima largada. O perfil salvo em `[maquina]` é o que a retomada
  usa depois de reiniciar.

## Cortes por tipo

`[base.limites]` no `config.toml` local, ou a tabela **Cortes ao indexar**
no painel (por base). Padrão do código, omitido do arquivo se não
diferir:

| Campo | Extensões | Recomendado no painel (MB) |
|-------|-----------|------------:|
| `txt` | `.txt` | 2 |
| `csv` | `.csv` | 2 |
| `md` | `.md` | 5 |
| `xlsx` | `.xlsx` `.xlsm` | 15 |
| `docx` | `.docx` `.docm` | 30 |
| `pdf` `pptx` | as óbvias + `.pptm` | 50 |

`0` = sem teto. O painel já vem preenchido com o recomendado até o
usuário ajustar. O ajuste grava na base **e** em `[maquina.limites]`,
para a próxima base nesta máquina herdar. Já indexado **não** sai
sozinho. A passada em voo nasceu com o mapa antigo. Flag de CLI
`--pular-texto-acima-de` ainda cobre `.txt`/`.csv` se vier explícita.

Isto **não** é `max_chars`. Mexer no trecho reindexa o corporativo.

Rede de segurança no código, sem tela: `.txt`/`.csv` com mais de 800
trechos também ficam `adiado`. PDF/DOCX/PPTX não entram nesse teto.

## Barra

O indexador publica `etapa`, `trecho` e `trechos` a cada ~2 s, inclusive
no meio de um arquivo. A tela avisa se o sinal parar por mais de 20 s.
Atalho: `scripts/abrir-painel.cmd` (porta 18787, token em `.painel.json`
ao lado do `config.toml`, gitignorado).

## Fila

A ordem dos arquivos não é mais a do disco. Ondas, pastas pequenas primeiro e
versão vigente (mtime) estão em [`prioridade-de-indexacao.md`](prioridade-de-indexacao.md).
Os tetos desta página continuam sendo a **porta** (`adiado`); as ondas só
decidem **quando** o arquivo entra na fila.

## O que não vai no Git

`config.toml`, índices, caminhos do acervo deste desktop, `.mcp.json`
local, `.painel.json`.
