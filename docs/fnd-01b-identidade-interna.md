# FND-01b — identidade interna por raiz e caminho

Contrato de implementação do FND-01b. A persistência e a integração pública
foram entregues em dois commits revisáveis; a ativação do índice real continua
sendo uma operação explícita e reversível.

Serve a uma pasta que nunca vimos: duas raízes na mesma base, o mesmo
`contrato.md` relativo, conteúdos diferentes. O 01a recusava a passada. Agora
as duas ocorrências coexistem e a MCP as distingue; a migração escreve em
diretório novo e só publica após a verificação.

Relaciona o `J.b1` sem trocar o `doc_id` público de conteúdo.

## O que já está decidido no código

| Peça | Estado | Consequência |
|---|---|---|
| `documentos.ocorrencia_id` é `PRIMARY KEY` após migração | `esquema.py` | homônimo entre raízes são linhas distintas |
| `documentos.path` no schema legado | compatibilidade de leitura | migração reconstrói a chave sem alterar o original |
| `doc_id` = prefixo de `sha256` | `acesso/identidade.py` | identidade **pública de conteúdo**; não muda |
| `sc://<base>/<doc_id>` | conferência de base, nunca seletor | invariante 7 |
| parse store | chave = hash + parser | não usa path; migração copia e verifica sem reescrever |
| journal `operacoes.ocorrencia_id` | FND-02b | a migração leva o journal e recusa linha pendente |
| backup para pasta nova | FND-08b, PR #98 | destino da migração; original intacto |

O indexador não chama mais a guarda temporária do 01a. A ambiguidade continua
protegida na resolução pública: caminho sem raiz só é aceito quando há uma
única ocorrência.

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

PK de `documentos`: `ocorrencia_id`. Colunas `root_id` e
`caminho_rel` com `UNIQUE(root_id, caminho_rel)`. `path` deixa de ser PK;
pode ficar coluna gerada ou view de compatibilidade **só na leitura do
schema antigo**, não como chave nova.

### 4. Chunks, vetores e journal

`chunk_id` hoje semeia `doc_path`. Depois da migração a semente inclui
`ocorrencia_id` (não o path cru). Dois `contrato.md` não compartilham chunk
nem vetor.

`operacoes.ocorrencia_id` (FND-02b) identifica a ocorrência. Migração com journal
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

## Dois commits, em ordem

**Commit 1 — persistência.** `index/esquema.py`, `store.py`, migrador,
`operacoes.py` (journal), integridade e reconciliação. Testes com duas raízes
sintéticas no Store, sem acervo real.

**Commit 2 — integração pública (Notebook).** `acesso/identidade.py`,
`registro.py`, resolução MCP, busca, leitura e `chunking.py`; remove a guarda
temporária e prova o exemplo acima.

Os commits permanecem separados para revisão. A fila registra o executor
`notebook` e a evidência SHA da entrega.

## Fora deste desenho

- Ligar em índice real (corporativo ou do Desktop) antes da fixture verde.
- Inferir `root_id` de `C:` / `D:` / UNC.
- Trocar `doc_id` público ou o esquema `sc://`.
- Reescrever parse store.

## Aceite do desenho (esta entrega)

Documento versionado; fila `FND-01b` e `FND-01b-int` com dono `notebook` e
evidência SHA. Fixtures sintéticas verdes, migração verificada em diretório
novo e ativação real mantida como passo separado e reversível.
