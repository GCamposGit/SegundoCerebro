# Pacote J — Camada de Acesso ao Corpus (Parse Store + Acesso Integral)
**Status:** FINAL — pronto para distribuição aos devs (notebook e desktop)
**Data:** 2026-08-30 · **Origem:** decisão de arquitetura pós-dossiês (R1–R10, C1–C7, E-enterprise)
**Prioridade:** P0 (J.a–c, J.f) / P1 (J.d–e) · **Dono:** ver tabela por subpacote
**Relação:** não altera pacotes existentes; **subordina** partes de R1.x, R3.2, E4 e adiciona tools ao conjunto de R7.1. Tabela de interações na §7.

---

## Como usar este documento (instrução para Claude Code / Grok Build)

- Mesmas regras dos dossiês: **um subpacote = uma branch = um PR**, número antes/depois quando tocar ranking, donos conforme `docs/colaboracao.md` §1; subpacote que cruza a fronteira divide em dois PRs.
- **Nomes de módulos, funções e tools abaixo são contratos sugeridos, não prescrição.** A base passou por refatoração completa desde a última avaliação externa: **mapeie cada contrato para o layout real vigente** antes de criar arquivo. O que é normativo neste documento são os **objetivos, invariantes, comportamentos observáveis e critérios de aceite** — não os nomes nem a organização interna. Se um contrato já existir sob outro nome, estenda-o; não duplique.
- Nenhum subpacote muda `model_id`, chunking padrão ou `[padrao]` sem acordo entre setups (invariante existente).
- Leia a §2 (invariantes) antes de qualquer linha. Violar a §2 é motivo de rejeição do PR independentemente de qualquer métrica.

---

## 0. Por que este pacote existe — a mudança de requisito

O produto tinha um modo de consumo: **retrieval** — pergunta curta → top-k trechos → LLM responde. As tools MCP existentes (`search`, `read_note`, `neighbors`, ...) servem esse modo bem.

O requisito novo é o segundo modo: **ingestão integral dirigida por agente**. Casos concretos que o produto passa a prometer:

- *"Crie um paper detalhado sobre o projeto X"* apontando para uma pasta com dezenas de arquivos — o agente precisa ler **tudo** que é relevante, na íntegra, com citações confiáveis, dentro do orçamento de contexto dele.
- Workflows agênticos (n8n, OpenClaw-like, agentes de longa duração): passos programáticos que enumeram, leem e processam documentos por ID estável, repetíveis semana após semana com resultado idêntico.
- Obsidian e ferramentas de nota: o usuário quer *ver e navegar* o acervo como Markdown interligado, sem que o sistema jamais escreva nas pastas dele.

Nenhuma tool de busca resolve isso. Busca responde "onde está?"; o segundo modo pergunta **"me dê o conteúdo inteiro, organizado, endereçável e sob orçamento"**. A peça que habilita os dois modos com um único custo de parse é a **representação canônica persistida** de cada documento — o Parse Store — promovida de cache interno a **camada de produto**.

### O que muda em relação à discussão anterior

A recomendação original ("Parse Store" como cache) era uma otimização: parse uma vez, rebuild de vetores barato. Ela continua válida na íntegra (é o subpacote J.a + J.f), mas o escopo cresce:

| Antes (cache) | Agora (camada de acesso) |
|---|---|
| Consumidor: só o indexador | Consumidores: indexador, tools MCP de leitura integral, exportadores, agentes externos |
| Conteúdo: texto extraído | Conteúdo: Markdown canônico + sidecar estruturado (blocos, offsets, páginas) |
| Endereço: interno | Endereço: **ID público estável por documento** + URI resolvível |
| Garantia: idempotência de indexação | Garantia adicional: **determinismo observável por terceiros** — mesmo arquivo, mesmo parser ⇒ mesmo byte, hoje e daqui a um ano |

---

## 1. Visão arquitetural

