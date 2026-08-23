# CLAUDE.md — Segundo Cérebro RAG

Guia de desenvolvimento para o Claude Code neste projeto.

## Dois setups desde 20/08/2026 — ler antes de tocar em qualquer coisa

Há um segundo computador (desktop, duas GTX 980 Ti, corpus novo, Grok Build).
As regras são de [`docs/colaboracao.md`](docs/colaboracao.md), que é a **única**
fonte, mais a skill
[`.claude/skills/segundo-cerebro-notebook/SKILL.md`](.claude/skills/segundo-cerebro-notebook/SKILL.md).
Este notebook é o lado do **acervo corporativo e do conjunto dourado real**.

Ninguém commita em `main`; cada lado trabalha na sua branch e entra por PR.

**Nenhum dado do acervo real vai para o Git, e o repositório é público.** O que
a auditoria de 20/08 mostrou, e que vale como regra e não como episódio:

- A lista por nome no `.gitignore` **falha em silêncio** no arquivo seguinte.
  Quatro `metricas-f2-*` foram commitados localmente sem cair em nenhuma regra.
  Por isso `docs/metricas-*.md` virou padrão. Relatório por pergunta **sempre**
  cita nome de arquivo do acervo — é o que ele é.
- **Vocabulário de teste vem da VCE**, a empresa fictícia de `eval/sintetico/`.
  Sigla real em teste ou docstring é vazamento com aparência de código. O
  dicionário publicável é `eval/glossario.example.toml`.
- Ao sanear, `\bSIGLA\b` **não** casa dentro de literal como `'\nRDE = ...'`: o
  caractere antes do `R` é o `n` da escapada, que é caractere de palavra. Auditar
  com o padrão e com o caso escapado.
- Dado real que **já estava público** antes desta auditoria, e que segue lá:
  `retrieve/familias.py`, `tests/test_familias.py` (nome de arquivo real) e
  `docs/arquitetura-tecnica.md` (sigla interna). Tratar quando houver uma branch
  que toque esses arquivos por outro motivo.

---

## O que é este projeto

Servidor **MCP** de recuperação sobre base de conhecimento pessoal/corporativa.
Não gera texto, não tem UI. Ver [ARCHITECTURE.md](ARCHITECTURE.md) para as
decisões e [ROADMAP.md](ROADMAP.md) para as fases.

## Estado atual

**F1 fechada, F2 fechada em 18/08/2026, F3.5 concluída. Da F3 falta só um ato
humano.** Ler `docs/estado-f1.md` primeiro — é o retomador de
contexto: o que está pronto, os números medidos, as decisões com motivo e as
armadilhas já encontradas. Para usar o sistema, `docs/usar-o-mcp.md`.

A ordem do ROADMAP foi **invertida em 13/08/2026**: a F3 (superfície MCP) passou
na frente da F2 (reranking), para que o uso real diga qual é o gargalo antes de
otimizar precisão. Motivo registrado no ROADMAP.

Resumo de uma linha: parsers, chunker, índice e recuperação híbrida prontos com
200 testes; índice reconstruído com `e5-large` (11.208 chunks, 100% do texto
embeddado) e **a F1 passou a bater o baseline por 11,1 pontos de recall@1**
(0,644 contra 0,533) e 7,2 de MRR. Ver `docs/ablacao-f1.md`.

Antes de ler qualquer número anterior a 13/08: `docs/truncagem-silenciosa.md`.
Três defeitos encadeados deixavam 80,7% do texto fora do vetor, e duas
conclusões da ablação de 12/08 estão **retratadas** — o peso ótimo do denso não
é zero (é o sinal mais forte), e a tensão entre nome e conteúdo não é
irreconciliável.

O critério de medição mudou em 12/08: baseline e busca ranqueiam o **mesmo
universo** (`eval.rodar --prefixo`), e seis perguntas cuja fonte é `.msg` ou PDF
digitalizado saem da média dos dois lados, anotadas com motivo no conjunto
dourado. OCR e email são F4 — decisão registrada, não esquecimento.

