# Backup e restauração do índice

Contrato do `FND-08b`. Copia o **índice** (registro SQLite + vetores LanceDB),
não os documentos da pasta que o leigo apontou. Restaurar grava numa pasta
**nova** e não apaga o índice atual.

```bash
py -m segundocerebro.index.backup criar --base trabalho --destino backup-indice
py -m segundocerebro.index.backup restaurar --origem backup-indice --destino indice-restaurado
```

A indexação tem de estar parada. A restauração não troca o `config.toml`: para
usar a cópia, aponte `indice` para a pasta nova.

## O que entra

| Peça | Padrão | Nota |
|---|---|---|
| `registro.db` (FTS, metadados, menções, quarentena) | sim | Snapshot pela API de backup do SQLite |
| `vetores.lance` | se existir | Cópia com a trava exclusiva do indexador |
| `config.toml` / glossário | opt-in | `--incluir-config` / `--glossario` |
| parse store | opt-in | `--parse-store` — cache reconstruível |
| arquivos originais da pasta apontada | nunca | Apagar o original não o recupera por este backup |

## O que o procedimento não é

O LanceDB 0.37.1 instalado não tem snapshot portátil: `checkout` e `restore` da
tabela são versões **no mesmo diretório**. Com o escritor parado (trava
`indexacao.lock`), copiar `vetores.lance` é o procedimento verificado. Copiar
arquivos de banco **vivo**, sem a trava, não é snapshot — o CLI recusa se a
indexação estiver ativa.

O manifesto (`manifesto.json`) guarda schema/`model_id`, checksums SHA-256,
contagens e o resultado da integridade (FND-02a) mais uma consulta lexical
sintética. Checksum divergente, arquivo truncado ou formato mais novo que o
instalado recusam a restauração. Disco cheio ou falha no meio deixam o índice
original intacto e não publicam o destino.

Ativar o restaurado é um passo separado. Este comando não aponta a base para a
pasta nova e não apaga a pasta antiga.