```
  Acervo do usuário (READ-ONLY, intocável)
        │  censo + hash (existente)
        ▼
  ┌─────────────────────────────────────────────┐
  │  PARSE STORE  (dentro do diretório do índice)│
  │  <hash[:2]>/<hash>.md.zst  ← Markdown canônico
  │  <hash[:2]>/<hash>.json    ← sidecar estruturado
  │  entradas identity p/ .md/.txt nativos       │
  └─────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
  Indexador            Tools MCP de           Exportadores
  (chunking,           acesso integral        (vault Obsidian,
  embeddings —         (get_document,          bundle .md —
  lê do store,         outline, list_folder,   ação explícita
  nunca re-parseia)    pack_folder)            do usuário)
```

Três consumidores, um único parse. A busca (retrieval) continua exatamente como está — este pacote **não toca ranking**; ele constrói a via de leitura que a busca não cobre.

---

## 2. Invariantes (não negociáveis — motivo de rejeição de PR)

1. **O acervo do usuário é somente-leitura. Sempre.** Nenhum artefato derivado — .md canônico, sidecar, export, log, lock — é escrito dentro das pastas indexadas. O store vive no diretório do índice; exports vivem em diretório escolhido explicitamente pelo usuário, fora das raízes indexadas.
2. **Determinismo.** A chave de toda entrada é `(hash_conteudo, parser_version, rota_de_parse)`. Mesmo trio ⇒ mesmo Markdown e mesmo sidecar, byte a byte, em qualquer máquina. Nada de timestamps de geração, ordenação dependente de dicionário, caminhos absolutos ou aleatoriedade dentro do artefato canônico (metadados voláteis vivem fora dele).
3. **O original é a fonte de citação.** Toda saída de tool ou export referencia o arquivo original (caminho, página/offset quando houver). O .md canônico é representação, nunca substituto: o usuário abre, envia e audita o original.
4. **O store é 100% derivado e descartável.** Apagar o store nunca perde dado do usuário; qualquer entrada é regenerável on-demand a partir do original. Nenhum fluxo pode tratar o store como fonte primária de verdade.
5. **O servidor recupera; o LLM raciocina.** Nenhuma tool deste pacote resume, interpreta ou sintetiza conteúdo server-side. `pack_folder` concatena e organiza; quem escreve o paper é o agente cliente. (Coerente com a anti-recomendação de roteador/juiz server-side de C1/R6.)
6. **Nunca truncar em silêncio.** Toda tool que devolve conteúdo aceita orçamento (`max_chars` ou equivalente) e, quando o conteúdo excede, devolve **cursor de continuação explícito** + metadado do total. O agente sempre sabe que há mais e como buscar.
7. **Privacidade nas descrições e erros.** Tools e exports não vazam caminho absoluto de máquina nem nome de cliente real em descriptions, logs de erro ou frontmatter além do que o próprio acervo já contém. Vale a mesma disciplina da VCE.

---

## 3. Componentes (contratos em nível de módulo/função)

> Reiterando: nomes são sugestões de contrato. Adapte ao layout pós-refatoração; preserve comportamento e assinatura semântica.

### 3.1 Núcleo do Parse Store — `ingest/parse_store.py` (ou equivalente)

Responsabilidade: única porta de leitura/escrita da representação canônica.

- `obter(doc) -> ParseCanonico | None` — hit/miss pela chave da §2.2. Miss ⇒ o chamador decide parsear (indexador) ou parsear on-demand (tool de leitura).
- `gravar(doc, markdown, sidecar)` — escrita atômica (temp + rename), compressão zstd do .md, verificação da chave.
- `entrada_identity(doc)` — para formatos já em texto plano/Markdown: nenhuma cópia; a entrada aponta para o original e a leitura passa pelo mesmo contrato `ParseCanonico` (normalização de encoding/EOL aplicada na leitura, não no disco).
- `invalidar(hash | parser_version | rota)` — invalidação seletiva; bump de `parser_version` de um parser invalida só a rota dele.
- `gc(censo, carencia_dias)` — remove entradas cujo hash sumiu do censo há N dias. Nunca roda durante onda de indexação.
- Layout físico: `parse_store/<hash[:2]>/<hash>.<ext>` dentro do diretório do índice; gitignorado; invisível ao leigo.