**F0 concluída em 11/08/2026.** Censo, conjunto dourado de 51 perguntas com
fonte conferida, harness de métricas e baseline por nome de arquivo.

```bash
cp census.example.toml census.toml               # raízes reais, não versionado
py -m segundocerebro.census --config census.toml --out docs/censo.md
py -m eval.rodar --out docs/metricas-f0.md       # métricas do baseline
py -m pytest tests/ eval/ -q
```

Corpus medido: 699 arquivos, 444 de conhecimento, **0 placeholders**. PDF (208)
e DOCX (119) são 74% — a F1 cobre esses dois. XLSX são 14, fora do caminho
crítico. Baseline sob o critério novo (45 perguntas, mesmo universo):
recall@1 = 0,533 e recall@10 = 0,844 na subárvore de dev, 0,444 e 0,800 no
corpus completo — as referências das portas no ROADMAP.

**F3.5 definida em 14/08/2026** — bases e painel de ajuste, entre a F3 e a F2.
Ver [`docs/painel-de-ajuste.md`](docs/painel-de-ajuste.md) e a seção de bases do
`ARCHITECTURE.md` §2. Duas necessidades no mesmo artefato: um acervo por base,
com índice e servidor MCP separados (invariante 7), e ajuste de recuperação sem
código. Daí as invariantes 6 e 7 acima.

**Bloco A concluído em 15/08/2026.** `config.py` com `[[base]]`, `[padrao]` e
`[maquina]`, lido pelo servidor MCP, pelo indexador e pelo eval; `--base` nos
quatro pontos de entrada. 285 testes. O `census.toml` continua valendo — sem
`config.toml`, uma base única é sintetizada e **nada reindexa**.

```bash
py -m segundocerebro.index.indexer --base trabalho
py -m segundocerebro.mcp.server --base pessoal
py -m eval.rodar --base trabalho --retriever hibrido
```

**Bloco B concluído em 15/08/2026.** Conjunto dourado **por base** —
`dourado` na configuração, arquivo por base e não filtro, pelo mesmo argumento
da invariante 7; o campo `base` da pergunta é conferência, não fronteira. E
`mcp.registrar`, que gera o trecho de `.mcp.json` mesclando com o que já existe.
303 testes.

```bash
py -m segundocerebro.mcp.registrar --base trabalho          # imprime
py -m segundocerebro.mcp.registrar --todas --out .mcp.json  # mescla
```

**Bloco C — API concluída em 15/08/2026, falta a tela.** `painel/app.py` em
Starlette (não FastAPI: `starlette`, `uvicorn` e `httpx` já vêm com o `mcp`),
`painel/medir.py` com o encoder aberto uma vez só, `config.gravar()` com escrita
atômica. 332 testes. Duas regras moram no servidor, não na tela, porque regra que
só existe no JavaScript é decoração: **salvar exige ter medido** (invariante 4) e
**a classe cara não passa pela API de ajuste**.

```bash
py -m segundocerebro.painel     # 127.0.0.1, porta livre, token na URL
```

**Indexação do corpus completo concluída em 16/08/2026, 02:46.** 1.601
documentos processados (o conjunto filtrado que `iter_files` enumera, **não** os
3.154 do censo bruto — confundir os dois reporta 45% quando o real é 91%), 1.458
com texto, **92.125 chunks**, zero fantasmas, reconciliação feita. 64 h de parede
desde 13/08, das quais ~39 h de trabalho efetivo.

**F1 FECHADA em 17/08/2026 — as cinco portas passam.** Ler
`docs/fechamento-f1.md`. recall@1 **0,678** contra 0,467 do baseline, MRR
**0,785** contra 0,592, armadilhas **5 de 6**, multi-hop com ≥1 fonte **5 de 5**,
e uma única queda do 1º lugar (não-crítica; o teto era 3).

Duas coisas que valem para as fases seguintes. A porta 3 fechou com **metadado**
(famílias de versão), não com peso de fusão — o gargalo que a inversão F2/F3
identificou era precisão, e parte dela não estava no conteúdo. E o fechamento
**não depende do reranking**: com ele desligado as portas 1 a 4 também passam, o
que importa porque ele custa 6,8× no tempo de consulta.

