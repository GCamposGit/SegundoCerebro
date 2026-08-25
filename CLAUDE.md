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
0,787, nDCG@5 0,793) e o caso plano → norma respondível só pela aresta.

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

**F4 — MSG/EML entregue em 21/08/2026.** Ler `docs/ablacao-f4-email.md`. 48 `.msg`
e um `.pdf` com conteúdo MIME saíram de `sem_parser`; `sem_parser` no registro caiu
de 83 para 35 e o índice foi para **1.608 documentos, 93.073 chunks**. As três
perguntas anotadas `fora_de_escopo: email` (`g001`, `g011`, `g033`) voltaram para a
média e medem **1,000 em recall@3** — eram zero por construção.

```bash
py -m segundocerebro.index.indexer --base padrao --pular-planilha-acima-de 40 --prefixo 02
py -m eval.rodar --retriever hibrido --sem-rerank --glossario eval/glossario-teste.toml --out docs/metricas-f4-email-depois-48.md
```

Cinco coisas desta entrega que valem para as fases seguintes:

- **Documento sem chunk é invisível até para o ranqueador de nome.** Contraria a
  intuição: "o número do contrato está no nome do arquivo, então o baseline acha"
  é **falso** — `paths_com_chunks()` é a fronteira, e ela é de conteúdo. Formato
  novo não é "mais um formato": é um conjunto de documentos saindo do zero absoluto.
- **O defeito não estava no parser nem no chunker, e sim na interação.** O chunker
  respeita orçamento de **token**; uma URL de rastreio de 400 caracteres opacos
  consome a janela de 512 tokens inteira. Cinco emails de reembolso davam **2.931
  chunks de 82 caracteres**; depois de trocar endereço por host, **25**. A
  indexação passou de 25 min travados para 55 s. Medir chunk com o tokenizador
  **real** é o que acha isso — sem ele o teste unitário dizia 19 onde havia 1.850.
- **A regressão é de uma pergunta, e a inspeção diz de quem.** `g045` perde o 1º
  lugar para um `.msg` da reunião diária da POC que ela cita. A outra queda
  (`g037`, ≤5º → 11º) é de **transcrição de reunião**, não de email. Sem olhar
  pergunta por pergunta as duas teriam sido creditadas ao email.
- **Parser novo não repesca documento já indexado.** `STATUS_PARA_REPESCAR` cobre
  "não havia parser", não "o parser mudou": um `.msg` ficou no índice com 343
  chunks de lixo, e nada o repesca. Falta coluna de versão de parser no registro.
- **O corpus é 63% maior do que o índice.** `iter_files` enumera 2.617 documentos,
  o registro tinha 1.601: **1.013 nunca indexados**, 1.010 deles em `Meetings/`.
  Toda métrica de F1 e F2 mediu um corpus 39% menor que o disco. Nenhuma conclusão
  muda (cada uma declara seu corpus), mas é o próximo número a decidir.

**F4 — fatia cross-lingual (C4.5) entregue em 24/08/2026.** Ler
`docs/fatia-cross-lingual.md`. O harness recorta toda medição em `mesma-língua`
contra `cross-lingual`, e o recorte acusou o que a média escondia: recall@1
**0.625** mesma-língua contra **0.333** cross-lingual, razão em recall@5 **0.73**
contra o 0.80 do critério. O acervo é 15% inglês (284 de 1.900 documentos com
conteúdo) e um quinto do dourado cruza idioma.

```bash
py -m eval.idioma --base padrao --escrever   # anota idioma/idioma_fonte no dourado
```

Três coisas desta entrega que valem para as fases seguintes:

- **recall@20 é 1.000 na fatia cross-lingual.** O documento certo é alcançado e
  **mal ordenado** — sintoma de ranqueador cego dentro da fusão, não de busca que
  não encontra. Dois dos três votos (bm25 e nome) são cegos a idioma por
  construção: FTS5 não casa `contrato` com `agreement`. É a pergunta que `F4-P`
  herda.
- **Anotação estática, não derivada do índice — porque o baseline por nome não
  abre índice.** Calcular a fatia no relatório a faria sumir do lado F0 de toda
  comparação entre fases, que é a razão de o harness existir. O preço (anotação
  envelhece) se paga com `conferir()`, que confronta anotação e índice a cada
  `eval.rodar`.
