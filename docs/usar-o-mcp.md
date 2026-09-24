# Usar o Segundo Cérebro pelo MCP

Oito ferramentas — três de pergunta (`search`, `read_note`, `neighbors`),
quatro de leitura (`list_folder`, `outline`, `get_document`, `pack_folder`) e
`overview` para o panorama. Provadas por stdio na suíte padrão, sem carregar
modelo (`tests/test_protocolo_mcp.py`).

## Ligar no Claude Code

O `.mcp.json` na raiz do projeto já traz a configuração. Abrindo o Claude Code
nesta pasta, ele oferece aprovar o servidor `segundocerebro` na primeira vez.
O Grok aberto na mesma pasta lê esse arquivo.

Depois do `pip install`, o servidor sobe sem `PYTHONPATH`:

```bash
py -m segundocerebro.mcp.server --base trabalho
```

`PYTHONPATH=src` só cabe num checkout que não foi instalado. O transporte
padrão é stdio: o cliente sobe um processo e o encerra junto com a sessão.
A leitura integral pode consultar originais e
reconstruir o cache dentro do índice, sem modificar o acervo. Sem `config.toml`,
`--indice index` continua valendo e o servidor se chama `segundocerebro`.

### Um processo para vários agentes

`--http` escuta só em `127.0.0.1`, com token Bearer. Vários agentes desta
máquina — e, por Tailscale Serve, as outras máquinas da tailnet — usam o mesmo
processo. O modelo carrega uma vez. A porta não abre na internet.

```bash
py -m segundocerebro.mcp.server --base trabalho --http
```

A porta padrão é **18788**. O token fica em `.mcp-http.json`, ao lado do
`config.toml`, e não entra na URL. O cliente manda `Authorization: Bearer …`.
Sem o token, ou com `Host` que não seja loopback nem um nome passado em
`--host-publico`, o servidor recusa. Se o comando achar o `tailscale` no
`PATH`, o DNSName desta máquina entra sozinho na lista de Host.

Para as outras máquinas da tailnet, na mesma máquina que escuta:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:18788
```

O endereço passa a ser `https://<nome>.ts.net/mcp`, só para nós da tailnet.
`tailscale funnel` publica essa porta na internet; para as suas máquinas o
comando é `serve`. O mesmo token vale nos dois endereços.

Cada aplicativo registra a URL uma vez, no escopo do usuário:

| Agente | Onde | Campo |
|---|---|---|
| Grok | `~/.grok/config.toml` | `url` e `headers` |
| Claude Code | `claude mcp add --scope user --transport http` | URL e `--header` |
| Codex | `codex mcp add --url` | `--bearer-token-env-var` |
| Antigravity | `~/.gemini/config/mcp_config.json` | `serverUrl` e `headers` |

### Várias bases

Desde 15/08/2026 uma instalação atende N acervos, cada um com índice e servidor
próprios — pessoal e trabalho sem se misturarem. Com `config.toml` no lugar:

```bash
py -m segundocerebro.mcp.server --base trabalho
```

O nome do servidor vira `segundocerebro-trabalho`, e índice, modelo e pesos saem
da base. Sem `config.toml` nada muda: o comando acima continua valendo e o
servidor continua se chamando `segundocerebro`.

Para não editar JSON à mão, o trecho de registro sai pronto:

```bash
py -m segundocerebro.mcp.registrar --base trabalho
```

Imprime na tela; com `--out .mcp.json` grava **mesclando**, preservando os outros
servidores MCP que já estiverem lá. `--todas` registra todas as bases de uma vez
— o que é conveniência, não isolamento.

**O controle de acesso é qual servidor você registra naquele cliente.** Registrar
só a base pessoal num projeto é fronteira dura — a ferramenta não existe na
sessão do agente. Registrar as duas e contar que o modelo escolha pela descrição
é conveniência, não garantia; para isso a descrição de cada base precisa dizer
de verdade o que ela cobre, porque é o único sinal que o modelo tem.

A **primeira busca demora ~80 s**: é o `e5-large` carregando. As ferramentas de
leitura não carregam o encoder. Depois disso as
buscas respondem em frações de segundo. O modelo é carregado sob demanda de
propósito — carregar na importação estoura o handshake do cliente MCP, e o modo
de falha seria "servidor não conecta", que não diz nada sobre a causa.

## Ligar no Claude Desktop — o segundo cliente

Um comando, sem editar JSON:

```bash
py -m segundocerebro.mcp.registrar --cliente claude-desktop --instalar
```