**`ParseCanonico`** (o contrato de dados que todos os consumidores enxergam):
- `markdown` — renderização legível, com headings, tabelas em pipe-table, quebras estáveis;
- `blocos[]` — lista ordenada: tipo (`paragrafo|heading|tabela|celula|slide|legenda|codigo`), texto, offset inicial/final **no markdown**, página/slide/aba de origem quando existir, trilha de headings;
- `meta` — hash, rota de parse, `parser_version`, idioma provável, contagem de tokens (pelo tokenizer real já usado no chunking), flags (`fonte=ocr`, `convertido_de=.doc`, ...).

O sidecar é a **fonte estrutural** (spans do E4 nascem dele); o .md é a **renderização** (o que agentes e humanos leem). Um deriva do outro de forma determinística — nunca manter os dois por caminhos independentes.

### 3.2 IDs públicos e endereçamento — pré-requisito agêntico

- **`doc_id` estável**: derivado do `hash_conteudo` (curto, ex.: 12 hex). Sobrevive a renomeação e a mudança de pasta (conteúdo igual ⇒ mesmo id); muda quando o conteúdo muda — comportamento correto para reprodutibilidade de workflow.
- **URI resolvível**: esquema interno `sc://<base>/<doc_id>` aceito por todas as tools de leitura no lugar de caminho. Caminho continua aceito (conveniência humana); o id é o contrato para agentes.
- Resolução `doc_id → caminhos[]` usa a tabela de caminhos do dedup (R1.3): um conteúdo, N caminhos, um preferido.
- **Opcional (avaliar custo):** expor documentos também como **MCP resources** além de tools, para clientes que suportam resources nativamente. Não bloquear os subpacotes por isso; registrar decisão.

### 3.3 Tools MCP de acesso integral — o coração do requisito novo

Quatro tools, todas servidas pelo store (miss ⇒ parse on-demand + gravação):

**`get_document(id_ou_caminho, cursor=None, max_chars=N)`**
- Devolve o Markdown canônico completo, paginado por orçamento. Primeira página inclui cabeçalho de metadados (título, caminho original preferido, datas, tokens totais, nº de páginas/blocos, família de versões se houver).
- Excedeu o orçamento ⇒ `cursor_proximo` + `restante_chars`. Invariante §2.6.
- Substitui/estende o `read_note` atual como caminho único de leitura integral (o `read_note` de trecho continua para o modo retrieval).

**`outline(id_ou_caminho)`**
- Mapa barato do documento: árvore de headings/slides/abas com offsets e contagem de tokens por seção. Permite ao agente decidir *o que* ler antes de gastar contexto — é a tool que transforma "ler 50 arquivos" em plano viável.

**`list_folder(caminho, recursivo=False, filtros=None)`**
- Manifesto da pasta: por item — `doc_id`, título, caminho relativo, tipo, datas, **tokens do parse canônico**, flag de canônico/duplicata por família (R1.3), status (`indexado|so_censo|quarentena|precisa_ocr`).
- Ordenação estável e documentada. Paginado por cursor como tudo. É a tool de *enumeração* que o caso "paper do projeto X" começa chamando.

**`pack_folder(caminho, budget_chars, cursor=None, politica='canonicos')`**
- O empacotador: devolve um bundle Markdown **manifest-first** — primeiro o sumário (o manifesto de `list_folder` + outline resumido por doc), depois os documentos concatenados na íntegra, cada um precedido de separador padronizado com `doc_id`, caminho original e metadados de citação.
- `politica`: `canonicos` (default — 1 membro por família de versões, R1.3), `todos`, `apenas_listados(ids)`.
- Orçamento estourado ⇒ corta **em fronteira de documento** (nunca no meio de um), devolve cursor. O agente monta o paper em múltiplas passadas com garantia de cobertura total e sem repetição.
- Ordem default: a do manifesto (estável). Nada de ranking aqui — pack é enumeração, não busca (invariante §2.5).

