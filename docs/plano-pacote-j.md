# Plano — Pacote J, camada de acesso ao corpus, conferido no código

**Data:** 30/08/2026 · **Conferência:** notebook · **Especificação recebida:**
[`pacote-j-camada-acesso-corpus.md`](pacote-j-camada-acesso-corpus.md)

O pacote J chegou marcado *FINAL* e pediu, no próprio texto, a única coisa que
faltava para ele ser executável aqui: **"mapeie cada contrato para o layout real
vigente antes de criar arquivo"**. Este documento é esse mapeamento, feito
executando — não lendo. É o mesmo tratamento que os dossiês `R1–R10` e `C1–C7`
receberam no [`ROADMAP.md`](../ROADMAP.md), e pelo mesmo motivo: a especificação
foi escrita contra uma base que mudou de forma desde a última avaliação externa.

O que segue está em três partes: **o que já existe** (e não se duplica), **o que
o pacote assume e não é verdade aqui** (dez itens, cinco deles medidos), e **a
ordem revisada com donos, efeito mínimo e critério de encerramento** — os três
campos que a regra de ouro exige antes de abrir branch e que a especificação não
traz.

---

## 1. O requisito é real, e não tem tool que o sirva

O produto tem **um** modo de consumo: pergunta curta → top-k trechos → o cliente
responde. `search`, `read_note` e `neighbors` servem esse modo.

O modo novo é **ingestão integral dirigida por agente**: *"escreva um paper sobre
o projeto X"* apontando para uma pasta com dezenas de arquivos. Nenhuma
combinação das três tools de hoje resolve isso — `read_note` devolve um trecho e
sua janela, `search` devolve top-k por relevância, e nenhuma das duas enumera,
mapeia ou empacota. O agente que tentar hoje lê o que a busca escolher e **não
sabe o que não viu**, que é exatamente o modo de falha que a
[`truncagem-silenciosa.md`](truncagem-silenciosa.md) documenta em outra camada.

Serve base desconhecida: **sim, e diretamente.** Quem aponta o produto para uma
pasta que nunca vimos quer, no primeiro dia, tanto perguntar quanto *ler tudo*.
O pacote J é produto, não laboratório.

---

## 2. O que já existe — estender, não criar

A especificação avisa que os nomes são sugestão. Estes são os pontos onde o
contrato sugerido **já tem dono no código**, e criar arquivo novo seria
duplicação:

| Contrato do pacote J | Onde já mora | Estado |
|---|---|---|
| `ParseCanonico.blocos[]` | `ingest/document.py::Block` — `heading_path`, `text`, `locator`, `kind` | **Existe**, em memória, nunca persistido |
| `blocos[].trilha de headings` | `Block.heading_path`, e `chunks.trilha` no registro | **Existe nos dois lugares** |
| `blocos[].página/slide/aba` | `Block.locator` (`"p. 12"`, `"slide 4"`, `"Orçamento!A1:F40"`) | **Existe** |
| `meta.parser_version` | `parsers/__init__.py::register(version=)` + `parser_version_for()` + coluna `documentos.parser` | **Existe**, por extensão |
| `meta.hash` | `ParseResult.sha256` → `documentos.sha256` | **Existe**, com buraco medido (§3.2) |
| `meta.contagem de tokens` pelo tokenizador real | `ingest/chunking.py::contar` | **Existe**, por chunk |
| `meta.flags` (`fonte=ocr`, `convertido_de`) | `ingest/natureza.py` → `familia_real`, `extensao_mente`, `digitalizado`, `tem_sumario_nativo` | **Existe e é persistido** |
| status `quarentena` no manifesto | tabela `quarentena` (`R1.4`, PR #36) | **Existe** |
| `politica='canonicos'` (1 por família) | `retrieve/familias.py::familias_de` + `_por_vigencia` | **Existe** — e não é `R1.3` (§3.1) |
| wikilinks derivados do `J.e` | `retrieve/identificadores.py` + tabela `mencoes` + `retrieve/glossario.py` | **A fonte existe**; falta só a renderização |
| GC por censo | `census.py` + `index/reconciliar.py` (detecção de movido por `sha256`) | **A matéria-prima existe** |
| `[parse_store]` no config | `config.py` com a guarda de chave desconhecida do `Q11`, derivada do modelo | Seção nova entra pela guarda; barato |

E o que **não existe em forma nenhuma**: o parse store físico, a renderização
Markdown canônica, offsets no Markdown, `doc_id` público, a URI `sc://`, as
quatro tools de acesso integral, o exportador de vault, e a dependência `zstd`.

---

## 3. Onde a especificação não bate com esta base

Dez itens. Os marcados **medido** foram apurados executando contra o registro
corporativo (2.156 documentos) ou contra o código, em 30/08/2026.

### 3.1 A dependência `J.d → R1.3` está errada aqui

A tabela de subpacotes dá `J.d` como dependente de `R1.3` (dedup/famílias).
`R1.3` está **absorvido por `C6`** no `ROADMAP.md` desde 24/08/2026, e a
instrução vigente para o desktop é **não implementar** — o complemento mostrou
que MinHash a 0,85 fundiria o que `retrieve/familias.py` separa de propósito, e
reintroduziria a `g045`.

O conceito de canônico que `pack_folder` precisa **já existe**, por nome de
arquivo, em `familias.py`, e é do notebook. A dependência correta é:

> `J.d` → `retrieve/familias.py` (existe hoje) · `C6` **só** se o pack precisar
> distinguir *família de versões* de *grupo de formatos* — o mesmo documento em
> `.docx` e em `.pdf`.

### 3.2 `doc_id` derivado de hash não cobre o acervo inteiro — **medido**

`ParseResult.sha256` só é preenchido quando os bytes foram lidos. O portão de
leitura recusa placeholder de nuvem **antes** de abrir, porque abrir dispara
download — é invariante do projeto, não otimização.

No registro corporativo, hoje:

| | |
|---|---|
| documentos | **2.156** |
| sem `sha256` | **29 (1,3%)** — 27 `sem_parser`, 2 `travado` |

E `list_folder` promete `doc_id` para item com status `so_censo`, que é
justamente a população que nunca foi aberta. **Ou o manifesto admite item sem
`doc_id`, ou o censo passa a hashear placeholder — e hashear placeholder é
baixar o acervo.** É decisão, não detalhe de implementação; a recomendação é a
primeira, com o campo explicitamente nulo e um motivo legível, nunca string
vazia.

### 3.3 "Um conteúdo, N caminhos" é 1 em 10, não caso de borda — **medido**

| | |
|---|---|
| paths com hash | **2.127** |
| conteúdos distintos | **1.904** |
| paths byte-idênticos a outro | **223 (10,5%)** |

O "um preferido" da §3.2 da especificação não é refinamento: um décimo do acervo
cai nele. E hoje **não há regra declarada** — `store.path_ok_por_sha256` devolve
o primeiro path com status `ok` que o SQLite entregar, que é ordem de indexação.
Para um agente que promete workflow repetível *"semana após semana com resultado
idêntico"*, ordem de indexação é aleatoriedade com aparência de determinismo.

A regra de preferência tem de ser declarada e testada junto com o `doc_id` — e a
candidata natural é a mesma de `familias.py::_por_vigencia`, para não haver duas
noções de "o principal" no mesmo produto.

Além disso: **não há índice em `documentos.sha256`.** Resolver
`doc_id → caminhos[]` hoje é varredura de tabela. É barato de consertar e caro de
esquecer — a lição do N+1 deste repositório é que a *forma* do acesso é a mesma
no índice de teste e no acervo real, e só o N muda.

### 3.4 `get_document` não pode ser servido dos chunks — **medido**

Havia um atalho aparente: a tabela `chunks` guarda o texto inteiro, ordenado por
`ordinal`. Concatenar seria `get_document` sem store nenhum.

Não fecha. Os chunks se **sobrepõem** em 200 caracteres, e `_juntar_pequenos`
funde blocos pequenos antes de cortar. Medido, num bloco único de 14.399
caracteres:

| | |
|---|---|
| chunks gerados | 9 |
| soma dos chunks | 15.999 caracteres |
| inflação | **+1.600 (+11,1%)**, em 8 emendas |

O critério de aceite do `J.c` — *"concatenação das páginas == .md canônico"* —
falharia por construção. **`get_document` precisa do store**; não há atalho.

### 3.5 Mas `outline` e `list_folder` **têm** atalho, e isso muda a ordem

As duas tools de *mapa* não precisam de nenhum byte do parse store:

- `outline` = `chunks.trilha` (trilha de headings) + `chunks.locator`
  (página/slide/aba) + `ordinal`, tudo já no registro e já indexado por `path`;
- `list_folder` = `documentos` (tipo, datas, status, `n_chunks`) + `census.py`
  para o que está no disco e fora do índice + `quarentena` + `familias_de`.

Só as duas tools de *conteúdo* (`get_document`, `pack_folder`) dependem do
store. Isso importa para o calendário: **o notebook começa o requisito agêntico
sem esperar o store**, e a ordem sugerida (a → f → b → c → d → e) deixa de ser a
única possível. Ver §5.

### 3.6 Determinismo byte-a-byte é asserção sobre coisas que não são determinísticas

O invariante §2.2 diz *"mesmo arquivo, mesmo parser ⇒ mesmo Markdown, byte a
byte, em qualquer máquina, hoje e daqui a um ano"*. Três rotas de parse do
produto saem do nosso controle:

- `ingest/converters/libreoffice.py` — binário externo, versão do sistema;
- `ingest/ocr.py` — motor de ML, pesos e versão do runtime;
- `reader.py::_recalcular_planilha` — recálculo de fórmula pelo mesmo LibreOffice.

A chave da entrada tem de incluir **a versão do motor externo**, não só
`parser_version`. Sem isso, um upgrade de sistema que troca o LibreOffice deixa o
cache servindo o parse velho para sempre — e ninguém commitou nada, então a
"regra de PR" que a §8 da especificação propõe como mitigação **não dispara**.
Este é o único ponto onde o pacote J tem risco sub-declarado, e é o mais caro de
todos, porque o sintoma é conteúdo desatualizado servido com confiança.

Leitura honesta do invariante para essas três rotas: *determinístico dado
`(hash, parser_version, rota, versão do motor)`*. E para OCR, nem isso — o motor
pode não ser determinístico entre execuções na mesma máquina. Ou o OCR grava com
a versão do motor na chave e aceita reprocessar no upgrade, ou fica fora do
contrato de byte-identidade e o teste do `J.a` o exclui **por declaração**, nunca
por omissão.

### 3.7 A tabela de donos chega desatualizada

`J.a`, `J.b` e `J.f` — os três P0 do lado de infraestrutura — estão atribuídos ao
**desktop**. Os créditos do Grok acabaram e o notebook assumiu os pacotes do
desktop em 30/08/2026, por autorização explícita do usuário
([`colaboracao.md`](colaboracao.md) §6). Ou os três também são do notebook, ou o
P0 não anda. Proposta na §5.

### 3.8 `sc://<base>/<doc_id>` encosta no invariante 7

O invariante 7 diz que isolamento entre bases é **físico**: um diretório de
índice e um processo por base, nunca filtro de metadado. O store dentro do
diretório do índice respeita isso por construção — bom.

Mas a URI nomeia a base **dentro do endereço**, e uma tool que aceite `<base>`
como parâmetro reintroduz "base como filtro" pela porta dos fundos. A regra que
fecha: o servidor já é um processo por base, então `<base>` na URI é
**conferência** — não casou com a base do processo, é erro —, nunca seletor.
Escrever isso no `ARCHITECTURE.md` junto com a URI, não depois.

### 3.9 `get_document` "substitui/estende o `read_note`" — é adição, não substituição

`read_note` é uma das três tools da superfície MCP declarada no `CLAUDE.md`,
documentada em [`usar-o-mcp.md`](usar-o-mcp.md) e com cliente instalado em duas
máquinas. O próprio pacote diz depois que *"o `read_note` de trecho continua"* —
então o verbo certo é acrescentar. Registrado para que a implementação não leia
"substitui" e remova uma tool pública.

### 3.10 As quatro tools não cabem em `mcp/server.py` — **medido**

`mcp/server.py` tem 338 linhas, e `construir` tem **148** — já declarada em
`FUNCOES_ACIMA_DO_TETO` de `tests/test_tamanho_dos_modulos.py`, cuja tabela **só
desce**. Quatro tools novas com descriptions que "ensinam o padrão de uso" não
entram ali: o teste reprova, e é para isso que ele existe.

`J.c` nasce dividido (`mcp/leitura.py` ou equivalente), com `construir` apenas
registrando. Não é preferência de estilo; é a única forma do PR ficar verde.

---

## 4. O que o pacote J acerta, e vale repetir

Três coisas, para não se perderem no meio das dez correções:

- **A anti-recomendação 1** (nunca escrever `.md` nas pastas do usuário) é o
  invariante que este repositório já tem, dito melhor: ela nomeia a tempestade de
  sync do OneDrive e o laço com o watcher (`F4-W`), que são consequências que a
  nossa formulação não explicitava.
- **Cursor explícito sempre** (§2.6) é a lição da truncagem silenciosa aplicada a
  uma superfície nova, antes de o defeito acontecer. É a primeira vez neste
  projeto que uma classe conhecida é fechada **antes** da primeira instância.
- **Manifest-first** resolve o caso "pasta de 10k documentos" sem heurística e
  sem RAM: a primeira resposta é sempre o manifesto, e o agente decide. É a mesma
  escolha de "primitivas componíveis, o loop é do cliente" do invariante 3.

E o Obsidian volta ao projeto pela porta certa. O `CLAUDE.md` diz que ele foi
deliberadamente **não** adotado, e isso continua valendo para a *entrada*: não há
vault, não há wikilink no acervo, o grafo é derivado. O `J.e` é **saída** — uma
*view* descartável, one-way, gerada por comando explícito. Não reintroduz a
premissa errada.

---

## 5. A ordem revisada, com donos

A especificação sugere **a → f → b → c → d → e**. Com o §3.5 medido, há uma ordem
melhor, e o motivo é de calendário: ela deixa duas frentes andarem em paralelo em
vez de serializar tudo atrás do store.

**`J.b` divide em duas metades com dependências diferentes:**

| Metade | O que é | Precisa do store? |
|---|---|---|
| **`J.b1`** | `doc_id` público, índice em `documentos.sha256`, resolução `doc_id → caminhos[]`, regra de preferência declarada, URI `sc://` | **não** — a coluna já existe |
| **`J.b2`** | sidecar estruturado com offsets no Markdown canônico | **sim** |

Com isso:

| Onda | Subpacote | Dono proposto | Por quê |
|---|---|---|---|
| **1** | `J.b1` (ids) · `J.c-mapa` (`outline`, `list_folder`) | notebook | Não dependem de nada. Entregam metade do requisito agêntico já |
| **1** | `J.a` (store) · `J.f` (indexador lê do store) | desktop **se houver crédito**, senão notebook | Paga o rebuild das ablações `R2.1`/`R3.1` antes de elas rodarem |
| **2** | `J.b2` (sidecar) · `J.c-conteúdo` (`get_document`) | notebook | Depende do `J.a` |
| **3** | `J.d` (`pack_folder`) | notebook | Depende do `J.c` completo e de `familias.py` — **não** de `R1.3` |
| **4** | `J.e` (export vault) | qualquer | Depende do `J.b2` e das menções, que já existem |

**O que isso muda no plano existente:** `J.a`+`J.f` entram **antes** da onda 5
(`R3.1`+`C4.1`+`R2.1`, o rebuild coordenado), porque é ela que paga o
investimento. As tools ficam adjacentes à onda 7 (`R7.1`/`R7.2`), com a diferença
de que `J.c-mapa` não espera ninguém.

**Nota de calendário, honesta:** o pacote J tem seis subpacotes e um deles
introduz dependência nova. Não cabe em dois dias. O que cabe, e entrega valor
sozinho, é `J.b1` + `J.c-mapa` — enumerar e mapear, que é o que transforma "ler
50 arquivos" em plano viável para o agente, mesmo sem `pack_folder`.

---

## 6. Efeito mínimo e critério de encerramento — o que faltava

A regra de ouro exige, **antes** de abrir a branch: hipótese falsificável, efeito
mínimo com fatia declarada, critério de encerramento, e a classe generalizada
(regra 12). A especificação traz critérios de aceite — bons — mas só o `J.f` tem
número.

Para subpacote de *feature*, "efeito mínimo" não é Δ de métrica: é **a classe de
defeito que passa a ser impossível**, com o teste que a pega sozinho. Preenchido
aqui para que cada branch abra completa:

| Sub | Hipótese / efeito mínimo | Classe generalizada — quem passa a pegá-la |
|---|---|---|
| `J.a` | Parsear duas vezes o mesmo arquivo produz o mesmo byte, em duas máquinas | *Cache que serve parse velho depois de o parser mudar* — teste de contrato fixando o hash do parse de fixtures conhecidas, com a **versão do motor externo** na chave (§3.6) |
| `J.b1` | `doc_id` sobrevive a renomear e a mover; os 223 caminhos duplicados resolvem para um preferido **declarado** | *Identidade por caminho num acervo que move arquivo* — teste que renomeia a fixture e exige o mesmo id, e que exige preferência estável sob duas ordens de indexação |
| `J.b2` | Reconstruir o `.md` a partir dos blocos devolve o `.md` | *Divergência silenciosa entre renderização e estrutura* — property test de reconstrução |
| `J.c` | Nenhum retorno truncado sem cursor, sob orçamentos aleatórios | *A tool que faz o agente acreditar que viu tudo* — property test de orçamento aleatório sobre todas as tools de conteúdo, com a lista de tools **derivada do servidor**, não escrita à mão |
| `J.d` | Um agente com contexto limitado cobre 100% dos canônicos em N passadas, sem repetição e sem corte intra-documento | *Cobertura que o agente não consegue auditar* — o teste de agente do `C1`, com famílias plantadas |
| `J.e` | Export recusa destino dentro de raiz indexada; re-export idêntico | *Artefato derivado escrito dentro do acervo* — teste com watcher de filesystem na raiz sintética, que serve os cinco subpacotes |
| `J.f` | Rebuild com store quente ≥80% mais rápido, e índice **byte-equivalente** ao de store frio | *Cache que muda o resultado* — comparação de índice frio × quente na suíte |

**Critério de encerramento, global:** o `J.f` é o único com número, e empate
encerra. Se a redução medida do rebuild ficar abaixo de 80% no corpus sintético
com mix de PDF/OLE/OCR, o `J.f` fecha com "hipótese refutada" e o store continua
valendo pelos outros consumidores — não se pede outra grade.

**Ablação nula, obrigatória:** o pacote J não toca ranking, e provar isso é uma
passada do dourado antes/depois com **Δ exatamente zero**. Não é "não regrediu
dentro do IC": é zero, porque nenhuma linha do caminho de consulta muda. Δ
diferente de zero significa que alguém mexeu no que não devia.

---

## 7. O que fica fora, e por quê

- **MCP resources** como segunda superfície (§3.2 da especificação, marcado
  "opcional"): registrado e não priorizado. Duas superfícies para o mesmo
  conteúdo é a anti-recomendação 5 aplicada ao transporte, e o ganho depende de
  clientes que hoje não usamos.
- **Sync bidirecional** e **escrita no acervo**: anti-recomendações 1 e 2, e são
  invariante deste repositório antes de serem decisão do pacote J.
- **Qualquer síntese server-side** no `pack_folder`: invariante 2, sem discussão.

---

## 8. Paths, quando cada branch abrir

Nenhuma linha de código foi escrita nesta passada. Registrado aqui para que a
primeira branch já abra com a lista fechada, e para que a sessão paralela saiba o
que **não** é dela:

- `J.a`/`J.f` tocam `index/indexer.py` (o laço) e criam módulo novo em `ingest/` —
  é a fronteira do desktop, e cruzar ranking com o laço continua sendo dois PRs.
- `J.b1` toca `index/store.py` (coluna e índice) e cria módulo de identidade.
- `J.c`/`J.d` tocam `mcp/server.py`, que é **"um de cada vez"** por
  [`colaboracao.md`](colaboracao.md) §1, e criam `mcp/leitura.py` (§3.10).
- `J.e` cria comando novo e toca o painel — painel também é "um de cada vez".