**F3.5 bloco D em curso desde 16/08/2026** — controle de indexação. Método e
coeficientes em `docs/estimativa-de-indexacao.md`.

Feito: `index/estimativa.py` (trabalho em byte ponderado por formato, faixa em vez
de ponto, tempo ativo com suspensão descontada), `index/progresso.py` (JSON
atômico ao lado do índice — o indexador publica, o painel lê), `index/esforco.py`
(perfil `leve` com prioridade e E/S baixas via psutil), instrumentação dentro do
laço do indexador, `--perfil` na CLI, e a barra no painel.

**Painel completo em 17/08/2026 — 465 testes.** Estágio 0 (criar base com prévia
de custo, indexar, conectar), perfis, pesos e releitura, diagnóstico de consulta,
**ensinar o sistema quando erra**, perfil de esforço e re-apontar pastas. A prévia
usa o mesmo `iter_files` do indexador, e separa "arquivos" de "legíveis" — contar
tudo daria estimativa maior que a verdade.

**F3.5-D fechada em 19/08/2026 — retomada automática depois de reinício.**
`index/retomada.py` já existia com 13 testes; o que faltava era o controle no
painel e a verificação contra o Windows real. Botão liga/desliga em Máquina,
e nenhum marcador novo — o `progresso.json` é o marcador, porque um segundo
arquivo criaria duas fontes de verdade.

O mecanismo **não** é a tarefa agendada que o plano previa. `schtasks /SC ONLOGON`
e o `Register-ScheduledTask` do PowerShell dão "acesso negado" sem elevação nesta
máquina; criar tarefa `ONCE` no mesmo shell funciona, o que localiza o
impedimento no **gatilho de logon** e não no agendador. O gatilho passou a ser um
`.cmd` na pasta de inicialização do usuário — dispensa elevação e é um arquivo
visível que se apaga à mão. Verificado rodando de `C:\Windows\System32`.

Lição para a F4 e a F5: **mock de utilitário do sistema não prova permissão.** Os
13 testes com `schtasks` simulado passavam verdes contra um comando que a máquina
recusa. O que pegou foi rodar de verdade.

```bash
py -m segundocerebro.index.indexer --perfil leve   # cede a vez, recusa bateria
```

**F2 fechada em 18/08/2026 — critério de saída cumprido.** A tabela consolidada
está em `docs/ablacao-f2.md` (leitura) e `docs/ablacao-f2-tabela.md` (evidência
regenerável). Sem reranking, a configuração entregue mede recall@1 **0,667**, MRR
**0,787** e nDCG@5 **0,793**; com reranking ligado, recall@1 **0,678**. As
entregas medidas, na ordem em que entraram:

- **Famílias de versão** (`docs/ablacao-familias.md`): 0,600 → 0,644, armadilhas
  4 → **5 de 6**, zero regressões. **A porta 3 passa.** Custo zero por consulta.
- **Reranking com peso 0,25** (`docs/ablacao-rerank.md`): 0,644 → **0,678**. O
  cross-encoder entra como **quarto ranqueador, não como juiz** — a grade é
  monotônica e *substituir* a ordenação é o pior resultado de todos (0,489).
  **Desligado por padrão**: a consulta vai de 0,92 s a 6,28 s, 6,8× por 3,4
  pontos. `rerank = 0.25` na base liga. Numa GPU (F3.6) o padrão inverte.
- **Expansão de contexto**: `search` anexa vizinhos em `antes`/`depois`, fora de
  `texto` para não contaminar procedência. Entra por argumento — o conjunto
  dourado não mede "a resposta estava no parágrafo seguinte".