- **Os dois defeitos do detector eram de normalização, não de vocabulário.** `as`
  faltava na lista inglesa, e `só` perde o acento e vira a palavra inglesa `so`.
  Os dois faziam o texto pontuar para o idioma errado **proporcionalmente ao
  tamanho**. Nenhum apareceu na leitura; os dois apareceram no teste.

**F4 — porta de latência (R9.3) entregue em 24/08/2026.** Ler
`docs/porta-de-latencia.md`. Instrumento em `eval/latencia.py`, portas em
`eval/portas-latencia.toml`. **Todo o orçamento de latência é `search`**: p95
entre **1.840 e 2.877 ms** conforme o estado térmico, contra 0,9–2,8 ms de
`read_note` e 1,6–2,1 ms de `neighbors`, que passam o alvo de produto por mais de
uma ordem de grandeza.

```bash
py -m eval.latencia --base padrao --maquina notebook-15w --rodadas 3 --porta
```

Quatro coisas desta entrega que valem para as fases seguintes:

- **Duas portas, não uma.** Porta que a máquina reprova no dia em que é escrita
  não guarda nada — fica vermelha para sempre e ninguém repara quando piora. O
  alvo de produto (300 ms) fica como dívida declarada de `R4.1`/`R3.3`; o piso de
  regressão é **por máquina nomeada**, e `--porta` recusa rodar sem `--maquina`.
- **Número sem máquina é mentira, e sem estado térmico também.** Cinco passadas
  do mesmo código no mesmo índice deram p95 de 1.840 a 2.877 ms — **1,6×** —
  conforme o notebook estivesse descansado ou saturado. Isso reconcilia a linha
  de base de 1.145 ms que o ROADMAP registrava: ela não estava errada, estava sem
  protocolo. O piso desta máquina fica de propósito na ponta quente, porque gate
  que pisca vermelho por causa do ventilador é desligado em uma semana.
- **Um braço por passada.** Medir `search` e `search+rerank` no mesmo laço dava
  4.394 ms contra 2.713 ms isolado — o cross-encoder satura o pacote térmico e o
  braço barato paga a conta do caro. **O número contaminado é plausível**, então
  passaria. Mesma família do defeito anterior: a primeira versão media
  `recursos.busca`, que herda o reranker da base, e chamava aquilo de "sem rerank".
- **`R6.2` tem meta impossível, com número.** Reranquear custa **~761 ms por par**
  neste CPU; os "30 candidatos em <500 ms" do pacote são ~22,8 s, **46× a meta**.
  Não é ajuste, é a classe do modelo — `R6.2` escolhe entre GPU (F3.6) ou outro
  reranqueador.

**F4 — `C3.a` fechado em 24/08/2026, e os dois critérios discordam.** Ler
`docs/ablacao-c3a-pesos-fts.md`. `Store.buscar_lexical` aceita pesos de coluna do
`bm25()`, `[base.pesos]` ganhou `fts_texto`/`fts_trilha`/`fts_caminho`, e
`eval/fonte.py` recorta todo relatório por **tipo de fonte** (reunião, email,
escritório, misto), derivado do caminho da fonte.

```bash
py -m eval.varredura_fts --base padrao --glossario eval/glossario-teste.toml --out docs/metricas-c3a-pesos-fts.md
```

**Nada mudou de configuração.** Pela regra declarada nenhum dos 18 braços passa. O
nome do arquivo pontua duas vezes — na coluna `caminho` do FTS5 e no
`RanqueadorDeNome` da fusão — mas **as duas contagens não são intercambiáveis**: o
grupo de reunião é **14× mais sensível** ao peso da fusão (amplitude 0,172) que à
coluna do bm25 (0,005 a 0,012). Em MRR e recall@1 a coluna se paga; zerá-la custa
até 0,062 de MRR e 6,8 pontos de recall@1.

Cinco coisas desta entrega que valem para as fases seguintes:

- **O ranqueador de nome é ponte entre idiomas.** MRR cross-lingual cai
  monotonicamente com o peso do nome: 0,496 → 0,475 → 0,461. Identificador, código,
  data e nome próprio no nome do arquivo casam igual em PT e EN; o bm25 não casa
  `contrato` com `agreement`. Isso **retira** a recomendação de `nome = 0,25`, que
  sobe agregado (+0,004), nDCG@5 (+0,013) e reunião (+0,122) e derruba a ponte em
  0,021 — a média esconde, a fatia mostra.
