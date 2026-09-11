# FND-01b — identidade interna por raiz e caminho

Desenho que desbloqueia a implementação. Não é a migração. Schema, Store e
índice real **não mudam neste documento**.

Serve a uma pasta que nunca vimos: duas raízes na mesma base, o mesmo
`contrato.md` relativo, conteúdos diferentes. Hoje o 01a recusa a passada.
Amanhã as duas ocorrências existem e a MCP as distingue. Empate no desenho
encerra; não se “começa a migrar para ver”.

Relaciona o `J.b1` sem trocar o `doc_id` público de conteúdo.

## O que já está decidido no código

| Peça | Estado | Consequência |
|---|---|---|
| `documentos.path` é `PRIMARY KEY` | `esquema.py` | homônimo entre raízes é uma linha só |
| `documentos.raiz` já existe | metadado, não chave | a recusa do 01a não usa isso para coexistir |
| `doc_id` = prefixo de `sha256` | `acesso/identidade.py` | identidade **pública de conteúdo**; não muda |
| `sc://<base>/<doc_id>` | conferência de base, nunca seletor | invariante 7 |
| parse store | chave = hash + parser | não usa path; migração não o reescreve |
| journal `operacoes.path` | FND-02b, PR #102 | a migração tem de levar o journal, ou recusar se houver linha pendente |
| backup para pasta nova | FND-08b, PR #98 | destino da migração; original intacto |

A recusa do 01a (PR #90) permanece até o aceite da integração: dois homônimos
indexados **e** consultáveis. Tirar a recusa no PR de migração é regressão.

## Decisões

### 1. Dois ids, dois papéis

- **Ocorrência** (interna): um arquivo numa raiz desta base. Chave opaca
  `ocorrencia_id`. Consumidor não parseia o id.
- **Conteúdo** (público): `doc_id` / `sc://`. Um conteúdo, N ocorrências, como
  hoje nos 10,5% de duplicatas byte-idênticas.

Homônimo com conteúdo diferente: duas ocorrências, dois `doc_id`. Homônimo
byte-idêntico: duas ocorrências, um `doc_id`. Não fundir as duas no Store.

### 2. `root_id` não é letra de disco

`root_id` é o `name` de `RootSpec`, único **dentro da base**. Dois `name`
iguais na mesma base são erro de configuração (não se desambigua com
`C:\` vs `D:\`).

Tabela nova `raizes`: `root_id` (PK), `rotulo`, `caminho_atual` (só
diagnóstico). O caminho no disco pode mudar; o `root_id` não muda sem o
comando de remapeamento.

Mover a pasta: ação explícita (`remapear root_id → novo caminho`). Nada
detecta troca de letra de drive.

### 3. `ocorrencia_id` opaco e estável

```
ocorrencia_id = sha256(root_id + "\0" + caminho_rel)[:16]
```

Determinístico: a mesma raiz lógica e o mesmo relativo reproduzem o id.
Remapear o caminho físico **não** muda o id. Renomear o `root_id` é outra
ocorrência — isso é o remapeamento, não um rename silencioso.

`caminho_rel` é POSIX relativo à raiz (`contrato.md`, `atas/2024/x.pdf`),
sem drive e sem `..`.

PK sugerida de `documentos`: `ocorrencia_id`. Colunas `root_id` e
`caminho_rel` com `UNIQUE(root_id, caminho_rel)`. `path` deixa de ser PK;
pode ficar coluna gerada ou view de compatibilidade **só na leitura do
schema antigo**, não como chave nova.

### 4. Chunks, vetores e journal

`chunk_id` hoje semeia `doc_path`. Depois da migração a semente inclui
`ocorrencia_id` (não o path cru). Dois `contrato.md` não compartilham chunk
nem vetor.

`operacoes.path` (FND-02b) passa a `ocorrencia_id`. Migração com journal
pendente: **recusar**. Escritor parado (trava do 08b) é pré-requisito.

LanceDB: o campo que hoje replica `path` replica `ocorrencia_id`. Integridade
02a compara esses ids, não o path relativo.

### 5. Resolução na MCP

| Pedido | Único | Ambíguo |
|---|---|---|
| `sc://base/doc_id` | conteúdo; lista ocorrências | — |
| caminho relativo | resolve a ocorrência | erro: pedir `root_id` ou `sc://` |
| `root_id` + relativo | a ocorrência | — |

Não escolher a primeira linha do SQLite. Path sem raiz só vale quando a
consulta por `caminho_rel` devolve uma linha.

### 6. Versão de schema e migração

Versão nova, explícita (tabela `meta` ou carimbo no manifesto do 08b).
`CREATE IF NOT EXISTS` **não** migra PK.

Migrador:

1. Recusa índice em uso e `operacoes` pendente.
2. Backup 08b (ou equivalente) do original.
3. Escreve **diretório novo**. Não altera o original.
4. Confere contagens: documentos, chunks, FTS, vetores, menções, quarentena,
   journal vazio, parse store intocado (chave de conteúdo).
5. Publica o destino só depois da conferência. Interromper não aponta
   `config.toml` para pasta parcial.
6. Ativação é passo separado, como o restore do 08b.

Rollback: voltar o `indice` para a pasta antiga. Sem downgrade destrutivo.

## Exemplo que o aceite tem de reproduzir

Duas raízes na base `vce`, fixture sintética, sem acervo real:

```
pessoal/contrato.md   "Contrato da oficina da VCE, cláusula 1."
trabalho/contrato.md  "Contrato do escritório da VCE, cláusula 9."
```

| Hoje (01a) | Depois da integração 01b |
|---|---|
| passada recusada, índice intacto | duas ocorrências, dois `doc_id` |
| — | `list_folder` / `get_document` / `search` distinguem as duas |
| — | apagar só `pessoal/contrato.md` não apaga a outra |
| — | path `contrato.md` sem raiz devolve erro de ambiguidade |

Mesmo conteúdo nas duas raízes: duas ocorrências, um `doc_id`, preferido
pela regra já existente de `por_vigencia`.

## Dois PRs, um de cada vez

**PR 1 — migração (Desktop).** `index/esquema.py`, `store.py`, migrador,
`operacoes.py` (journal), laço do indexer o mínimo para gravar
`ocorrencia_id`. Recusa 01a **ligada**. Testes com duas raízes sintéticas no
Store, sem MCP.

**PR 2 — integração (Notebook, depois do 1 em `main`).**
`acesso/identidade.py`, `registro.py`, resolução MCP, `chunking.py` se o
id do chunk ainda nascer do path. Só então desligar a recusa 01a, no mesmo
PR que prova o exemplo acima.

Não um diff só. `store.py` e `acesso/identidade.py` não abrem juntos.

## Fora deste desenho

- Implementar o migrador ou mudar `ESQUEMA` agora.
- Ligar em índice real (corporativo ou do Desktop) antes da fixture verde.
- Inferir `root_id` de `C:` / `D:` / UNC.
- Trocar `doc_id` público ou o esquema `sc://`.
- Reescrever parse store.

## Aceite do desenho (esta entrega)

Documento versionado; fila `FND-01b` em `em_execucao` no PR 1 de migração
(Desktop). Recusa do 01a permanece. Implementação que divergir destas decisões
reabre o bloqueio, não “ajusta no código”.