Grava em `%APPDATA%\Claude\claude_desktop_config.json`, **mesclando**: os outros
servidores MCP e as preferências do app ficam intactos, e o que mudou é relatado
na saída. Depois, fechar e reabrir o Claude Desktop — ele lê a configuração no
início, não recarrega em quente.

Sem `--instalar` o comando imprime o trecho e diz onde colar, que é o caminho
para qualquer outro cliente MCP por stdio (`--cliente generico`).

Duas diferenças em relação ao Claude Code, e são as duas que fazem o registro
manual falhar:

- **Os caminhos saem absolutos.** O Claude Desktop nasce em
  `C:\Windows\system32`, e ali `PYTHONPATH=src` não aponta para nada. O servidor
  subiria com `ModuleNotFoundError`, que o cliente mostra como "servidor não
  conecta" — silencioso quanto à causa. Por isso o trecho fixa `PYTHONPATH`,
  `--config` e `cwd`.
- **A primeira consulta ainda demora ~80 s.** No Claude Desktop isso aparece
  depois do servidor já ter conectado, na primeira `search` — não no início. Se o
  servidor aparecer como conectado e a primeira busca parecer travada, é a carga
  do modelo.

Sobre o `--instalar`: ele só existe para cliente cujo caminho **e** formato foram
conferidos. O VS Code fica fora de propósito — o `mcp.json` dele chama a seção
`servers`, não `mcpServers`, e o trecho gerado aqui não serve para ele.

## As oito ferramentas

**`overview()`** — panorama estatístico da base de conhecimento: total de documentos e trechos indexados, período temporal coberto (datas mais antiga e mais recente), formatos mais comuns, principais pastas de primeiro nível, taxa de sucesso da indexação e documentos digitalizados pendentes de OCR. Boa para chamar no início de uma sessão para orientar buscas ou planos de leitura.

**`search(consulta, k=8, contexto=1, pasta="", incluir_versoes_antigas=False, depois_de="", antes_de="")`** — trechos por significado e por termo
exato, fundidos por RRF. Devolve, para cada trecho: `id`, `arquivo`, `secao`,
`onde`, `texto`, `score`, `achado_por` (qual ranqueador o encontrou: denso,
lexical ou os dois) e `versoes` (número de versões da família). Quando há versões
superadas ou formatos alternativos colapsados, inclui listas `anteriores` e `formatos`
com `id`, `arquivo` e `data` para o agente comparar minutas com `read_note` ou `neighbors`.
O `contexto` anexa vizinhos em `antes` e `depois`, para o
caso "a resposta estava no parágrafo seguinte". Aceita `pasta` para restringir a
uma subpasta, `incluir_versoes_antigas=True` para não descartar versões superadas
de uma família, e filtros temporais `depois_de` e `antes_de` no formato ISO (`YYYY` ou `YYYY-MM-DD`).

**`read_note(id, janela=1)`** — o trecho pedido mais os vizinhos do mesmo
documento, para ler o contexto em volta. O `id` é o que veio da `search`.

**`neighbors(arquivo, limite=5)`** — documentos ligados a um arquivo por
identificador citado em comum: norma, lei, código de contrato, CNPJ, processo. E
devolve **por que** cada um está ligado, com o identificador e o trecho, para a
ligação ser conferível em vez de oracular.

As três acima servem o modo **pergunta**: você pergunta, o servidor devolve os
trechos que respondem. As quatro seguintes servem o modo **leitura** — quando a
tarefa não é "onde está X" e sim "escreva um relatório sobre esta pasta".

**`list_folder(pasta="", recursivo=False, cursor=0, max_itens=100, cursor_opaco=false)`** — o que
existe numa pasta: por documento, a `raiz`, um `id` estável quando já há hash, o tipo, a data, quantos
caracteres de texto ele tem indexados, se é a versão vigente da família e o
status (`indexado`, `quarentena`, `sem_texto`, `formato_nao_lido`, `so_censo`).
Com as raízes configuradas, inclui arquivos ainda não indexados por enumeração
de metadados: não abre conteúdo, não baixa placeholders e respeita exclusões.
Esses arquivos aparecem como `so_censo`, sem id e com motivo. Caminhos relativos
iguais em raízes diferentes são entradas distintas. A ordem é por caminho e raiz,
**nunca** por relevância. Quando há mais itens que o
orçamento, o retorno traz `cursor_proximo` e `restante`: a ferramenta nunca corta
em silêncio. O cursor inteiro é legado e não garante snapshot. `cursor_opaco=true`
(opt-in) carrega revisão da enumeração: se o acervo mudar entre páginas, a
continuação recusa com `cursor_desatualizado` — reinicie sem cursor. Sem raízes
declaradas, o campo `fronteira` avisa que só há dados do índice; falhas de
enumeração vêm em `aviso_censo`, sem fingir cobertura completa.