**Descriptions das tools** (mesma disciplina de R7.2/C1): ensinam o padrão de uso ao LLM cliente — *"para tarefas que exigem ler uma pasta inteira: `list_folder` → `outline` nos maiores → `pack_folder` com orçamento; para perguntas pontuais use `search`"*. O roteamento entre os dois modos é 100% do LLM cliente; nenhum classificador server-side.

### 3.4 Indexador lê do store — o ganho original de cache

- O laço de indexação consulta o store antes de qualquer parser; hit ⇒ pula direto para chunking/embedding. Rebuilds (R2.1, R3.1, mudança de chunking) deixam de pagar parse/OCR/conversão.
- Todos os produtores existentes gravam no store ao parsear: parsers modernos, rota LibreOffice (R1.1), OCR (R1.2), Docling (R1.5). A quarentena (R1.4) registra a falha; nunca grava entrada parcial.
- O passe 2 do dois-passes (R3.2) lê do store por construção — zero parse duplicado.

### 3.5 Exportadores — *materialized views* explícitas (Obsidian e afins)

- Comando/ação explícita do usuário (CLI + wizard R8.2): **"Exportar [pasta|base] como vault Markdown"** para um diretório de destino escolhido, obrigatoriamente fora das raízes indexadas (validado; recusa com mensagem clara).
- Cada doc vira `.md` com **frontmatter YAML**: `doc_id`, caminho original, datas, hash, rota de parse, tags derivadas da árvore de pastas; corpo = Markdown canônico.
- **Wikilinks derivados, não inventados:** menções a identificadores (`PO-CORP-007`) e siglas resolvidas (C2) viram `[[links]]` entre notas do vault — o grafo do Obsidian de graça, a partir de tabelas que já existem.
- **One-way, regenerável, descartável.** Re-export sobrescreve; edições do usuário no vault **não** voltam para o acervo nem para o índice. Sem sync bidirecional (ver §6). O vault é uma *view*, e o comando diz isso ao usuário.
- Incremental: re-export só do que mudou (mesma chave da §2.2).

### 3.6 Config e painel

- `[parse_store]` no config: ativado (default on), carência de GC, limite de disco com política de aviso (nunca despejo silencioso do que está em uso).
- Painel/relatório: tamanho do store, taxa de hit no último rebuild, entradas por rota, pendências de regeneração após bump de `parser_version`.

---

## 4. Subpacotes de entrega

| Sub | Escopo | Prioridade | Dono | Depende de |
|---|---|---|---|---|
| **J.a** | Núcleo do store (§3.1) + produtores gravando + GC | **P0** | desktop | — |
| **J.b** | Sidecar estruturado + `doc_id`/URI (§3.1–3.2) | **P0** | desktop | J.a |
| **J.c** | Tools `get_document` + `outline` + `list_folder` (§3.3) | **P0** | notebook (tools/MCP) | J.b |
| **J.d** | `pack_folder` + políticas de família (§3.3) | **P1** | notebook | J.c, R1.3 |
| **J.e** | Exportador vault/Obsidian (§3.5) | **P1** | qualquer | J.b, C2 (links) |
| **J.f** | Indexador lê do store; rebuild fast-path (§3.4) | **P0** | desktop | J.a |

Ordem de ataque sugerida: **a → f → b → c → d → e**. O par a+f entrega o ganho de custo imediato (rebuilds baratos antes das ablações R2.1/R3.1, que pagam rebuild); b+c entregam o requisito agêntico; d+e são as superfícies de produto.

---

## 5. Critérios de aceite por subpacote

**J.a**
- Byte-identidade: parsear o mesmo arquivo 2× (e em 2 máquinas) produz artefatos idênticos;
- suíte verde com store vazio, store populado e store deletado no meio da execução (regeneração on-demand);
- zero escrita fora do diretório do índice (teste com watcher de filesystem na raiz do acervo sintético);
- GC nunca remove entrada de hash presente no censo; sobrevive a interrupção (`kill`) sem corromper entradas (escrita atômica).