- **Glossário de siglas** (`docs/ablacao-glossario.md`): 0,644 → **0,667** de
  recall@1, nDCG@5 0,760 → **0,793**, zero regressões, **custo zero por consulta**.
  Nessa métrica vale mais que o reranking, que custa 6,9× no tempo.

  O achado que decide o produto: o dicionário de teste foi medido dividido, e o
  grupo **genérico** (mês abreviado, serviria a qualquer acervo) deu **zero**
  enquanto o **específico da empresa** deu o ganho inteiro. Logo dicionário
  embutido é peso morto, e o mecanismo de o usuário construir o dele **é** a
  feature — endpoint `/api/glossario` e tela no painel, arquivo por base.
- **Tabela consolidada da F2** (`docs/ablacao-f2.md`, gerada por
  `eval.ablacao_f2`): nove braços numa passada. O harness passou a emitir
  nDCG@**5** e @10 — o @5 porque a saída da fase pede, o @10 para não perder
  comparabilidade com F0 e F1.

**A lição que se repetiu três vezes:** neste acervo o consenso de ranqueadores
independentes vale mais que qualquer juiz isolado. Aconteceu com o bm25 (13/08),
com o cross-encoder (16/08) e na tabela consolidada de 18/08 — nenhum ranqueador
isolado chega perto da fusão. Desconfiar de mecanismo que proponha reordenar
sozinho.

E a lição inversa, que a tabela deu de graça: o pior par de dois sinais é
`bm25 + nome` (nDCG@5 0,647), e é o par que lê **forma de superfície**. O que soma
é sinal de natureza diferente, não sinal a mais.

**Onde o bm25 se paga, e é só ali.** `denso + nome + famílias` tem o maior nDCG@5
da tabela (0,789), acima do reranking, a um oitavo do custo — e faz **3 de 6
armadilhas** contra 5 do padrão. Isso também mata a explicação de que as famílias
teriam tornado o bm25 redundante: sem ele, com famílias ligadas, as armadilhas
caem para 3. Os dois resolvem casos diferentes. O padrão não muda porque a regra
foi declarada antes; fica registrado como candidato se a porta 3 for renegociada.

**Metadado antes de modelo, confirmado duas vezes.** Famílias de versão e
glossário custam zero por consulta e valem +0,044 e +0,033; o reranking custa
6,9× e vale +0,011 de nDCG@5. Dois dos três maiores ganhos da fase não vieram de
modelo nenhum.

Armadilha do catálogo, repetida: o `bge-reranker-v2-m3` que o ROADMAP nomeava
**não existe no `fastembed`**, igual ao BGE-M3 denso. Conferir catálogo antes de
escrever o nome de um modelo no plano.

**Painel com tela** desde 16/08 — `painel/index.html`, servido pelo próprio
Starlette, sem npm e sem nada vindo de fora. Perfis com o custo de cada um à
mostra, diagnóstico de consulta e conjunto dourado crescendo do uso real.

**Segundo cliente instalado por um comando, desde 18/08/2026.**

```bash
py -m segundocerebro.mcp.registrar --cliente claude-desktop --instalar
```

Resolve `%APPDATA%\Claude\claude_desktop_config.json`, mescla preservando os outros
servidores MCP e as preferências do app, e **recusa gravar** se o cliente não
estiver na máquina — criar a pasta deixaria configuração órfã sem ninguém avisar.
O teste `test_bloco_do_claude_desktop_sobe_de_um_cwd_neutro` (marcado `modelo`)
sobe o servidor **de `C:\Windows\system32`** com o bloco exato e responde a
consulta do traço da F3 contra o índice real. Da F3 falta só o ato humano: abrir o
Claude Desktop e fazer a pergunta lá.

**F3 fechada em 20/08/2026.** Mesma pergunta multi-hop nos dois clientes, com
decomposições de busca **diferentes** e nenhum fato sem fonte no acervo —
evidência mais forte de R1 que a mesma decomposição repetida seria. Traço em
`docs/traco-f3-uso-real.md` (gitignorado).

**F4 — grafo derivado e `neighbors` entregues em 20/08/2026.** Ler
`docs/ablacao-f4-grafo.md`. Métricas da F2 **idênticas** (recall@1 0,667, MRR
0,787, nDCG@5 0,793) e o caso plano → norma respondível só pela aresta. Falta da
F4: SharePoint, watcher, MSG/EML e legado DOC/XLS.