**`outline(documento, cursor=0, max_secoes=80)`** — o mapa de um documento sem
gastar contexto lendo o documento: as seções na ordem do texto, onde cada uma
está (página, slide ou aba) e quanto ocupa. É o que transforma "ler 50 arquivos"
em plano viável — o agente vê a estrutura, escolhe o que vale ler, e só então
gasta contexto. Aceita o caminho, o `id` de `list_folder` ou uma URI `sc://`.

**`get_document(documento, cursor=null, max_chars=8000)`** — todo o Markdown
canônico extraído, paginado sem sobreposição dos chunks. Aceita caminho relativo,
id ou URI `sc://` da própria base. Copie `cursor_proximo` na chamada seguinte
até `completo=true`; a ausência do cursor indica o fim. `total` e `restante`
contam caracteres Unicode, não tokens. O teto é 32.000 caracteres de Markdown
por resposta, além dos metadados; até 200 blocos com offsets e localizadores.
Os offsets são globais no canônico, não na fatia. Cite `documento.arquivo` e
`documento.raiz`, nunca o cache. `read_note` continua sendo leitura de trechos.

`estrutura` declara o contrato `blocos:1`: início inclusivo, fim exclusivo,
base zero, em code points Unicode. Cada bloco traz `ordinal` global, `trilha`
de seções e `pagina`/`slide` base um quando o parser os conhece (`null` nos
demais casos). A página de transporte não é a página do original. Use também
`versao` para identificar uma citação; o ordinal sozinho não sobrevive a reparse.
Detalhes e compatibilidade: [estrutura para citações](jb2-estrutura-citacoes.md).

A função serve a **versão indexada**, não uma cópia ao vivo. Com raízes, confere
tamanho e datas do original; se mudarem, pede reindexação. A continuação está
vinculada ao documento, base, rota e conteúdo canônico. Sem raízes, só serve
cache existente e declara `original_conferido=nao_configurado`. Um miss reabre o
original pelo portão existente, compara o hash e reconstrói o Parse Store.
Arquivos só no censo ou sem identidade precisam de indexação primeiro.
Se o caminho existir em mais de uma raiz, use id ou URI para desambiguar.

Não baixa placeholders nem inicia OCR novo: só restaura OCR previamente usado
na indexação. Extração sob demanda tem teto de 50 MB por arquivo (ou menor,
conforme a base), 60 s para formatos isolados e RAM limitada; arquivos demorados
devem passar pelo indexador. `limitacoes_extracao`, `aviso_ocr` e `fronteira`
distinguem texto extraído de reprodução completa de imagens, tabelas e páginas.
Erros de execução retornam `isError=true` com código e orientação.

**`pack_folder(pasta="", budget_chars=8000, cursor=null, politica="canonicos", ids=null, recursivo=false, estrito=false)`**
— bundle Markdown da pasta: primeiro o manifesto, depois os documentos canônicos
inteiros. `politica=canonicos` traz um membro por família de versões (a vigente);
`todos` traz cada arquivo; `apenas_listados` exige `ids`. `budget_chars` conta
caracteres Unicode, não tokens. Quando o orçamento estoura, o corte é na
**fronteira de documento**, nunca no meio, e o retorno traz `cursor_proximo`.
`estrito=true` (opt-in) nunca deixa o Markdown passar do teto: documento maior
que a página vai para `get_document`, com id e próximo passo. Continue até
`completo=true`. Não resume e não ranqueia. Arquivo só no censo, sem hash ou
sem canônico aparece em `omitidos`, com motivo. Cite `arquivo` e `raiz` do
separador, nunca o cache.

O padrão de uso: **`list_folder` para saber o que existe → `outline` para mapear
→ `pack_folder` para cobrir a pasta sob orçamento, ou `get_document` para um
arquivo. `search` para perguntas pontuais.**

O `id` merece uma linha: ele vem do **conteúdo** do arquivo, não do caminho.
Renomear ou mover não muda o id; editar muda. Quando o mesmo conteúdo está em
mais de um caminho — 1 em 10 arquivos do acervo corporativo —, o id resolve
sempre para o mesmo caminho preferido, pela mesma regra de versão vigente que a
`search` usa. Documento que o servidor nunca conseguiu abrir (placeholder de
nuvem, formato não lido) aparece **sem** id e com o motivo escrito ao lado, em
vez de sumir da lista.