**J.b**
- `doc_id` estável sob renomeação/mudança de pasta do arquivo (mesmo conteúdo ⇒ mesmo id);
- sidecar: todo bloco tem offsets válidos no .md (property test: reconstruir o .md a partir dos blocos ⇒ idêntico);
- offsets/páginas suficientes para o contrato de spans do E4 (validar com o dono do E4 antes de congelar o schema).

**J.c**
- `get_document` devolve documento de 500 páginas completo via cursores, sem perda nem sobreposição (teste: concatenação das páginas == .md canônico);
- nenhum retorno truncado sem cursor (property test com orçamentos aleatórios);
- `outline` de doc grande responde <200 ms com store quente;
- caminho e `sc://` URI resolvem para o mesmo documento.

**J.d**
- Teste de agente (padrão do C1): em pasta sintética "projeto" com 30+ docs incluindo famílias de versões plantadas, um agente com contexto limitado consegue, só com `list_folder`+`outline`+`pack_folder`, cobrir 100% dos documentos canônicos em N passadas, sem repetição e sem corte intra-documento;
- `politica='canonicos'` nunca omite família inteira (o canônico sempre entra);
- separadores de citação carregam caminho original + `doc_id` em 100% dos docs do bundle.

**J.e**
- Export recusa destino dentro de raiz indexada;
- vault abre no Obsidian com grafo de wikilinks funcional (validação manual documentada + teste de sintaxe de frontmatter/links);
- re-export incremental toca só arquivos com chave alterada;
- deletar o vault e re-exportar ⇒ resultado idêntico (view descartável).

**J.f**
- Rebuild de vetores com store quente: **≥80% de redução** no tempo total vs. rebuild com re-parse (medir no corpus sintético com mix de PDF/OLE/OCR);
- índice resultante byte-equivalente ao de um build com store frio (o cache não pode mudar resultado);
- taxa de hit reportada no relatório da onda.

**Globais**
- Nenhuma métrica de ranking regride (as tools novas não tocam a fusão — verificar por ablação nula: dourado real antes/depois idêntico);
- disciplina VCE: nenhum nome real em fixtures, descriptions, docs ou mensagens de commit.

---

## 6. Anti-recomendações (decisões tomadas — não reabrir sem número)

1. **Escrever .md nas pastas do usuário.** Quebra o invariante read-only, polui taxonomia curada, dispara tempestade de sync (OneDrive/backup), cria loop com o watcher (F4-W) e vaza conteúdo de documentos restritos em texto plano. O caso "usuário quer o .md" é atendido por J.e (export explícito).
2. **Sync bidirecional com Obsidian/vault.** Transformaria a view em segunda fonte de verdade — conflitos, merge, corrupção do invariante §2.4. Se um dia houver demanda real de anotação, ela entra como camada separada de *anotações sobre doc_id*, nunca como escrita no acervo ou no store.
3. **Sumarização/síntese server-side no `pack_folder`.** O servidor recupera; o LLM raciocina. Um "resumo automático por documento" server-side exigiria LLM local, quebraria determinismo e duplicaria o trabalho do cliente.
4. **Pack sem orçamento ou com truncamento silencioso.** É o modo de falha clássico de tool para agente: o LLM acredita que viu tudo. Cursor explícito sempre.
5. **Segundo formato canônico por consumidor** (um .md "para Obsidian", outro "para agentes", outro "para o indexador"). Um único `ParseCanonico`; consumidores aplicam *rendering* próprio a partir dele (frontmatter do export é rendering, não formato novo).
6. **Ranking dentro de `list_folder`/`pack_folder`.** Enumeração é estável e neutra; relevância é trabalho do `search` e do agente. Misturar os dois torna o pack não-reprodutível.

---

## 7. Interações com pacotes existentes