```bash
py -m segundocerebro.retrieve.grafo --base padrao            # constrói, ~30 s
py -m segundocerebro.retrieve.grafo --base padrao --estado   # só relata
py -m eval.rodar --retriever hibrido --com-grafo --out docs/metricas-f4-com-grafo.md
```

**O ganho medido é de uma pergunta só, e é a certa.** `g048` (multi-hop) vai de
recall@10 **0,50 → 1,00**: exigia todas as fontes e ficava travada porque a
segunda era inalcançável por qualquer busca. Custo: duas perguntas descem de 5→8 e
8→10, −0,018 de recall@5. O salto **não é padrão** — a troca é do cliente.

Quatro coisas da F4 que valem para as fases seguintes:

- **Passada separada do indexador vale mais que a economia óbvia.** Reconstruir o
  grafo custa 30 s contra 39 h de reindexação — e foram necessárias **cinco**
  iterações de regra de extração. Um artefato derivado do índice, e não do disco,
  é iterável; um que exige reindexar, não é.
- **Cinco defeitos, todos a mesma classe, nenhum pego por teste unitário.** Todos
  eram "o mesmo identificador escrito de outra forma não liga" — `ISO 42001:2023`
  contra `ISO 42001`, `ISO 14.001` truncado em `ISO 14`, LGPD partida em duas.
  É o defeito mais insidioso possível aqui, porque cada grafia produz sua própria
  aresta plausível e nada parece errado. **Só olhar a distribuição real acha.**
- **Um limite escolhido no abstrato cortou o caso motivador da fase.** O teto de
  25 documentos por identificador tinha raciocínio plausível e excluía a `ISO
  42001` (27 docs), que é a aresta que a fase existia para construir. A
  distribuição medida é o que desfaz esse tipo de erro.
- **Nome de arquivo é fonte de identificador, não só o texto.** O documento que a
  pergunta multi-hop precisa é PDF digitalizado com zero texto extraível. Daí o
  desempate que decide a ordem: identificador no nome significa que o documento
  **é** o assunto; no corpo, que ele **fala sobre** — e entra como desempate, nunca
  como prioridade sobre a raridade.

**Próximo passo:** o que resta da F4 (SharePoint, watcher, MSG/EML) e a decisão
sobre a porta 3 — ver "onde o bm25 se paga". O multi-hop completo segue em 1 de 5,
e agora há a primitiva para atacá-lo: o cliente compõe `search` → `neighbors`.

O que o corpus real ensinou e que não estava no plano — tratar na F1:
famílias de versão (`_v6` não é o vigente), caminhos acima de 260 caracteres
(34 arquivos), arquivos travados pelo Word durante a indexação, e duplicatas
byte a byte entre pastas e entre formatos (.docx + .pdf do mesmo documento).

## O corpus real — não é um vault Obsidian

Isso já foi motivo de mal-entendido; não reintroduzir a premissa errada.

- **Pessoal**: pastas soltas em disco (Windows)
- **Corporativo**: SharePoint via **pasta sincronizada** do cliente OneDrive.
  Graph API (`Sites.Selected` + consentimento de admin) fica para a F5
- **Formatos dominantes**: PDF, DOCX, XLSX, PPTX. Markdown é opcional
- **Não há Obsidian instalado e não há wikilinks.** O Obsidian é gratuito e
  dispensa conta, mas foi deliberadamente **não** adotado — não acrescenta nada
  sobre uma pilha de arquivos Office. Se entrar depois, wikilink é sinal
  *adicional*, nunca o principal
- Por isso o grafo que alimenta `neighbors` e o multi-hop é **derivado**:
  identificadores (contrato, projeto, processo, siglas), entidades, taxonomia de
  pastas, datas

## Por que MCP e não um app

O usuário prefere custo fixo de assento já pago a cobrança variável por token —
mesmo quando a API sairia mais barata (a API ficaria em ~US$5–10/mês contra
US$100–200 de um assento Max). A motivação é previsibilidade, não economia.

