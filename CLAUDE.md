# CLAUDE.md — Segundo Cérebro RAG

Guia de desenvolvimento para o Claude Code neste projeto.

## A regra de ouro — ler antes de escolher o que fazer

**O produto é para um leigo apontando uma pasta que nunca vimos.** Não é para o
nosso acervo, não é para o corpus da VCE, não é para o revisor sênior. A régua, as
três perguntas que todo pacote responde antes de começar e as regras 10, 11 e 12
estão em [`docs/regra-de-ouro.md`](docs/regra-de-ouro.md) — **precedência sobre
qualquer prioridade herdada de dossiê, guia ou fila**.

Em uma linha cada:

- **Ganho de um acervo só não vira `[padrao]`** — vira `[[base]]`, prior do
  autotune, ou espera o segundo acervo. Exceção: custo zero por consulta e
  independente de acervo (foi o caso de famílias e glossário).
- **Hipótese sem efeito mínimo declarado não gera varredura** — e empate encerra
  o pacote, não pede mais medição.
- **Defeito se generaliza, não se remenda** — a entrega é o método que pega a
  classe inteira na próxima vez, não o caso consertado.

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

**F0–F3.6 fechadas. F4 em curso. A `F6` — primeiro uso em máquina desconhecida —
fechou em 30/08/2026**, com a `F6-B` (estágio 0 do painel, provado ponta a ponta)
e a `F6-C` (hardware; estava implementada e não declarada). Os números vivos ficam na §6 de
[`docs/colaboracao.md`](docs/colaboracao.md); os pacotes, no
[`ROADMAP.md`](ROADMAP.md).

A crônica de F0 a F4 — trinta blocos de ablação, com número, data e corpus
declarado — está inteira em
[`docs/historico-decisoes.md`](docs/historico-decisoes.md). Ela saiu daqui em
25/08/2026 porque era 79% deste arquivo e porque quem abre a sessão lendo a
crônica continua a crônica. Consultar quando a pergunta for sobre aquele número;
não como aquecimento.

Onde o sistema está, em cinco linhas:

- **Índice corporativo**: corpus e registro reconciliados desde 24/08/2026 —
  2.156 documentos dos dois lados, 463 excluídos **por papel** (`F4-M`), exclusão
  declarada e medida, não silenciosa.
- **Recuperação**: fusão de quatro sinais (denso `e5-large`, bm25/FTS5, nome de
  arquivo, famílias de versão), glossário por base, reranking **desligado** por
  custo, grafo derivado servindo `neighbors`. Desde 25/08/2026 os quatro sinais
  existem **nos dois caminhos** — a `F4-P` levou o nome para `buscar_chunks`, que
  é o que o cliente executa.
- **Linha de base do acervo corporativo** (n=59, sem rerank, glossário de teste):
  recall@1 **0,551**, MRR **0,680** em `search`, que segue sendo a série histórica.
  O caminho entregue está em **0,551 / 0,696** desde a `F4-P`. Com intervalo:
  [`docs/rigor-estatistico.md`](docs/rigor-estatistico.md). É **piso de
  regressão**, não autoridade de arquitetura.
- **Superfície MCP**: cinco ferramentas em dois modos. `search`, `read_note` e
  `neighbors` respondem **pergunta**; `list_folder` e `outline` — do `J.c-mapa`,
  30/08/2026 — servem **leitura**: enumerar uma pasta e mapear um documento para
  o agente que vai ler tudo. Toda tool de leitura devolve cursor explícito. Dois
  clientes instalados por comando (Claude Code e Claude Desktop).
- **Painel** em `127.0.0.1`: criar base, indexar com barra, pesos, glossário,
  diagnóstico de consulta, ensinar quando erra. Fora do caminho de consulta
  (invariante 6).

**Onde o produto não está pronto**, e é o que a régua de ouro manda olhar
primeiro: o watcher, e o **parse store** (`J.a`/`J.f`), sem o qual metade do
pacote J não anda e todo rebuild paga o parse de novo. O `Q15` fechou inteiro em
31/08/2026, com o `Q15.a`. Instalar frio numa máquina que não é nossa deixou de
ser hipótese: o percurso do leigo tem teste. O Office legado
(`.doc` `.xls` `.ppt` `.rtf`) **é lido** desde a F4; o que falta ali é o `F4-L`,
o container OLE que mente sobre o próprio conteúdo.