| Pacote | Relação com J |
|---|---|
| R1.1 (LibreOffice) / R1.2 (OCR) / R1.5 (Docling) | Passam a **gravar no store** (produtores). OCR vira investimento único por documento. |
| R1.3 (dedup/famílias) | Fornece `doc_id`→caminhos e o conceito de canônico que `list_folder`/`pack_folder` consomem. |
| R1.4 (quarentena) | Falha de parse nunca grava entrada; tools de leitura reportam status `quarentena` no manifesto em vez de erro cru. |
| R2.1 / R3.1 (rebuilds de vetores) | Beneficiários diretos do J.f — fazer J.a+J.f **antes** dessas ablações para pagar o parse uma vez só. |
| R3.2 (dois passes) | Passe 2 lê do store por construção. |
| E4 (spans citáveis) | O sidecar (J.b) é o lar dos offsets; congelar schema em conjunto. |
| R7.1/R7.2 (tools + descriptions) | As 4 tools novas entram no pacote de tools com descriptions que ensinam o padrão enumerar→mapear→empacotar. |
| C1 (particionamento) | Inalterado: tools de acesso integral operam por base; cruzar bases continua sendo trabalho do LLM cliente. |
| C2 (glossário/menções) | Fonte dos wikilinks do export J.e. |
| R8.2 (wizard) | Ganha a ação "Exportar como vault Markdown" com escolha de destino validada. |
| F4-W (watcher) | Nenhum conflito: store fora das raízes observadas por construção (§2.1). |

---

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Divergência silenciosa .md ↔ sidecar | Um gera o outro deterministicamente; property test de reconstrução (J.b). |
| Store crescer sem controle | Zstd (texto extraído comprime 5–20×), GC por censo, limite com aviso no painel (§3.6). |
| `parser_version` esquecida em melhoria de parser ⇒ cache servindo parse velho | Regra de PR: qualquer mudança de saída de parser exige bump; teste de contrato que fixa hash do parse de fixtures conhecidas. |
| Tools de leitura integral usadas para exfiltração além do escopo da base | Mesmo modelo de confiança já vigente (o MCP client vê a base que o usuário conectou); nenhum privilégio novo — apenas conveniência sobre conteúdo já acessível via `read_note`. Registrar em `ARCHITECTURE.md`. |
| Pack de pasta gigantesca (10k docs) | Manifest-first + cursor: a primeira resposta é sempre o manifesto; o agente decide prosseguir. Nunca materializar o bundle inteiro em RAM. |

---

## 9. Fontes

> **Uma edição no documento recebido, feita em 30/08/2026 ao versioná-lo.** A
> atribuição institucional que acompanhava o Docling na linha abaixo casava com um
> token da lista de saneamento (`tests/test_saneamento.py`), e o guarda não
> distingue menção incidental de vazamento — nem deve. O link do projeto já
> identifica a origem, então a linha não perdeu informação. Nenhuma outra palavra
> do documento foi alterada.

- Anthropic — Contextual Retrieval e práticas de tool-use para agentes (descriptions que ensinam o padrão de uso): https://www.anthropic.com/news/contextual-retrieval
- Docling — Markdown estruturado como representação intermediária de parse: https://github.com/docling-project/docling · paper: https://arxiv.org/html/2501.17887v1
- MarkItDown (Microsoft) — conversão de formatos office para Markdown canônico: https://github.com/microsoft/markitdown
- Unstructured — parse-once / representação intermediária em pipelines enterprise: https://unstructured.io/insights/rag-pipeline-best-practices-enterprise
- MCP spec — tools e resources; múltiplos servidores por cliente: https://modelcontextprotocol.io/specification
- Repomix (padrão manifest-first + bundle sob orçamento para consumo por LLM, análogo ao `pack_folder`): https://github.com/yamadashy/repomix
- Obsidian — frontmatter/wikilinks (formato de vault): https://help.obsidian.md/
- Ablações e invariantes internos: `docs/colaboracao.md` §1/§4, `ROADMAP.md` (Pacotes), dossiês R1–R10 / C1–C7 / E-enterprise.