- **Quando a régua cresce, o ótimo anterior tem de ser rederivado, não herdado** —
  mas rederivar pode reconfirmar. O 0,5 saiu da varredura de 13/08, num dourado
  **sem nenhuma pergunta de reunião** (entraram com a F4-M), e a rederivação deu 0,5
  outra vez, agora por dois motivos: escritório **e** ponte PT↔EN.
- **`caminho` troca recall@1 por recall@5, e isso não estava na hipótese.** Com
  `nome` 0,5: `caminho` 0,3 dá o **maior recall@5 da grade** (0,847 contra 0,797),
  `recall@10` **idêntico** nos três, recall@1 0,517 contra 0,551. Não se ganha
  documento, reordena-se dentro do top-10. E `fts_caminho = 0,3` leva a razão do
  `C4.5` de 0,73 a **0,79** com as duas fatias subindo, custo zero por consulta —
  onde as rotas previstas eram `R3.1` (rebuild) e `R6.2` (6,9× de latência). É uma
  pergunta de doze: pista, a confirmar no perfil bilíngue de `R9.1`.
- **Critério de razão é satisfazível piorando o denominador.** Dois braços com
  recall@5 cross-lingual idêntico (0,708): o de mesma-língua **pior** (0,875) marca
  0,81 e passa; o melhor nas duas (0,898) marca 0,79 e reprova. O critério do `C4.5`
  precisa de piso absoluto ao lado da razão.
- **Memo na fronteira do `Store`, não fusão paralela.** 18 braços em 4 minutos, 81%
  das buscas ao índice evitadas, `BuscaHibrida` rodando inteira as 18 vezes.
  Reimplementar a fusão offline seria mais rápido e seria o defeito de
  `docs/porta-de-latencia.md` outra vez. `eval/test_memo.py` prova a equivalência.

Sobre o instrumento: **recorte derivável não se anota.** `idioma_fonte` precisa do
índice e por isso é anotação estática; grupo de fonte sai do caminho que o dourado
já carrega. A regra derivada errou na primeira versão por **prefixo de ordenação de
pasta** (`09. `, `10 - `, `260722_`): 14 dos 36 segmentos do dourado têm um, e ela
media 10 reuniões onde já se sabia que eram 11 — número menor e plausível, então
passaria. Mesma classe dos cinco defeitos do grafo.

**F4 — o eval passou a medir o caminho que o cliente recebe, em 24/08/2026.** Ler
`docs/ablacao-caminho-entregue.md`. `eval/entregue.py` + `--entregue` no
`eval.rodar`, **aditivo**: `search` continua sendo a série histórica F0→F4.

```bash
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank --entregue --glossario eval/glossario-teste.toml --out docs/metricas-caminho-entregue.md
```

**São dois recuperadores, e o harness media o que o cliente não executa.** A
ferramenta `search` do MCP chama `buscar_chunks` (`mcp/server.py:191`), onde o
`RanqueadorDeNome` **não participa** — ele pontua documentos e não há posição de
trecho honesta para dar a ele. Verificado no índice real antes de qualquer código:
mudar `peso_nome` de 0,5 para 0 **não altera nada** em `buscar_chunks` e altera a
ordem em `search` em todas as consultas. O peso do nome é **inerte em produção**.
`painel/medir.py:79` herda a mesma cegueira.

No agregado os dois medem parecido — recall@1 idêntico (0,551), o entregue ganha
nDCG@5 (0,693 contra 0,682) e perde recall@10 (0,881 contra 0,907). **É o recorte
que mostra**, e ele corrige duas coisas:

- **O caminho entregue é 3× melhor em reunião** (recall@1 0,273 contra 0,091, MRR
  0,452 contra 0,287): ele é, na prática, a configuração "sem ranqueador de nome"
  que `docs/dourado-cobertura.md` mediu.
- **E paga com a ponte PT↔EN.** O achado de manchete de
  `docs/fatia-cross-lingual.md` — *"recall@20 é 1.000 na fatia cross-lingual, o
  documento é alcançado e mal ordenado"* — **vale só em `search`**. No caminho
  entregue é **0,750**: três das doze não são alcançadas no top-20. Para um quarto
  da fatia, no produto, é busca que não encontra.

Duas lições que valem além do pacote:

- **Verificar qual caminho de código o produto executa vem antes de afinar peso
  nele.** Isto foi achado ao começar o `F4-P`, com três consultas, antes de
  escrever uma linha — e o `F4-P` teria afinado um botão que o cliente não lê,
  contra um teto de oráculo (+0,032) calculado sobre o caminho errado.
- **O princípio já estava escrito e não tinha sido aplicado.** `ablacao-familias.md`
  diz "ligado em `search` **e** em `buscar_chunks`, para o que se mede ser o que se
  entrega". Vale conferir isso para todo sinal, não só para o próximo.

**A arquitetura de avaliação resiliente entrou no plano em 24/08/2026 — pacotes
E1–E6 e Q1–Q10.** Ler [`docs/relatorio-avaliacao-resiliente.md`](docs/relatorio-avaliacao-resiliente.md),
[`docs/guia-engenharia-5-estrelas.md`](docs/guia-engenharia-5-estrelas.md) e, antes
de tocar no gerador, o laudo [`docs/avaliacao-pacote-e1.md`](docs/avaliacao-pacote-e1.md).

Três camadas: dourado real **congelado** como regressão (nunca decide arquitetura
sozinho, e a série F1→F2 fica intacta), sintético gerado por código como camada de
**decisão**, benchmark externo como **alarme**. `R9.1`+`C5.b` foram absorvidos pelo
`E1`, e o gerador **passou a ser do notebook**.

**O código do `E1` foi executado antes de entrar no plano, e reprovou como veio.**
Oito achados, três que decidem a ordem:

- **`--n-por-fatia 30`, o comando do próprio README, não termina.** O espaço de
  siglas tem **26** elementos e não 26³ — 7, 11 e 17 são coprimos de 26, então
  `b mod 26` é bijeção sobre a tripla. Em `i = 26` o `while True` não sai. **A
  suíte que veio passa** porque todo teste usa `n ≤ 11`. É a lição do `schtasks`
  da F3.5-D com outro nome: teste verde contra um caminho que a máquina não
  executa. E o `n ≥ 30` que o `E5` exige para significância é inalcançável.
- **A fatia cross-lingual sai de tamanho zero** — `{'não declarado': 260}` —
  porque `idioma_fonte` nunca é emitido, e `idioma: "pt->en"` nem código de idioma
  é. É palavra por palavra o que `eval/golden/README.md` avisou no mesmo dia que
  aconteceria. Contrato escrito num dia e violado no outro só é pego executando.
- **Zero perguntas de reunião e de email:** `{'escritório': 234, 'misto': 26}`.
  Sem `.msg`, `.eml`, `.vtt` nem pasta de transcrição.

**Esse último achado é o que reordena o trabalho, e contra a intuição.** O
relatório manda instrumento antes de conclusão, e lido ingenuamente isso poria o
`E1` na frente da `F4-P`. Mas o alvo declarado da `F4-P` é o grupo `reunião`, e o
sintético não mede reunião nem cross-lingual: rodá-lo antes **não protegeria a
`F4-P` de nada**. O que protege uma decisão sobre n=11 é o intervalo de confiança
sobre o dourado corporativo, que já é o piso declarado — e ele é o `E5`, o item
mais barato da lista inteira (~30 linhas, numpy já está lá).

**Ordem adotada: `E5` → `F4-P` → `E1` endurecido.**

**`E5` fechado em 24/08/2026 — e ele achou que a porta 5 não rodava.** Ler
`docs/rigor-estatistico.md`. `eval/estatistica.py` traz bootstrap **pareado** de
percentil com semente fixa; `eval.rodar` ganhou a tabela de ruído por recorte e
`eval.comparar` a de **Δ ± IC95 com veredito**. A regra de adoção passou a ser
escrita: ganha quem **exclui zero** na fatia declarada antes de olhar a tabela;
empate resolve por simplicidade, que é não adotar.

```bash
py -m eval.comparar --base padrao --antes hibrido --depois hibrido --rerank-depois --glossario eval/glossario-teste.toml --out docs/metricas-e5-rerank-reanalise.md
```

Três coisas desta entrega que valem para as fases seguintes:

- **A ferramenta da porta 5 estava inexecutável desde 15/08.** `eval.comparar`
  levantava `AttributeError` fora do baseline: o arremedo de `Args` que ela monta
  para reusar `rodar._montar` não acompanhou quatro campos (`base_cfg`,
  `glossario`, `rerank`, `sem_rerank`). **Nenhum teste pegou** porque todos montam
  `Resultado` à mão e nunca passam por `_montar` — mesma família do `F4-P.0`:
  teste bom, cego ao caminho de montagem. O conserto que importa não é completar
  a lista, é `_CAMPOS_DE_MONTAGEM` conferido em teste contra o código-fonte de
  `rodar._montar`, para a próxima fase quebrar o teste em vez da porta.
- **Pareado não é detalhe de método, é potência de graça.** Os dois braços
  respondem as mesmas perguntas, e como a média é linear,
  `media(depois[idx]) − media(antes[idx]) == media((depois − antes)[idx])` — então
  reamostrar o vetor de diferenças **é** o teste pareado, e ninguém consegue
  dessincronizar dois vetores depois. Daí a armadilha de leitura que o relatório
  avisa: **dois intervalos de braço isolado que se sobrepõem não provam empate.**
- **`--peso-denso`/`--peso-nome` ausentes viravam constante de módulo**, não o que
  a base configura. Com os `fts_*` que o `C3.a` acrescentou, a porta 5 mediria
  pesos de fábrica contra uma base que configura outros — o defeito que
  `rodar._montar:88` já documenta com outro nome.

**A re-análise do reranking da F2 deu empate, e isso fortalece a decisão que já
existia.** Δ MRR **+0,012 [−0,031; +0,055]** e Δ nDCG@5 **+0,022 [−0,010; +0,054]**
em n=59 — o ganho está reproduzido em tamanho e cruza zero nas três métricas. O
reranking já estava desligado por custo (6,8× por 3,4 pontos); com o intervalo à
mão a conversa sobre custo nem precisaria ter acontecido. Dois achados de
mecanismo: **Δ recall@1 é +0,000 em todos os recortes** — com peso 0,25 o
cross-encoder reordena a cauda e quase nunca desloca o 1º lugar — e a única fatia
que acende é a cross-lingual, em **uma métrica de três**, sem ter sido declarada
antes. Fica como pista para `C4.2`, não como resultado: com oito recortes, a chance
de um acender por acaso sob H0 é ~34%.

**O que o n=11 detecta depende da forma do efeito, não só do tamanho** — e isto
muda o critério de saída da `F4-P`. Simulado sobre as 11 perguntas de reunião: um Δ
de **+0,273 concentrado** em três perguntas dá **empate**; um de **+0,150
espalhado** pelas onze **ganha**. O concentrado é 1,8× maior e reprova. Logo o alvo
de +0,165 da `F4-P`, se vier de duas perguntas indo ao 1º lugar (+0,182), é empate
— a fase precisa de melhora **ampla** na fatia, e o critério passa a olhar
*quantas* perguntas se moveram, não só o valor. Isso é o instrumento funcionando:
mudança que conserta duas perguntas é ajuste àquelas duas.

As sete condições de entrada
do `E1` estão no ROADMAP, e a que bloqueia merge é a sexta: a suíte que veio no zip
carrega dez nomes de cliente por extenso num arquivo versionado, que é exatamente o
anti-padrão que `tests/test_saneamento.py` existe para impedir — e a docstring dele
já dizia que o teste com a lista embutida "seria o próprio vazamento".

**Próximo passo:** `F4-P`, **reescopado pelo achado acima**. Deixou de ser afinação
de peso e passou a ser a **reconciliação dos dois caminhos**: trazer o sinal de
nome para `buscar_chunks` sem deixá-lo votar em documento de reunião. Alvo
declarado — reunião ≥ **0,452** de MRR (o que o entregue já faz de graça) e
cross-lingual voltando para recall@20 = **1,000** (o que só `search` faz hoje), sem
perder o recall@1 de 0,551. O teto de oráculo de +0,032 **não vale**: foi calculado
sobre `search`. **Antes dela vem o `E5`**, e o motivo está acima. Depois `E1`, `C6` e `R6.1`.
Segue em
aberto: `Meetings/` já indexado mas o resto da F4 (SharePoint, watcher, legado
DOC/XLS) não, e a porta 3 — ver "onde o bm25 se paga". O multi-hop completo segue
em 1 de 5, e há a primitiva para atacá-lo: o cliente compõe `search` →
`neighbors`.

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
