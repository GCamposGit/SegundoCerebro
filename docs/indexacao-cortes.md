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
  usando essa GPU. `completo`/`maximo` usam todas.

## Cortes por tipo

`[base.limites]` no `config.toml` local, ou a tabela **Cortes ao indexar**
no painel (por base). Padrão do código, omitido do arquivo se não
diferir:

| Campo | Extensões | Padrão (MB) |
|-------|-----------|------------:|
| `txt` | `.txt` | 2 |
| `csv` | `.csv` | 2 |
| `pdf` `docx` `pptx` `xlsx` `md` | as óbvias + `.docm`/`.pptm`/`.xlsm` | 0 (sem teto) |

`0` = sem teto. Já indexado **não** sai sozinho. A passada em voo nasceu
com o mapa antigo — vale na próxima. Flag de CLI `--pular-texto-acima-de`
ainda cobre `.txt`/`.csv` se vier explícita.

Isto **não** é `max_chars`. Mexer no trecho reindexa o corporativo.

Rede de segurança no código, sem tela: `.txt`/`.csv` com mais de 800
trechos também ficam `adiado`. PDF/DOCX/PPTX não entram nesse teto.

## Barra

O indexador publica `etapa`, `trecho` e `trechos` a cada ~2 s, inclusive
no meio de um arquivo. A tela avisa se o sinal parar por mais de 20 s.
Atalho: `scripts/abrir-painel.cmd` (porta 18787, token em `.painel.json`
ao lado do `config.toml`, gitignorado).

## O que não vai no Git

`config.toml`, índices, caminhos do acervo deste desktop, `.mcp.json`
local, `.painel.json`.