Oito, e não as cinco originalmente propostas no ROADMAP. `search` e `read_note` fecham
o laço básico e foram as duas únicas até a F3. A `neighbors` entrou na F4 por um
motivo diferente: o traço de uso real mostrou o limite que ela rompe. Um plano
que termina em "certificação ISO 42001" e a norma, em outra pasta, não têm nome,
pasta nem vocabulário em comum — nenhum peso de fusão os aproxima, porque o que
faltava não era precisão, era uma **aresta**. A `list_recent` continua hipótese.

A `glossary` que o ROADMAP previa **não virou ferramenta**, e por decisão: o
glossário de siglas entrou como expansão de consulta dentro da `search`, invisível
para o cliente. Uma ferramenta de glossário obrigaria o modelo a saber que precisa
consultá-la antes de buscar — mais uma chamada por consulta e uma chance de ele
não fazer. Expandir por dentro sempre funciona.

## O que o servidor não faz, e por quê

Não existe ferramenta que gere texto. Nada de `answer`, `summarize` ou `explain`.
Isso não é omissão: é a invariante 2 do `ARCHITECTURE.md`. Uma etapa de geração
no servidor reintroduziria custo por consulta e amarraria o projeto a um
fornecedor, que é exatamente o que a arquitetura existe para evitar. Quem gera
texto é o cliente; o servidor recupera e devolve procedência.

Multi-hop também é do cliente. As oito ferramentas são primitivas componíveis, e
o laço de agente é quem compõe.

## O que esperar, honestamente

A tabela é de **18/08/2026**, num corpus de então (1.601 documentos, 92.137
trechos, 45 perguntas, `docs/ablacao-f2.md`). A coluna "atual" daquela medição
é sem reranking, com famílias de versão e com um glossário de 10 siglas. Não é
o tamanho do acervo de hoje e não se compara com o piso posterior. O reranking
continua desligado por padrão: naquela medição, `rerank = 0.25` levava o
recall@1 a **0,678** e a consulta ficava cerca de 8× mais lenta. Nessa
métrica o glossário, de graça, rendia mais que o reranking.

| | baseline | atual |
|---|---:|---:|
| recall@1 | 0,467 | **0,667** |
| recall@5 | — | **0,885** |
| recall@10 | 0,800 | **0,930** |
| MRR@10 | 0,592 | **0,787** |
| nDCG@5 | — | **0,793** |
| perguntas do usuário: MRR | 0,557 | **0,724** |
| perguntas do usuário: recall@10 | 0,833 | **1,000** |

As seis perguntas escritas de memória pelo usuário — o subconjunto sem viés de
construção — são **todas** encontradas dentro do top-10.

Naquela passada, famílias de versão já traziam a vigente e citavam as anteriores
(5 de 6 armadilhas, `ablacao-familias.md`). Juntar todas as fontes de uma
pergunta multi-hop no top-10 só acontecia em 1 de 5.

Hoje o servidor indexa e-mail (`.msg`, `.eml`) e PDF com texto. PDF digitalizado
passa pelo OCR por padrão; página que o motor não lê fica `vazio` no registro,
visível. A lista fechada de formatos está em [`comecar.md`](comecar.md).

## Ensinar as siglas da sua casa

O ganho mais barato do sistema, e o único que ele não tem como adivinhar. Quando
você pergunta "o acordo de proteção de dados" e o contrato diz "DPA", nada liga as
duas formas; o contrário também.

No painel, seção **Siglas da sua casa**: a sigla como aparece nos arquivos, o que
ela significa, e pronto. As buscas passam a achar os dois jeitos, **sem custo
nenhum no tempo de resposta** — é consulta a dicionário antes de qualquer
ranqueador.

Medido em 18/08/2026 (`ablacao-glossario.md`) com 10 siglas: recall@1 0,644 →
**0,667**, nDCG@5 0,760 → **0,793**, e **0,571 → 0,724 de MRR nas perguntas
escritas de memória** — o subconjunto que mais se parece com o uso real, porque no
uso real ninguém consulta o nome do arquivo antes de perguntar. Zero regressões.

O dicionário **nasce vazio**, e isso é resultado de medição, não economia de
trabalho: a metade genérica do dicionário de teste — mês abreviado, que serviria a
qualquer acervo — deu **zero**, e as siglas da empresa deram o ganho inteiro. Não
há dicionário embutido porque um dicionário embutido não ajudaria ninguém.

## O que fazer com o que você encontrar

Anotar a pergunta que falhou, com o arquivo que deveria ter respondido. É isso
que vira o conjunto dourado v2 — o atual tem **39 das 45 perguntas escritas a
partir de nomes de arquivo**, viés conhecido e registrado, e perguntas reais são
o que corrige isso.
