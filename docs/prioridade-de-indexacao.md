# Prioridade de indexação — ondas, pastas e o que não entra

23/08/2026. Branch `f36-rerank-gpu`. Setup desktop. **Não é a condição C.**
Nenhum número de recall daqui substitui o conjunto corporativo.

A ordem da fila é política de **indexação**, não de ranking. `retrieve/*`,
pesos, `Chunking` e `model_id` não mudam. Consulta no meio do run continua
válida: o commit continua sendo por documento.

## Por quê

O laço lia `iter_files` na ordem do disco. Um dump ou um PDF de centenas de MB
podia aparecer cedo e prender a GPU enquanto milhares de DOCX pequenos — os que
o usuário pergunta — ficavam no fim. Sem parser, JPEG/DLL/vídeo viravam
`sem_parser` e eram re-tentados a cada passada.

A tabela em [`estatisticas-arquivos-por-extensao.md`](estatisticas-arquivos-por-extensao.md)
é um disco inteiro, não uma base. O algoritmo tem que sobreviver a qualquer
raiz: acervo corporativo, pasta pessoal, ou um volume apontado por engano.

## O que entra na fila

Fonte de verdade: `ingest.parsers.supported_extensions()`. Ruído **não** gera
linha nova em `documentos`. Censo e prévia do painel continuam vendo o disco
inteiro; o filtro é no indexador, depois da enumeração. O estimador declara só
o que entrou na fila.

Hoje:

| Grupo | Extensões | Onda 1 | Onda 2 | Depois |
|-------|-----------|--------|--------|--------|
| Nota | `.md` `.markdown` | todos | — | — |
| Word | `.docx` `.docm` `.doc` | ≤ 0,5 MB | ≤ 2 MB | até `[base.limites]` |
| PDF | `.pdf` | ≤ 2 MB | ≤ 8 MB | até o limite |
| Deck | `.pptx` `.pptm` `.ppt` | ≤ 5 MB | ≤ 15 MB | até o limite |
| Planilha | `.xlsx` `.xlsm` `.xls` | ≤ 2 MB | ≤ 15 MB | até o limite + teto de abas |
| Texto bruto | `.txt` `.csv` | 100 KB / 256 KB | teto da base | `adiado` |
| RTF | `.rtf` | ≤ 0,5 MB | ≤ 2 MB | até o limite |

`.doc` / `.xls` / `.ppt` entram porque, sem eles, um acervo de consultoria
(Office 97–2003) fica cego. A extração é pior que OOXML — bytes only, sem COM —
e isso é aceito: a alternativa medida foi dezenas de milhares de `sem_parser`.

**Não entram** (sem parser, fora da fila): imagem, vídeo, áudio, binário, o
próprio índice (`.lance`), compactados, cache. `.msg` / `.eml` / OCR continuam
F4. HTML/JSON/XML só com allowlist explícita — nesta amostra são mistura de
config e lixo.

`[base.limites]` e o teto de 800 trechos em `.txt`/`.csv` **não** são afrouxados
pelas ondas. Arquivo acima continua `adiado`, sem abrir o conteúdo.

## Quatro ondas, uma passada

| Onda | Quem | Promessa |
|------|------|----------|
| 1 | vigentes pequenos, markdown, notas | a base já responde o dia a dia |
| 2 | os mesmos tipos até o teto médio | cobertura da mediana |
| 3 | até `[base.limites]` | documentos longos |
| 4 | versões antigas, dumps por nome, cauda | histórico por último |

`--apenas-onda N` indexa só aquela onda. Default: 1→4 numa run só.

Ordenação dentro da onda: pasta com maior *score* primeiro, depois arquivo
menor, depois `mtime` mais novo. Score da pasta:

```
N / (1 + log1p(bytes)) × densidade × recência
```

Densidade = arquivos desta onda na pasta / indexáveis na pasta. Recência =
`1 / (1 + idade em anos do mtime mais novo)`. Sem palavra-chave no caminho.

## Versão e duplicata

Chave de família na indexação: pasta + extensão + tronco sem `_vN`, `(1)`,
`Cópia`, `_bkp`, `_old`. **Não** se tira `final`/`revisado`: o vigente muitas
vezes é esse arquivo, sem número (forma do g010). Desempate = `mtime`, nunca o
número no nome. Família não atravessa pasta nem extensão (pdf+pptx do mesmo
stem são os dois — forma do g045).

Irmão velho vai para a onda 4. Já indexado não sai.

SHA-256 igual em **outro** path, já `ok` com o mesmo modelo e chunker: status
`duplicado`, sem reembeddar. Consulta acha o primeiro path. Copiar vetores para
o segundo é follow-up (id de trecho inclui o path).

## Retomada e reconciliação

`_precisa_indexar` não muda. A enumeração completa alimenta `vistos` (JPEG já
registrado como `sem_parser` não some e não dispara a trava de 20%). A fila de
trabalho é só o que tem parser.

## CLI

```bash
py -m segundocerebro.index.indexer --base vce --perfil normal
py -m segundocerebro.index.indexer --base vce --apenas-onda 1
```

A barra publica `onda`, `ondas` e `pasta` em `progresso.json`. Sem marcador novo.