## Próximo passo

> **A varredura de peso de nome por tipo de fonte saiu desta lista em 27/08/2026.**
> Ela tinha o efeito mínimo que lhe faltava — nDCG@5 de reunião
> **−0,089 [−0,172, −0,017]**, IC que não cruza zero — e a `F4-P.1` **fechou como
> hipótese mal especificada**, não como refutação: a alavanca zerava o peso do nome
> nos candidatos de reunião, que são as **vítimas**, e 11 de 12 dos documentos que
> causam o dano são de escritório
> ([`docs/ablacao-f4p1-nome-por-fonte.md`](docs/ablacao-f4p1-nome-por-fonte.md)).
> **Não reabre com outra grade.**

> **`J.b1` e `J.c-mapa` fecharam em 30/08/2026** e saíram desta lista. O acervo
> ganhou identidade pública (`doc_id` de conteúdo, URI `sc://`, preferência
> declarada entre os 10,5% de caminhos duplicados) e as duas tools de mapa
> (`list_folder`, `outline`), servidas do registro e sem esperar o parse store.
> A especificação recebida é
> [`docs/pacote-j-camada-acesso-corpus.md`](docs/pacote-j-camada-acesso-corpus.md);
> a conferência contra o código, com as cinco premissas que não batem com esta
> base, é [`docs/plano-pacote-j.md`](docs/plano-pacote-j.md). **Ler as duas antes
> de tocar no resto do pacote J.**

0. **`J.a` + `J.f` — o parse store e o indexador lendo dele**, que é o que
   destrava `J.b2`, `J.c-conteúdo` e `J.d`, e o que paga o rebuild das ablações
   `R2.1`/`R3.1` antes de elas rodarem. Era do desktop; o desktop está sem
   créditos desde 30/08. Três avisos medidos, todos em
   [`docs/plano-pacote-j.md`](docs/plano-pacote-j.md): `get_document` **não** sai
   dos chunks (a sobreposição infla o texto em 11,1%), a chave da entrada precisa
   da **versão do motor externo** para LibreOffice/OCR/recálculo de planilha, e o
   store nasce dentro do diretório do índice por causa do invariante 1.
1. **`F4-R.1` — o regime de máquina observável**, e é pré-requisito da passada de
   calibragem no acervo real: sem ele a `Calibracao` aprende coeficiente de dois
   regimes misturados (22× de diferença) com milhares de observações a favor.
   `esforco.py` está emprestado ao notebook por declaração na §6 de
   [`docs/colaboracao.md`](docs/colaboracao.md), porque o desktop não tem bateria
   nem CPU híbrida e não reproduz o defeito.
2. **`F4-O.3` — o dourado de OCR** (`g015`/`g025`/`g048`), que é do notebook e
   destravou quando o `F4-O.2` entrou na `main` no PR #42.
3. **`Q18`** — medido e resolvido, **esperando acordo, não execução**: ligar as
   dez regras baratas do `ruff` faz 75 dos 92 `noqa` inertes de `src` valerem,
   por 40 correções. Delas, oito arquivos são do desktop e dois são "um de cada
   vez" — é decisão de política de repositório com efeito cruzado, e a regra 8
   manda declarar, não fazer. O notebook recomenda ligar. Do `Q2` sobram
   lockfile e extras.

> **`Q15.a` e `F4-D.2` fecharam em 31/08/2026** e saíram desta lista. O `Q15.a`
> só ficou certo depois de **medir a sequência**: a primeira versão do conserto
> arrumava um caso que já funcionava, e o teste dela passava com o conserto
> desligado. O `F4-D.2` virou `eval/serie.py` + um manifesto versionado de
> impressões digitais.