Daí a arquitetura: o modelo vem do cliente MCP (Claude Code, Antigravity, Grok,
Claude Desktop); o servidor só recupera. Embeddings e reranking locais. Custo
marginal por consulta: zero.

Restrições que isso impõe e que **não** têm contorno:
- Assinatura Pro/Max está sob Termos de Consumidor, premissa de uso individual —
  não cobre implantação multiusuário
- O Agent SDK **exige API key**; OAuth de Pro/Max é bloqueado. Automação não
  interativa precisa de key própria
- Anthropic não tem API de embeddings. Nenhuma assinatura cobriria a recuperação
  — daí embeddings locais serem a única rota de custo zero

## Invariantes — não violar sem atualizar ARCHITECTURE.md

1. **Nenhuma chamada a API paga no caminho de consulta.** Embeddings e reranking
   são locais. Geração é do cliente. Uma etapa por-consulta que chame API quebra
   a razão de existir do projeto.
2. **Sem ferramenta que gere texto.** Nada de `answer`, `summarize`, `explain`
   na superfície MCP. Isso reintroduziria custo e amarraria o sistema a um
   fornecedor.
3. **Multi-hop é do cliente.** Não construir orquestrador de retrieval. Oferecer
   primitivas componíveis e deixar o loop de agente compor.
4. **Toda mudança em chunking, embedding ou ranking passa pelo eval.** Se a
   métrica não melhorou, a mudança não entra.
5. **Todo retorno de ferramenta carrega procedência** (arquivo + seção) e ID
   estável.
6. **O painel de ajuste está fora do caminho de consulta.** Ele lê e grava
   configuração; não recupera, não ranqueia, não gera texto e não é requisito de
   execução. O servidor MCP funciona com o painel desinstalado — e existe teste
   que prova isso.
7. **Isolamento entre bases é físico, não filtro.** Cada base tem seu diretório
   de índice e seu processo de servidor. Nunca implementar base como filtro de
   metadado numa consulta compartilhada: um booleano pode estar errado, dois
   diretórios não vazam um no outro. O campo `raiz` do registro é procedência,
   **não** fronteira de isolamento.

## Stack

Python 3.12 · `mcp` · BGE-M3 (`fastembed`) · `bge-reranker-v2-m3` · `lancedb` ·
`sqlite3` · `pymupdf4llm` · `watchdog` · `pytest`

## Como rodar

```bash
pip install -r requirements.txt
py -m pytest tests/ -v        # testes
py -m pytest eval/ -v         # métricas de recuperação
```

## Convenções

- Código e comentários: **inglês**
- Documentação interna e strings de usuário: **português**
- Logging via `logger.get_logger("modulo")` — nunca `print()`
- Testes isolados: `tmp_path` e `monkeypatch`; nunca tocar o índice ou as pastas
  de origem reais
- **Nunca abrir conteúdo de arquivo sem checar antes os atributos de nuvem**
  (`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`, `FILE_ATTRIBUTE_OFFLINE`) — ler um
  placeholder do SharePoint dispara download
- **Caminhos longos**: prefixar `\\?\` (ou `\\?\UNC\`) ao abrir arquivo no
  Windows. O corpus real tem 34 arquivos acima de 260 caracteres — o limite
  clássico — e o mais longo chega a 293. Sem o prefixo, a API do Windows falha
  como "arquivo não encontrado", que é o pior modo de falha possível: silencioso
  e enganoso. `os.scandir` enumera sem problema, o erro só aparece na abertura

## Avaliação

`eval/golden/` contém pares pergunta → fonte(s) esperada(s). Métricas:
recall@k, MRR, nDCG. Resultados de ablação vão em `docs/`.

Regra: **nenhuma otimização de precisão sem número antes e depois.**

## Contexto do usuário

Ambiente Windows 11, PowerShell. Projeto irmão em `C:\Pytondev\TotalAudioRelator`
(app desktop de gravação de reuniões) — de onde vêm os padrões de LGPD,
`audit_trail.py` e `encryption.py` para reaproveitar na fase F5.