A **`F6` inteira fechou** em 30/08/2026 — `F6-A` (PR #14), `F6-D` e `F6-E`
(25/08), `F6-B` e `F6-C` (30/08). O `Q5` P0 fechou junto com ela.

## Lições que valem para qualquer acervo

As únicas conclusões deste projeto que não dependem do nosso corpus. Cada uma tem
a evidência datada em [`docs/historico-decisoes.md`](docs/historico-decisoes.md).

- **Metadado antes de modelo.** Os dois maiores ganhos da F2 custam **zero** por
  consulta (famílias +0,044, glossário +0,033); o reranking custa 6,9× e vale
  +0,011 de nDCG@5.
- **Consenso de ranqueadores independentes vence juiz isolado** — três vezes, com
  três mecanismos diferentes. E o que soma é sinal de **natureza diferente**: o
  pior par é `bm25 + nome`, os dois que leem forma de superfície.
- **Conferir qual caminho de código o produto executa vem antes de afinar peso
  nele.** O peso do nome era inerte em produção e ninguém sabia.
- **Mock de utilitário do sistema não prova permissão.** Treze testes verdes
  contra um comando que a máquina recusa.
- **Só a distribuição real acha o defeito.** Cinco grafias do mesmo
  identificador, e um limite escolhido no abstrato que cortava justamente o caso
  motivador da fase.
- **Medir com o instrumento real, e um braço por passada.** Tokenizador real para
  chunk (o teste dizia 19 onde havia 1.850); máquina nomeada e estado térmico
  para latência (1,6× de variação); braços misturados contaminam o barato com o
  caro, e o número contaminado é plausível.
- **Braço de velocidade sem regime de máquina gravado mede a janela, não o
  braço.** A mesma máscara de afinidade custa 0× num regime e 8× noutro, e a mesma
  máquina entrega 0,141 e 3,19 s/chunk sem nada do produto mudar — 22×, contra os
  1,6× que a lição térmica de latência previa. Só braços **intercalados** dentro da
  janela pegam isso; blocos em sequência produzem tabela coerente e causa falsa, e
  foi o que aconteceu com o achado 16.1 e com a minha hipótese substituta
  (`docs/afinidade-e-estado-de-maquina.md`).
- **Recorte derivável não se anota; anotação que o índice não dá se confere a
  cada rodada.** Regra derivada errou por prefixo de pasta e deu número menor e
  plausível — que passaria.
- **Passada separada do indexador vale mais que a economia óbvia.** Grafo: 30 s
  contra 39 h, e foram cinco iterações de regra até a extração ficar certa.
- **Δ zero tem duas causas, e a regra de encerramento só vale para uma.** Empate é
  a mudança ter agido sem se separar do ruído; insensibilidade é a variável não
  tocar nenhum documento da fatia, e aí o zero é por construção. Na `F4-P.1` a
  fatia tinha n=100 e a variável tinha n=0 — o ranqueador de nome não pontuava um
  único documento de reunião no corpus sintético. A porta é
  `eval/comparar.py::_insensivel`, que compara o **ranking recuperado** e marca a
  célula com `∅`.
- **Efeito medido numa fatia não autoriza alavanca sobre os documentos daquela
  fatia.** O dano de nome em reunião é real (−0,089), e 11 de 12 dos documentos que
  causam esse dano são de **escritório**. A `F4-P.1` zerava o peso nos candidatos
  de reunião, que são as vítimas. Fatia definida pela **fonte esperada** e alavanca
  aplicada ao **candidato** são populações diferentes
  (`docs/ablacao-f4p1-nome-por-fonte.md`).
- **Régua que nomeia formato que o produto não ingere é regra sobre documento que
  nunca existe — e a fatia sai vazia sem erro.** `retrieve/fonte.py` classificava
  `.vtt` como grupo `reunião` e `hybrid.py` escolhia peso por esse grupo, com
  `.vtt` fora de `supported_extensions()`. A fatia que decidiria a `F4-P.1` tinha
  n=0 onde a declaração dizia n≈100, e a medição teria fechado o pacote como
  "hipótese refutada" cumprindo todas as regras. Pego por auditoria **antes** de
  medir; a porta é `tests/test_fonte_contrato.py`
  (`docs/fatia-reuniao-invisivel.md`).
- **Documento sem chunk é invisível até para o ranqueador de nome.** A fronteira
  do índice é de conteúdo, não de nome — formato novo é um conjunto de documentos
  saindo do zero absoluto.
- **Regra de exclusão que não casa com nada falha em silêncio, e o silêncio
  parece sucesso.** Menos arquivos é justamente o que se pediu. Duas instâncias:
  quatro `metricas-f2-*` commitados (20/08) e 3 h 22 min de máquina com medição
  contaminada (26/08). O que resolve é contagem **por regra** conferida contra
  zero antes de pagar o custo — `docs/duas-falhas-silenciosas.md`.
- **Número que qualifica a métrica não mora em documento.** A cobertura do
  dourado foi medida à mão em 24/08 e envelheceu duas vezes em quatro dias — o
  `ROADMAP.md` guardava 18,2%, o doc guardava 25%, e o número era 38,5%. Enquanto
  isso o `recall@1` seguia sendo citado como se valesse para o acervo inteiro. O
  que resolve é o relatório **recalcular** a ressalva a cada passada e não
  conseguir sair sem ela: `render_markdown` sem cobertura imprime "não medida"
  (`eval/cobertura.py`, `docs/dourado-cobertura.md`).
- **Quem publica progresso não pode ser quem trabalha.** A thread principal
  dentro de uma chamada só do ONNX não volta para atualizar a barra, e o arquivo
  congela dizendo "indexando" com ETA. Vigia em thread separada, e `lote` de embed
  é escolha de velocidade — os vetores de `lote=1` e `lote=32` são idênticos bit
  a bit, e o de 32 é 3,2× mais lento nesta CPU.
- **Número sem corpus, sem máquina e sem data é mentira** (`colaboracao.md` §4,
  regra 7).
- **Código de produto que só roda de dentro do repositório é defeito, não
  detalhe de empacotamento.** `retrieve/hybrid.py::search` importava `Hit` de
  `eval.harness`, e `eval/` não vai no pacote: o método onde a série histórica
  inteira foi medida levantava `ModuleNotFoundError` para quem instalou com
  `pip`. A mesma forma aparece em raiz de repositório deduzida de `__file__` e em
  `PYTHONPATH=src` gravado no config do cliente MCP.
- **`monkeypatch` só desfaz o que `monkeypatch` fez.** Escrita em `os.environ`
  vinda do produto dentro de um teste sobrevive à sessão inteira, e
  `delenv(raising=False)` sobre variável ausente não registra nem valor a
  restaurar. Um teste envenenou os seis seguintes, e o modo de falha era
  assimétrico entre os dois setups: verde onde havia placa, vermelho onde não.
- **N+1 é invisível no índice de teste.** O caminho de consulta gastava 350 idas
  ao SQLite por consulta no acervo real e 6 no índice de quatro trechos da suíte:
  a **forma** do acesso é a mesma, só o N muda. O que pega isso é contar
  consultas, não cronometrar.
- **Regra escrita sem quem a confira é conselho.** O teto de 500 linhas por
  módulo existia desde 25/08/2026 em prosa; `indexer.py` cresceu 610 linhas nos
  quatro dias seguintes.
- **A porta de entrada do usuário é onde o silêncio custa mais.** `_secao`
  recusava chave desconhecida em seis seções e o silêncio era total nas outras
  cinco portas do TOML — `[[base]]`, seção de topo, `[indexacao]`, `[padrao]` e
  entrada de `raizes`. Quem instala amanhã escreve o arquivo à mão, erra um
  nome, e roda com o padrão sem aviso. A guarda tem de ser **derivada do
  modelo**, não uma lista à mão: a lista à mão é o defeito na roupa seguinte.
- **Varredura de AST erra por parentesco de nó, e o erro passa por acidente.**
  `ast.NotIn` não é subclasse de `ast.In`; uma guarda que testava só `In` era
  cega para `"x" not in dados` — forma que **já estava** no arquivo que ela
  guardava, e o teste passava porque a mesma chave era lida por subscrito duas
  linhas abaixo. Prova de guarda tem de rodar contra caso **isolado**, nunca
  contra o arquivo real, onde a redundância mascara a cegueira.
- **Número que circula sem unidade vira três números.** "Cobertura do dourado"
  aparecia como 25%, 18,2% e 38,5% em cinco documentos, e o `README.md` dava a
  unidade errada ("das pastas" para uma fração de documentos). O instrumento
  reporta um **par** — 3,3% de piso e 38,5% de teto — e a leitura honesta fica
  entre os dois. Não é o mesmo defeito de "número sem corpus": é número **com**
  corpus e **sem** denominador.
- **Marcador escrito e nunca lido é comentário caro.** `MOTIVO_RECURSO` existia
  para separar *"tente com mais memória"* de *"este arquivo está corrompido"*,
  era gravado por três sítios e **consultado por nenhum** — a quarentena
  aposentava falha de ambiente com a política de arquivo podre, e duas passadas
  apertadas tiravam o documento do acervo até alguém editá-lo. Marcador novo
  entra com o leitor junto, ou não entra.
- **Resultado sem informação não pode apagar a informação anterior.** O filho
  que morria por recurso devolvia `ParseResult` sem `natureza`, e o `UPDATE`
  gravava zero em todas as colunas dela: o `digitalizado` sumia e o documento
  saía da fila de OCR. Não descobrir nada nesta passada não desfaz o que a
  anterior soube.
- **O escopo não desambigua nada quando o escopo é um.** "Todas as páginas
  falharam ⇒ é a máquina" é falso em N=1, e PDF escaneado de uma página é comum.
  Quem separa é o **tipo** da exceção — `ImportError` é a máquina, `MemoryError`
  é recurso, o resto é o documento; o escopo entra depois, como confiança.
- **Prova que copia a guarda prova a cópia.** As três provas "contra caso
  isolado" desta passada reimplementavam a lógica dentro do teste, e as duas
  cópias tinham **a mesma cegueira** sem ninguém notar: `ast.walk` de um `if`
  protegia o ramo `else`, e um predicado exigia `=` dentro do literal, o que
  tornava `ambiente["PYTHONPATH"] = …` invisível. O que fecha é um **núcleo
  puro** que o teste real e a prova chamam — não dois blocos que concordam hoje.
- **Conserto de silêncio pode ser pior que o silêncio.** Ao fazer a falha de
  OCR subir, o PDF misto passou de `ok` com texto nativo para `erro` sem nada —
  e `remover_documento` apaga chunks **e vetores já gravados**, com a quarentena
  aposentando o documento na segunda tentativa. Perder texto indexado é pior que
  não ganhar o do scan. A regra: **passada tardia que falha nunca apaga o
  resultado da anterior**, e o documento volta para a fila em vez de sair dela.
- **A mesma exceção é do documento numa camada e da máquina noutra.**
  `MemoryError` numa página A0 é o documento (593 MB a 72 dpi, por si só);
  `MemoryError` em todas as páginas é a janela. `ImportError` é sempre a
  máquina. Classificar pela exceção sozinha erra; o que classifica é **em que
  escopo ela se repete**.
- **Prova de guarda contra o arquivo real passa por acidente — sempre.** Três
  guardas escritas num dia passaram contra `src/` e falharam contra um caso
  isolado de duas linhas: a de hook aceitava qualquer `log.warning` no arquivo,
  a de `PYTHONPATH` não via texto gerado, e a de raiz do repositório comparava
  contra `json.dumps`, que **dobra as contrabarras do Windows** e nunca casava.
  Toda guarda nova entra com um teste sintético ao lado, onde o caso é a única
  coisa no arquivo.
- **Um valor de retorno com dois significados é um silêncio esperando
  acontecer.** `ocr_pdf` devolvia `None` para *"esta instalação não tem OCR"* e
  para *"o `pymupdf` não carregou agora"*. Condições opostas — uma é um no-op
  legítimo, a outra é o acervo sumindo — e a benigna vencia, porque um
  `except Exception` largo as fundia. O discriminador certo era o **nome do
  módulo que faltou**: pedir `X` e receber "falta X" é ausência; pedir `X` e
  receber "falta Y" é a máquina.
- **Duas guardas para a mesma coisa em dois ramos é uma guarda pela metade.**
  `parse_isolado` converte falha em status no filho **e** em processo, com dois
  `except` diferentes. Consertar um só é o modo de falha mais comum deste
  repositório, e aconteceu de novo com o registrador do MCP: consertei a CLI e
  deixei o painel, no mesmo dia em que escrevi a lição. O que fecha é a
  varredura que **deriva os sítios de chamada** — ela achou um terceiro que eu
  não sabia que existia.
- **Teste que pula por causa da máquina é teste que não tem veredito.** O piso
  de RAM do OCR existia porque o produto tinha duas reações à pressão de memória
  e só uma era honesta. Quando a outra ficou honesta, o piso saiu — e a régua
  que ficou não é "o OCR sempre produz texto", que seria assertar sobre a RAM: é
  *ou produz, ou o produto declara recurso*. Asserção sobre o comportamento
  garantido não depende da janela; asserção sobre o resultado depende.
- **Numa passada com cinco listas, a única escrita de cabeça foi a que
  quebrou.** Quatro eram derivadas — do modelo, do AST, do `pyproject.toml`. A
  quinta, o dialeto de topo do `census.toml`, saiu com uma chave quando o leitor
  lê três, e `census.example.toml` — versionado, e o que o clone copia — parou
  de carregar. O erro sobreviveu ao teste porque o teste também foi escrito de
  cabeça: montava um `census.toml` mínimo com a única chave que a lista tinha.
  **Lista e prova escritas pela mesma cabeça concordam sempre**; a prova tem de
  vir do artefato real ou de derivação independente.
- **`⊆` sobre conjunto pequeno é asserção que não assere.** Um teste comparava
  `{"limites"} ⊆ Maquina.__dataclass_fields__` e passava sobre 1/5 da
  superfície, enquanto o docstring afirmava cobrir a função inteira. Em guarda,
  igualdade exata; e quando o mecanismo real não é visível ao instrumento — ali
  a validação era delegada a uma dataclass, não a uma chave literal —, o que
  fecha é um segundo teste **de comportamento**, não um `⊆` mais largo.
- **Guarda que consulta o disco não prova nada sobre o clone.** O teste de links
  aceitava link para pasta usando `is_dir()`: pasta que existe nesta máquina com
  zero arquivos versionados passava verde e daria 404 em quem clonasse — a
  classe que aquele teste existe para pegar, dentro dele.
- **O teste que confirma o conserto tem de reprovar com o conserto desligado.**
  No `Q15.a` a primeira versão passava nos dois estados: ela media duas passadas
  **com** `--ocr`, e com OCR o defeito não existe — a fase de OCR é a última e
  regrava o `erro` por cima do `vazio`. O defeito vivia na passada de rotina,
  **sem** a flag. Ligar e desligar o conserto custou uma execução e derrubou o
  pacote inteiro; ler o código não teria derrubado.
- **Garantia que depende de alguém lembrar da flag é coincidência.** O primeiro
  conserto do `Q15.a` só valia quando a passada rodava com `--ocr`, o que é
  justamente o que a passada de rotina não faz.
- **`IN (...)` sem lote é o inverso do N+1: a forma está certa e só o N quebra.**
  O teto de parâmetros do SQLite é da build da máquina do usuário, não nosso, e
  uma pasta de 2.156 documentos o estoura. O que não prova nada é "listar 1.100 e
  ver se explode" — numa build com teto de 32.766 isso passa por acidente. A
  afirmação tem de ser sobre o produto: nenhuma consulta manda mais que o lote.
- **Série histórica sem mecanismo é frase.** `dourado-v1` era citado como
  congelado em três documentos e nada congelava nada — o conjunto é gitignorado,
  e uma pergunta editada movia a linha de base sem deixar diff. O que fecha é o
  manifesto **versionado** de impressões digitais: guarda o que move a métrica,
  não o texto, e a mudança passa a ter diff para revisar.
- **Auditoria que não executa erra a contagem, e erra para os dois lados.**
  Dos cinco números da passada de 29/08, quatro estavam errados quando medidos
  ao executar: 6 links quebrados e não 64, sete defaults duplicados e não seis,
  18 sítios de import e não dez, 16 construções repetidas e não 12. Diagnóstico
  é hipótese; a contagem só existe depois de rodar.

## O corpus real — não é um vault Obsidian

Isso já foi motivo de mal-entendido; não reintroduzir a premissa errada.

- **Pessoal**: pastas soltas em disco (Windows)
- **Corporativo**: SharePoint via **pasta sincronizada** do cliente OneDrive.
  Graph API (`Sites.Selected` + consentimento de admin) fica para a F5
- **Formatos dominantes**: PDF, DOCX, XLSX, PPTX. Markdown é opcional
- **Não há Obsidian instalado e não há wikilinks.** O Obsidian é gratuito e
  dispensa conta, mas foi deliberadamente **não** adotado — não acrescenta nada
  sobre uma pilha de arquivos Office. Se entrar depois, wikilink é sinal
  *adicional*, nunca o principal. **Isto vale para a entrada, e continua
  valendo.** O `J.e` do pacote J (30/08/2026) traz o Obsidian de volta como
  **saída**: um vault Markdown exportado por comando explícito, *view* one-way e
  descartável, com wikilinks derivados da tabela `mencoes` que já existe. Nada
  do vault volta para o acervo nem para o índice
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

## Onde as coisas moram — e o que já tem guarda

Atualizado em 29/08/2026, depois da passada de refatoração estrutural. A skill
`/navegar` traz o mesmo mapa com as perguntas ao lado; `docs/README.md` é o
índice da documentação.

**Caminho de consulta** — o que o cliente MCP executa:
`mcp/server.py` → `retrieve/hybrid.py::buscar_chunks` → `index/store.py`.
`retrieve/contrato.py` guarda `Hit` e o protocolo `Retriever`, que o `eval/`
importa — **nunca o contrário**: `eval/` é o único diretório fora do pacote.

**Caminho de leitura** — o segundo modo, que não ranqueia nada:
`mcp/leitura.py` (as tools `list_folder` e `outline`) → `acesso/manifesto.py` (o
que vira retorno, com cursor) → `acesso/registro.py` (as consultas) e
`acesso/identidade.py` (`doc_id`, URI `sc://`, qual caminho é o preferido). Ele
lê o mesmo registro que a busca e **não** passa por `retrieve/hybrid.py`.

**Indexação**: `index/indexer.py` é o laço. Ao redor dele, e com uma razão de
mudar cada: `index/cli.py` (as flags), `index/trava.py` (a trava exclusiva),
`index/travas.py` (só os nomes dos arquivos de trava, para quem precisa lê-los
sem carregar o encoder), `index/repesca.py` (este documento precisa reprocessar?),
`index/resultado.py` (o que a passada relata) e `index/esquema.py` (as tabelas e
os índices do registro, com o motivo de cada um).

**As fronteiras que têm teste**, e o que cada uma custou antes de tê-lo:

| Fronteira | Guarda |
|---|---|
| `src/` não importa `eval/` — o pacote não leva o harness | `tests/test_pacote.py` |
| a raiz do repositório tem um nome só (`repositorio.raiz()`) | `tests/test_pacote.py` |
| nenhum teste entrega `os.environ` sujo ao seguinte | `conftest.py` da raiz + `tests/test_isolamento_da_suite.py` |
| o painel abre sem carregar o encoder | `tests/test_painel.py` |
| uma consulta não volta a custar uma ida ao banco por candidato | `tests/test_hybrid.py` |
| módulo e função não crescem sem que alguém escreva por quê | `tests/test_tamanho_dos_modulos.py` |
| todo formato que o LibreOffice converte ganha o timeout de convert | `tests/test_quarentena.py` |
| OCR não dá veredito abaixo do piso de RAM declarado | `tests/test_ocr.py` |
| `except Exception` sem motivo escrito não entra | `tests/test_politica_excecoes.py` |
| nome real do acervo em arquivo versionado | `tests/test_saneamento.py` |
| chave desconhecida no `config.toml`, em qualquer nível | `tests/test_config_chaves.py` |
| um valor do `config.example.toml` divergir do padrão do código | `tests/test_config.py` |
| todo `[project.scripts]` virou executável instalado | `tests/test_pacote.py` |
| link em arquivo versionado apontar para arquivo que o clone não tem | `tests/test_documentacao.py` |
| arquivo de teste virar módulo de apoio de outro | `tests/test_isolamento_da_suite.py` |
| id de documento mudar porque alguém moveu o arquivo | `tests/test_identidade.py` |
| qual dos N caminhos do mesmo conteúdo é o principal depender da ordem de indexação | `tests/test_identidade.py` |
| tool de leitura cortar a resposta sem devolver cursor | `tests/test_leitura.py` |

**Skills**: `/pacote` antes de abrir a branch · `/medir` antes de rodar eval ·
`/depurar` quando algo quebra · `/revisar` antes do PR · `/entregar` no commit ·
`/navegar` para achar as coisas.

## Stack

Python 3.12 · `mcp` · BGE-M3 (`fastembed`) · `bge-reranker-v2-m3` · `lancedb` ·
`sqlite3` · `pymupdf4llm` · `watchdog` · `pytest`

## Como rodar

```bash
pip install -e .
py -m pytest tests/ eval/ -q   # a suíte inteira — ~2 min, sem GPU e sem modelo
py -m ruff check src tests eval && py -m pyright src
```

Fora da suíte padrão, por declaração (`pyproject.toml`, `markers`):

```bash
py -m pytest -m modelo     # carrega o encoder real — ~2 GB na primeira vez
py -m pytest -m ocr        # exige o extra [ocr]
py -m pytest -m cuda       # exige GPU
py -m pytest -m arquivo    # instrumento de pacote encerrado (eval/arquivo/)
```

## Convenções

- **Teto de tamanho: ~500 linhas por módulo, ~60 por função.** Não é estética: é
  o pior caso para edição por agente, e a regra existia desde 25/08 sem ninguém
  conferindo — `indexer.py` cresceu 610 linhas em quatro dias. Hoje quem confere é
  `tests/test_tamanho_dos_modulos.py`, e a tabela dos que já eram grandes **só
  desce**
- **Docstring de decisão se move verbatim.** Elas têm número e data, e são ADR
  embutida que não descola do código. Refactor que apaga histórico de decisão é
  reprovação, mesmo com a suíte verde
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

## Avaliação — três camadas, e o dourado real não é juiz

`eval/golden/` contém pares pergunta → fonte(s) esperada(s). Métricas: recall@k,
MRR, nDCG@5 e @10, com **IC95 pareado** (`eval.comparar`). Relatórios em `docs/`.

| Camada | O que é | Papel |
|---|---|---|
| 1 | dourado real, congelado como `dourado-v1` | **regressão** — bloqueia merge, nunca decide arquitetura sozinho |
| 2 | sintético gerado por código (`E1`) | **decisão** — é a camada que fala de base desconhecida |
| 3 | benchmark externo amostrado (`C5`) | **alarme** — detecta endogamia do gerador |

Três regras, e as duas últimas são de 25/08/2026
([`docs/regra-de-ouro.md`](docs/regra-de-ouro.md)):

- **Nenhuma otimização de precisão sem número antes e depois** (invariante 4).
- **Nenhum relatório sem a cobertura que ele alcança** — quantas pastas do índice
  as perguntas conseguem tocar entra ao lado da tabela, medida na hora
  (`py -m eval.cobertura --base <id>`). Cobertura baixa é limitação declarada, não
  reprovação; omiti-la é que faz a métrica de um canto do acervo ser lida como a
  do acervo.
- **Nenhuma varredura sem efeito mínimo e fatia declarados antes**; empate
  encerra o pacote.
- **Nenhum defeito consertado sem a classe generalizada** — qual teste ou método
  passa a pegá-la sozinho.

## Contexto do usuário

Ambiente Windows 11, PowerShell. Projeto irmão em `C:\Pytondev\TotalAudioRelator`
(app desktop de gravação de reuniões) — de onde vêm os padrões de LGPD,
`audit_trail.py` e `encryption.py` para reaproveitar na fase F5.
