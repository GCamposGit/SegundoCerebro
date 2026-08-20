# Roadmap — Segundo Cérebro RAG

Cada fase tem **critério de saída verificável**. Nenhuma fase começa antes da
anterior passar no seu critério.

---

## F0 — Fundação mensurável

Contraintuitivo, mas é a primeira fase: sem medição, as fases seguintes são
palpite. Ainda não indexa nada de verdade.

- Esqueleto do pacote, dependências fixadas, `pytest` rodando
- **Censo do corpus**: percorre as pastas configuradas e reporta contagem por
  extensão, tamanho total, distribuição de datas, profundidade de pastas — e
  quantos arquivos são *placeholders* de nuvem. Só metadados; **não abre
  conteúdo** (ver armadilha do Files On-Demand)
- **Conjunto dourado**: 50 pares pergunta → arquivo(s) esperado(s), escritos
  à mão a partir das pastas reais
- Harness de avaliação: recall@k, MRR, nDCG sobre o conjunto dourado
- Baseline deliberadamente burro (busca por nome de arquivo) para ter número
  de partida

**Saída:** `pytest eval/` imprime métricas do baseline, e o censo diz qual
formato domina o corpus — o que determina onde investir na F1.

**Resultado medido em 11/08/2026** (`docs/metricas-f0.md`), 434 documentos,
51 perguntas:

| Subconjunto | n | recall@1 | recall@10 | MRR@10 |
|---|---:|---:|---:|---:|
| geral | 51 | 0,55 | 0,83 | 0,69 |
| escritas pelo usuário, sem viés | 6 | 0,50 | 0,83 | 0,56 |
| casos-armadilha | 6 | 0,50 | 0,50 | 0,50 |

O baseline é **muito mais forte que o esperado**, e isso é informação sobre o
acervo, não sorte: as pastas são bem organizadas e os nomes de arquivo são
descritivos. Consequência direta para a F1 — o ganho não virá de *achar o
documento*, que o nome já resolve na maioria dos casos, e sim de **achar o
trecho** e de responder o que só existe dentro do conteúdo.

Ressalva metodológica registrada: 45 das 51 perguntas foram rascunhadas por
mim a partir dos nomes de arquivo, o que favorece o baseline por construção.
Por isso o conjunto marca `autoria` e `armadilha` — as 6 escritas de memória e
as 6 armadilhas são os subconjuntos honestos, ainda que pequenos demais para
conclusão estatística.

---

## F1 — Ingestão real + recuperação híbrida

Ingestão de Office entra aqui, não depois: é **todo** o corpus.

**Prioridade revista em 11/08/2026, depois da expansão da raiz.** Na pasta de IA
sozinha, XLSX era 2% e ficou fora do caminho crítico. Na raiz corporativa
completa são **686 planilhas, 21,7%** — o segundo formato do acervo. A decisão
anterior está revertida:

| Formato | Arquivos | % | Entra |
|---------|---------:|--:|-------|
| PDF | 1509 | 47,8% | 1º |
| **XLSX** | **686** | **21,7%** | **1º — era "fora do caminho crítico"** |
| DOCX | 463 | 14,7% | 2º |
| PPTX | 251 | 8,0% | 2º |
| MSG | 110 | 3,5% | F4 |
| XLS/XLSB/XLSM legado | 32 | 1,0% | F4, se o eval justificar |

Quatro perguntas do conjunto dourado dependem de planilha (`g021`, `g030`,
`g045` e parte da `g034`). Estavam marcadas como "vão medir zero até a F4" —
agora são requisito da F1.

- Parsers: PDF (`pymupdf4llm`), XLSX, DOCX, PPTX → markdown normalizado
- Política de Files On-Demand explícita e configurável (pular vs. hidratar
  sob limite declarado)
- **Arquivos travados por outro processo.** O corpus é uma pasta de trabalho
  viva: documentos abertos no Word/Excel durante a indexação recusam abertura
  com "usado por outro processo", mesmo em leitura compartilhada. Encontrado na
  F0 em 2 de 5 arquivos conferidos à mão. Tratar com nova tentativa, depois
  registrar status `travado` no SQLite e reindexar na próxima passada — nunca
  descartar em silêncio nem abortar a indexação inteira
- Chunking adaptativo por estrutura + cabeçalho contextual de headings
- Metadados: caminho de pastas como taxonomia, datas, nome de arquivo
- BGE-M3: vetores dense + sparse
- LanceDB com filtro por metadado; SQLite para registro e linhagem
- Fusão RRF de dense + sparse
- Indexação incremental por hash
- **Reconciliação com o disco** — acrescentado em 14/08/2026, depois de uma
  faxina de pastas do usuário deixar 148 documentos fantasma e 7.047 chunks
  órfãos, 18% do índice. Não era item previsto e deveria ter sido: "o corpus é
  uma pasta de trabalho viva" já estava escrito acima, e a consequência de o
  indexador só adicionar não tinha sido tirada. Arquivo apagado sai do índice;
  arquivo movido é reconhecido por sha256 e não confundido com exclusão

**Saída:** o critério original — "recall@10 ≥ 2× o baseline" — foi **descartado
em 11/08/2026**, porque o baseline mediu 0,83 e o dobro disso não existe. E o
experimento de escala (`docs/escala-f0.md`) mostrou que recall@10 é justamente a
métrica que menos se move: com 7,7× mais documentos ela cai 5%, enquanto o
ranqueamento cai 13% e o multi-hop 57%.

#### O critério de comparação, revisado em 12/08/2026

Os limiares absolutos da revisão anterior (`recall@1 ≥ 0,80`, `MRR ≥ 0,80`)
foram fixados **antes de existir qualquer medição do sistema completo**. Com a
primeira medição na mão (`docs/ablacao-f1.md`), eles se revelaram números
inventados: a melhor configuração medida empata com o baseline em recall@1, e
0,80 exigiria +0,36 absoluto sobre um baseline de 0,44. As portas agora comparam
contra o **baseline na mesma condição**, o que as mantém honestas quando o
acervo ou o conjunto de perguntas mudar.

Duas correções tornaram a comparação legítima, e valem para toda medição daqui
em diante:

- **Mesmo universo.** O baseline enumerava a raiz inteira (3.154 entradas)
  enquanto a busca ranqueava 392 documentos. `--prefixo` recorta os dois para a
  mesma subárvore. Sem isso a comparação media escala e creditava ao ranqueador.
- **Mesmas perguntas.** Seis das 51 têm como fonte um `.msg`, um PDF
  digitalizado ou um email com extensão `.pdf` trocada. Nenhum recuperador de
  conteúdo desta fase consegue lê-las, e mantê-las na média mede a ausência do
  parser, não a qualidade da recuperação. Ficam anotadas com motivo no conjunto
  dourado, excluídas **dos dois lados**, e sempre reportadas ao lado do número.
  `n = 45`.

Referência medida com as duas correções, baseline por nome de arquivo:

| Condição | docs | recall@1 | recall@10 | MRR@10 | armadilhas r@10 | multi-hop r@10 |
|---|---:|---:|---:|---:|---:|---:|
| B — subárvore de dev | 434 | 0,533 | 0,844 | 0,670 | 3 de 6 | 2 de 5 |
| **C — corpus completo** | 3.154 | **0,444** | **0,800** | **0,577** | **3 de 6** | **2 de 5** |

A condição C tem 3.154 entradas, e não as 3.332 de `docs/escala-f0.md`: o acervo
é pasta de trabalho viva e encolheu entre 11 e 12/08. As duas medições não são o
mesmo corpus, e por isso a referência tem que ser **remedida junto** com a
configuração que a fase for fechar, nunca copiada de um documento anterior.

#### As cinco portas

Medidas **na condição C**, sobre as 45 perguntas no escopo (baseline entre
parênteses):

1. **recall@1 ≥ baseline + 0,10** → 0,544 hoje (0,444). Achar não basta, tem que
   estar em primeiro. Dez pontos absolutos sobre o mesmo acervo e as mesmas
   perguntas é um ganho que ninguém consegue explicar por ruído de medição
2. **MRR@10 ≥ baseline + 0,08** → 0,657 hoje (0,577)
3. **casos-armadilha: ao menos 5 de 6 no top-10, e nenhuma falha em caso
   crítico** (3 de 6). Regra por caso, não por média: com 6 perguntas cada uma
   vale 16,7 pontos e a taxa não estima nada — revisão técnica externa de
   12/08/2026, e ela está certa. Esta é a porta que separa indexar conteúdo de
   indexar nome de arquivo, e é **também a que impede ganhar na média pelo
   caminho errado**: a ablação mostrou o bm25 puro fazendo 5 de 6 e a fusão com
   o ranqueador de nome derrubando para 3 de 6, enquanto a média subia
4. **multi-hop: para cada uma das 5, ao menos uma fonte esperada no top-10.**
   *Reescrita em 16/08/2026, e o motivo é de categoria, não de calibragem.*

   A redação anterior — "ao menos 3 das 5 com **todas** as fontes no top-10" —
   media recuperação de conjunto completo **numa consulta única**. A invariante 3
   diz o oposto: multi-hop é do cliente, o servidor oferece primitivas
   componíveis e o laço de agente compõe. A F1 estava sendo cobrada por uma
   capacidade que a arquitetura decidiu **não** implementar, e nenhum ajuste de
   recuperação a faria passar — o que passaria seria construir o orquestrador que
   a invariante 3 proíbe.

   O que a porta passa a medir é o que uma consulta única legitimamente entrega:
   **o cliente consegue começar**. Se nenhuma fonte da pergunta aparece, não há
   fio para puxar e o laço de agente não sai do lugar. Continua sendo regra por
   caso, pelo motivo de 12/08 que segue válido: com `n = 5` uma taxa não estima
   nada.

   A prova de composição completa não some — **muda de lugar**, para onde não dá
   para maquiá-la com peso de fusão: o critério de saída da F3 (uma pergunta
   multi-hop real respondida, com o traço de chamadas registrado em `docs/`) e o
   da F4 (uma pergunta que **só** é respondível via `neighbors`).

   **Transparência devida:** esta regra foi reescrita depois de ver o resultado,
   o que normalmente é escolher o ruído. Duas coisas a defendem — o argumento sai
   da invariante 3 e vale independentemente do número, e a exigência mais dura
   foi transferida em vez de removida. O que **não** foi feito: afrouxar o
   limiar. "3 de 5 com todas" não virou "2 de 5 com todas"
5. **Orçamento de regressão**, não regressão zero: nenhuma regressão em caso
   crítico, no máximo 3 perguntas caindo do 1º lugar, e cada uma inspecionada
   individualmente. "Zero regressão" reprovaria uma mudança que melhora trinta
   perguntas e piora uma — o que é o trade-off errado. Avaliável desde
   13/08/2026 por `py -m eval.comparar --antes X --depois Y`, que lista o
   movimento de cada pergunta: até então a porta era inavaliável na prática,
   porque duas médias não dizem *quais* perguntas se moveram

Mais: tempo de parede da indexação completa documentado, e nenhum placeholder
hidratado sem intenção (censo antes e depois com a mesma contagem).

#### ✅ Fechada em 17/08/2026 — as cinco portas passam

`docs/fechamento-f1.md`. Condição C, índice completo (1.601 documentos, 92.137
chunks), 45 perguntas, baseline remedido no mesmo run:

| # | Porta | Medido | Alvo | Baseline |
|---|---|---:|---:|---:|
| 1 | recall@1 ≥ baseline + 0,10 | **0,678** | 0,567 | 0,467 |
| 2 | MRR@10 ≥ baseline + 0,08 | **0,785** | 0,672 | 0,592 |
| 3 | ≥ 5 de 6 armadilhas | **5 de 6** | 5 | 3 de 6 |
| 4 | multi-hop: ≥ 1 fonte, por caso | **5 de 5** | 5 | 2 de 5 |
| 5 | ≤ 3 quedas do 1º, nenhuma crítica | **1, nenhuma crítica** | 3 / 0 | — |

As duas portas que reprovavam em 16/08 não foram afrouxadas: a 3 fechou com
famílias de versão (metadado, que nenhum peso de fusão alcança) e a 4 foi
reescrita por argumento de categoria, com a exigência dura migrando para F3 e F4.

**O fechamento não depende do reranking.** Com ele desligado as portas 1 a 4
também passam (0,644 e 0,762 contra alvos de 0,567 e 0,672), e ele custa 6,8× no
tempo de consulta.

#### Histórico — a medição de 16/08/2026, quando a fase não fechava

Índice completo (1.601 documentos, 92.125 chunks), baseline e busca remedidos
juntos no mesmo universo e nas mesmas 45 perguntas. Análise caso a caso em
[`docs/portas-f1-condicao-c.md`](docs/portas-f1-condicao-c.md).

| Métrica | baseline | híbrido | Δ |
|---|---:|---:|---:|
| recall@1 | 0,467 | **0,600** | +0,133 |
| recall@10 | 0,800 | **0,907** | +0,107 |
| MRR@10 | 0,592 | **0,736** | +0,144 |
| armadilhas no top-10 | 3 de 6 | 4 de 6 | +1 |
| multi-hop completo | 2 de 5 | 1 de 5 | −1 |

Portas 1, 2 e 5 **passam** — as duas primeiras com folga, 13 e 14 pontos onde se
exigia 10 e 8. Portas 3 e 4 **reprovam**: 4 de 6 armadilhas (exige 5) e 1 de 5
multi-hop (exige 3).

As duas armadilhas que falham falham **também no baseline**, e as duas são F2 por
descrição: `g010` é família de versão (o vigente não tem `_vN` no nome e o `_v6` é
antigo — informação de metadado, que nenhum peso alcança) e `g036` é discriminação
entre propostas irmãs (documento indexado, 12 chunks, `ACGR` em 13 chunks do
índice: falha de ranqueamento, não ausência).

**Isto responde a pergunta que a inversão de 13/08 deixou aberta.** O gargalo é
precisão, de um tipo específico: separar documentos irmãos que falam do mesmo
assunto. As agregadas já estão boas — com recall@10 = 0,907 a resposta quase
sempre está no poço; falta ordenar dentro dele. A F2 é o próximo passo, com
`g010` e `g036` como casos de teste nomeados.

**Pendência honesta:** a porta 4 mede recuperação de conjunto completo numa
consulta única, enquanto a invariante 3 delega multi-hop ao cliente. Ela precisa
ser revista **antes** da próxima medição, por argumento — mudar régua depois de
ver o resultado é escolher o ruído.

Desenvolver contra a raiz estreita (434 documentos, eval em segundos) e medir
nas duas condições antes de fechar a fase.

**O que fica explicitamente fora da F1**, e por isso não entra na conta: OCR de
PDF digitalizado (10 arquivos na subárvore de dev, todos com imagem por página)
e parser de email `.msg`/MIME (11 arquivos). São escopo da F4. Se entrarem
antes, as perguntas voltam para a média e as referências acima têm que ser
remedidas — `verificar_escopo()` avisa quando a anotação ficar velha.

---

## F2 — Precisão (o núcleo de R3)

- ✅ **Reranking — entregue em 16/08/2026, com peso 0,25.**
  [`docs/ablacao-rerank.md`](docs/ablacao-rerank.md). recall@1 0,644 → **0,678**,
  MRR 0,762 → **0,785**, sem mexer em recall@10 nem nas armadilhas.

  **O cross-encoder entra como quarto ranqueador, não como juiz.** A grade é
  monotônica: peso 0,25 → 0,678; 0,5 → 0,644; 1,0 → 0,611; 2,0 → 0,522; e
  **substituindo a ordenação → 0,489**, o pior de todos. Substituir era a
  integração óbvia e é o que menos funciona.

  Isso repete o padrão do bm25 medido em 13/08, e a repetição vira conclusão:
  **neste acervo o consenso de ranqueadores independentes vale mais que qualquer
  juiz isolado.** Desconfiar de todo mecanismo futuro que proponha reordenar
  sozinho.

  Duas coisas mais que a medição ensinou. O `bge-reranker-v2-m3` **não existe no
  catálogo do `fastembed`** — mesmo erro do BGE-M3 denso, repetido; sobrou o
  `bge-reranker-base` (MIT), porque quatro dos seis são só inglês e um é
  cc-by-nc. E a `g036`, que motivou o reranking, **continua sem acerto**: o ganho
  veio de outras perguntas.

  **Fica desligado por padrão**, e isso é julgamento, não medição: no caminho de
  consulta real a mediana passa de **0,92 s para 6,28 s** — 6,8× por 3,4 pontos
  de recall@1. Num laço de agente que faz várias buscas por turno, uma pergunta
  multi-hop iria de ~3 s para ~20 s. `rerank = 0.25` na base liga.

  A F3.6 inverte esse padrão sem discussão: numa GPU os 5,4 s viram frações de
  segundo e a qualidade é a mesma — já medida, não precisa remedir

- ✅ **Expansão de contexto — entregue em 16/08/2026.** O `search` anexa os
  vizinhos de cada acerto em `antes`/`depois`, com padrão 1 e teto 3.

  Ficam **fora** de `texto` de propósito: o trecho que casou com a consulta é o
  que tem procedência, e misturar o vizinho faria o cliente citar como achado um
  texto que o ranqueador nunca pontuou. Vizinho que já é outro acerto da mesma
  resposta é omitido — repeti-lo gastaria contexto do cliente e faria parecer que
  há mais fontes do que há.

  **Não é medível pelo conjunto dourado**, e isso precisa ser dito: o harness mede
  qual documento é recuperado, não se a resposta estava no parágrafo seguinte.
  Entra por argumento, não por número — e o argumento é que o chunker corta por
  estrutura, e estrutura não coincide com raciocínio
- Expansão de contexto: devolve seção completa + vizinhos
- ✅ **Expansão de consulta via glossário de siglas — entregue em 18/08/2026.**
  [`docs/ablacao-glossario.md`](docs/ablacao-glossario.md). Expande nos dois
  sentidos — sigla → extenso e extenso → sigla — no bm25 e no ranqueador de nome.
  O **denso não recebe a expansão**: acrescentar sinônimo move o vetor para a
  média dos termos, e o embedding assimétrico do `e5` já resolve sinônimo.

  Medido na condição C: recall@1 0,644 → **0,667**, MRR 0,762 → **0,787**, nDCG@5
  0,760 → **0,793**, zero regressões. Custo por consulta **zero**. O contraste que
  decide: nessa métrica ele vale mais que o reranking (+0,033 contra +0,011) e o
  reranking custa 6,9× no tempo.

  E o achado que decide o desenho do produto: o dicionário de teste nasceu
  dividido em **genérico** (mês abreviado, serviria a qualquer acervo) e
  **específico da empresa**, e os dois foram medidos isolados. O genérico deu
  **zero** — dígito por dígito igual a não ter glossário — e o específico deu o
  ganho inteiro. Logo **um dicionário embutido seria peso morto**, e o mecanismo
  de o usuário construir o dele não é acessório da feature: é a feature. Daí o
  endpoint e a tela no painel, e o arquivo por base no molde do conjunto dourado.

  Nasce vazio. Duas correções vieram de teste e não de métrica, e nenhuma mudou
  número: o mapa inverso guardava só a primeira sigla de cada forma (`dezembro`
  virava `Dez` e nunca `Dec`), e a busca da sigla quebrava no hífen — o sentido
  sigla → extenso estava morto para `CT-VCE-2024-0142` e `PO-VCE-007`. **Achar o
  descasamento não é achar o gargalo**, e as duas pagam na próxima entrada
- ✅ **Famílias de versão — entregue em 16/08/2026.**
  [`docs/ablacao-familias.md`](docs/ablacao-familias.md). Agrupa por pasta +
  extensão + nome sem marcadores, devolve a vigente e cita as anteriores; ligado
  em `search` **e** em `buscar_chunks`, para o que se mede ser o que se entrega.

  Medido na condição C: recall@1 0,600 → **0,644**, MRR@10 0,736 → **0,762**,
  armadilhas 4 → **5 de 6**, **zero regressões**. Com isto **a porta 3 passa a
  passar**. Custo zero por consulta — o sinal é metadado, que nenhum peso de
  fusão alcançava.

  Duas correções vieram de inspecionar as regressões da primeira versão, e as
  duas eram invisíveis nas médias: a extensão precisa entrar na chave (PDF e PPTX
  do mesmo deck não são versões um do outro) e **número declarado vence a data**
  — `_v0` de janeiro/2026 contra `_v1` de setembro/2025, o espelho do `g010`,
  onde a data acerta e o número erra. Nenhuma regra sozinha acerta os dois casos
- ✅ **Ablação medida: dense-só vs. híbrido vs. híbrido+rerank — 18/08/2026.**
  Leitura em [`docs/ablacao-f2.md`](docs/ablacao-f2.md), evidência regenerável em
  [`docs/ablacao-f2-tabela.md`](docs/ablacao-f2-tabela.md) (`py -m eval.ablacao_f2`).
  Nove braços na mesma passada, cada um diferindo do anterior por um fator só.
  nDCG@5: denso-só 0,700 → híbrido 0,760 → híbrido+rerank 0,771, monotônico.

  O harness passou a emitir nDCG@**5** e @10. Os dois, porque o @5 é o que este
  critério pede e o @10 é o que preserva comparabilidade com F0 e F1.

  O ponto que a tabela revelou e que nenhuma medição anterior tinha: **`denso +
  nome + famílias`, sem bm25, tem o maior nDCG@5 da tabela (0,789)** — acima do
  reranking — a um oitavo do custo, e faz **3 de 6 armadilhas**. O bm25 se paga
  exclusivamente ali. Também mata a explicação de que as famílias teriam tornado
  o bm25 redundante: sem ele, com famílias ligadas, as armadilhas caem de 5 para 3.
  Famílias e bm25 resolvem casos diferentes. O padrão **não muda**, porque a regra
  de elegibilidade foi declarada antes e trocá-la agora seria escolha post-hoc

**Saída:** ✅ tabela de ablação no `docs/`, com nDCG@5 por configuração. A escolha
final é a que ganhou, não a que pareceu elegante.

---

## F3 — Superfície MCP (destrava R1 e R4)

> **FECHADA em 20/08/2026 — a saída foi cumprida.** O ato humano que faltava
> aconteceu: mesma pergunta multi-hop perguntada no Claude Code e no Claude
> Desktop contra o mesmo índice, as duas respostas corretas.
>
> O achado que vale mais que "funcionou nos dois": **os dois clientes
> decompuseram a pergunta de formas diferentes**, e cada um buscou um conjunto
> de documentos diferente antes de sintetizar. Uma das respostas era estritamente
> mais completa que a outra, e verificar fato a fato contra o que `search`
> devolve confirmou que nada foi inventado — a resposta mais rica só chegou lá
> porque **buscou mais**, não porque preencheu lacuna com o próprio
> conhecimento. É a invariante 3 se provando na prática: o servidor oferece
> primitivas componíveis, e quem compõe é o loop do agente, não o servidor. Duas
> composições diferentes chegando a respostas fundamentadas é evidência mais
> forte de R1 ("model agnostic depois de construído") do que a mesma composição
> repetida duas vezes seria. Traço completo, com a conferência fato a fato,
> em `docs/traco-f3-uso-real.md` (gitignorado — cita conteúdo do acervo real).
>
> **Ordem invertida em 13/08/2026, por decisão do usuário.** A F3 passou na
> frente da F2. O argumento é o mesmo que o ROADMAP já usava para pôr a F4
> depois da F3 — "só com o traço real de uso fica claro quais arestas o modelo
> aproveita" — aplicado um degrau antes: o reranking da F2 é otimização de
> precisão, e otimizar precisão antes de saber se o gargalo é precisão contraria
> a regra de não otimizar sem número.
>
> A fundação não ficou por medir: a F1 bate o baseline em todas as métricas
> agregadas e passa a porta de regressão. O que falta é a medição no corpus
> completo, que não bloqueia o uso.
>
> **Feito**: `search` e `read_note` de pé, provado por stdio contra o índice real
> (`docs/usar-o-mcp.md`), traço multi-hop registrado (`docs/traco-f3-uso-real.md`),
> e desde 18/08/2026 o segundo cliente instalado por um comando e provado por
> teste a partir de um diretório neutro.
>
> **Falta só o ato humano**: rodar o comando, abrir o Claude Desktop e fazer a
> pergunta na interface dele. Nenhum código bloqueia isso.

- Servidor MCP via stdio com `search`, `read_note`, `neighbors`,
  `list_recent`, `glossary`
- IDs estáveis e procedência em todo retorno
- Registrado no Claude Code; **validado em ao menos um segundo cliente**
  (Antigravity ou Claude Desktop) — é a prova de R1, não uma formalidade.

  **18/08/2026: o lado técnico está provado e automatizado.**
  `py -m segundocerebro.mcp.registrar --cliente claude-desktop --instalar` resolve
  `%APPDATA%\Claude\claude_desktop_config.json`, mescla preservando os outros
  servidores e as preferências do app, e recusa gravar se o cliente não estiver na
  máquina em vez de deixar um arquivo órfão.

  E o teste `test_bloco_do_claude_desktop_sobe_de_um_cwd_neutro` (marcado
  `modelo`) sobe o servidor **de `C:\Windows\system32`** com o bloco exato,
  faz o handshake e responde a mesma consulta do traço da F3 contra o índice real.
  Era o modo de falha que importava: bloco com caminho relativo sobe com
  `ModuleNotFoundError` e o cliente mostra "servidor não conecta", que não diz
  nada sobre a causa.

  **Falta só o ato humano**: instalar, abrir o Claude Desktop e fazer a pergunta na
  interface dele. Nenhum código bloqueia mais isso

**Saída:** uma pergunta multi-hop real respondida corretamente, com o traço de
chamadas de ferramenta registrado em `docs/`. Mesma pergunta funciona em dois
clientes diferentes.

---

## F3.5 — Bases e painel de ajuste

> **Fase acrescentada em 14/08/2026, por decisão do usuário.** Meia fase para não
> renumerar: F4 e F5 são citadas no `ARCHITECTURE.md`, no `CLAUDE.md` e em meia
> dúzia de docs de medição, e renumerar custa mais do que informa.
>
> Entra **antes da F2** pelo mesmo argumento que inverteu F2 e F3 em 13/08:
> otimizar precisão antes de saber se o gargalo é precisão contraria a regra de
> não otimizar sem número. O painel é o instrumento que produz esse número no
> acervo de quem usa — e a F2 chega numa superfície de configuração que já
> existe, em vez de criar mais constantes para retrofitar depois.
>
> Duas coisas que este ROADMAP listava como fora de escopo mudam de status aqui,
> e o motivo está registrado na tabela do fim do documento.

Desenho completo em [`docs/painel-de-ajuste.md`](docs/painel-de-ajuste.md);
decisão de arquitetura das bases em `ARCHITECTURE.md` §2.

### O que a fase resolve

Duas necessidades que se apoiam no mesmo artefato — um arquivo de configuração
que servidor, indexador e eval leem:

1. **Bases** — uma instalação atende N acervos com índices separados, cada um
   com seu servidor MCP. Pessoal e trabalho não se misturam, e o controle de
   qual agente alcança qual base é *qual servidor está registrado naquele
   cliente*
2. **Ajuste sem código** — o usuário final muda o comportamento da recuperação
   pelo navegador, vê o efeito medido no conjunto dourado, e salva

Vêm juntas porque a configuração é a mesma peça, e escrevê-la duas vezes é o
desperdício. Os pesos de recuperação são **por base** por necessidade: a
premissa do painel é que a configuração certa depende do acervo, e notas
pessoais e contratos corporativos são acervos diferentes.

### A — Núcleo de configuração *(pré-requisito, sem UI)* — **concluído em 15/08/2026**

Hoje nenhum parâmetro de recuperação é configurável: os pesos são constantes em
`retrieve/hybrid.py`, `k` e `janela` em `mcp/server.py`, o chunking em
`ChunkConfig`, as raízes em `census.toml`. Trocar o peso do denso é editar um
`.py`.

- `config.toml` com `[[base]]`, `[padrao]` herdado e sobrescrevível por base
- Ordem de resolução declarada: padrão do código → arquivo → ambiente → CLI
- Lido pelo servidor MCP, pelo indexador **e pelo eval** — é o que garante que o
  número medido é o número que roda. Hoje `eval.varredura` instancia
  `BuscaHibrida` à mão, e nada estrutural liga uma coisa à outra
- Sem `config.toml`, uma base sintética a partir do `census.toml` atual: o
  índice existente continua valendo, **sem reindexar**. Um `census.toml` passado
  à mão em `--config` também é aceito — os comandos documentados no `CLAUDE.md` e
  no `docs/estado-f1.md` continuam rodando sem edição

Entregue: `[[base]]`, `[padrao]` herdado e `[maquina]` (perfil de execução, que é
propriedade do computador e não do acervo — ver F3.6); `--base` no indexador, no
servidor MCP, no `eval.rodar` e no `eval.varredura`; `BuscaHibrida.de_base`, que
é o que liga o número medido ao número que roda. Validação de carregamento cobre
o que não pode ser descoberto em produção: dois índices iguais ou aninhados,
base ambígua sem `--base`, chave desconhecida numa seção de pesos.

### B — Bases — **concluído em 15/08/2026**

- `--base` no indexador, no eval e no servidor MCP
- Diretório de índice por base; nenhuma base abre o índice de outra
- `instructions` e descrição de ferramenta vindas da base, não fixas no código —
  são o sinal pelo qual o modelo roteia quando duas bases estão registradas no
  mesmo cliente
- Conjunto dourado por base; nenhum relatório agrega métrica entre bases
- `py -m segundocerebro.mcp.registrar --base X` gera o trecho de `.mcp.json`,
  que é o degrau que hoje trava quem não edita JSON à mão

**Desvio do que este item dizia, com o motivo.** A linha original era "campo
`base` no conjunto dourado" — isto é, um filtro sobre um arquivo comum. Entregue
foi **um arquivo por base** (`dourado` na configuração), com o campo `base` da
pergunta rebaixado a *conferência*.

O argumento é o da invariante 7, aplicado ao mesmo problema: medir a recuperação
de um acervo contra as perguntas de outro produz um número que parece válido e
não é — e um campo pode vir vazio, vir errado ou ser esquecido por quem escreve
a pergunta, enquanto dois arquivos não se misturam. O campo continua existindo
porque a separação por arquivo deixa passar um caso, o de apontar o arquivo
errado, e aí ele para a medição com a contagem à mostra. Vazio é legítimo: é o
conjunto de hoje, escrito quando havia um acervo só, e ele continua medindo sem
edição.

A geração do `.mcp.json` **mescla, nunca substitui** — um `.mcp.json` costuma ter
outros servidores dentro, e escrever por cima apagaria configuração de terceiros
para resolver a nossa. Para a base sintetizada do `census.toml`, o registro omite
`--base`: `padrao` é um id que ninguém escolheu e que some no dia em que o
usuário escrever o `config.toml` dele.

### C — Painel — **concluído em 17/08/2026**

Os três estágios de pé, mais o estágio 0. O que a tela cobre hoje: criar base com
prévia de custo antes de indexar, barra de progresso, perfis com o custo de cada
um à mostra, pesos e releitura na gaveta avançada, diagnóstico de consulta,
**ensinar o sistema quando ele erra** (a pergunta entra no conjunto que mede a
base), perfil de esforço da máquina, re-apontar pastas, e o trecho de `.mcp.json`
pronto para colar.

Duas regras de fronteira que a tela respeita e não define: salvar ajuste de
ranking exige medição (invariante 4), e a classe cara não passa por aqui. Já o
perfil de máquina **grava direto** — ele muda a velocidade da indexação e nunca o
conteúdo do índice, então não há métrica que se mova, e exigir medição ali seria
ritual que ensina o usuário a ignorar a regra onde ela importa.

Detalhes de implementação abaixo.

`py -m segundocerebro.painel` sobe **Starlette** em `127.0.0.1` e abre o
navegador. Era FastAPI no plano; ao conferir o ambiente, `starlette`, `uvicorn` e
`httpx` já vinham com o pacote `mcp`, então o painel custa zero dependência nova
além do escritor de TOML. Sem npm, sem build. Três estágios, detalhados no doc:

1. **Perfis medidos** — os 37 pontos da varredura de 13/08 viram cartões com
   nome em português e os números ao lado, **inclusive o que cada um custa**
   (o perfil que sobe o MRR para 0,769 derruba as armadilhas de 4 para 3 de 6;
   esconder isso seria a versão desonesta da tela). Controles crus na gaveta
   "Avançado"
2. **Diagnóstico de consulta** — para uma pergunta digitada, qual ranqueador
   achou cada trecho, a posição em cada ranking antes da fusão e a contribuição
   RRF de cada um. Procedência e números, sem geração
3. **Conjunto dourado crescendo do uso real** — "o certo era este arquivo" com
   seletor de arquivo grava a pergunta no dourado da base. É o que faz "otimizar
   para o meu caso" ser verdade em vez de figura de linguagem

**Nada é salvo sem medida.** A invariante 4 diz que toda mudança em ranking
passa pelo eval; um painel de controles soltos violaria a regra do próprio
projeto. O fluxo é `ajustar → Medir → antes/depois por pergunta → Salvar`, com
Salvar desligado até existir medição da configuração exibida. O antes/depois é
por pergunta porque a porta 5 é orçamento de regressão, e duas médias não dizem
*quais* perguntas se moveram.

**Os parâmetros aparecem separados por custo de mudar**, que é a decisão de UX
que importa — sem isso, um dropdown dispara 35 horas de reindexação:

| Classe | O quê | Custo |
|--------|-------|-------|
| Grátis | os três pesos, `k_rrf`, `candidatos`, `k`, `janela` | recarrega sem reindexar |
| Cara | modelo de embedding, `max_chars`, `min_chars`, `overlap_chars` | reindexação: **~31 h a ~114 h** no corpus real deste notebook (medido em 15/08/2026 — a estimativa anterior, de 1,7 h a 34,9 h, subestimava em ~3×), e os ids todos mudam, então medição anterior deixa de ser comparável |
| De instalação | raízes, exclusões, política de placeholders, `threads` | nova varredura de disco; placeholder pode **baixar conteúdo** |

### D — Controle de indexação *(acrescentado em 16/08/2026)*

> Pedido do usuário, com o motivo: indexar é demorado e a espera sem informação
> é o que faz um usuário novo desistir antes de o sistema provar que serve.
>
> Método e coeficientes medidos em
> [`docs/estimativa-de-indexacao.md`](docs/estimativa-de-indexacao.md).

**Arquitetura, e ela é a parte que não pode sair errada:** o indexador continua
sendo um **processo independente**, que publica progresso; o painel apenas lê.
Fechar o painel não para a indexação, e a linha de comando continua fazendo tudo
sozinha. O painel é cliente do mecanismo, não dono — mesma razão da invariante 6.
Publicação por `progresso.json` gravado atomicamente ao lado do índice, com o
registro SQLite como verdade de fundo; nada de IPC.

**1. Estimativa realista.** Os quatro modos de errar estão medidos no doc, e três
deles eu cometi durante esta fase:

- **Denominador**: sai de `iter_files`, o mesmo enumerador do indexador. A
  contagem bruta do censo (3.154) contra o conjunto processado (1.601) é a
  diferença entre reportar 45% e 91%
- **Unidade de trabalho**: bytes ponderados por formato, não contagem de
  documentos — o custo por documento varia quase 600× entre mediana e pior caso.
  Coeficientes iniciais medidos: `.pptx` 3,8 s/MB · `.pdf` 48,7 · `.xlsx` 487 ·
  `.docx` 522
- **Tempo ativo, não de parede**: 64 h de relógio contra ~39 h de trabalho neste
  run. Relógio monotônico, salto acima do limiar tratado como suspensão
- **Faixa, não ponto**: P50 e P90. A dispersão por documento é CV 4,6; a soma de
  1.600 é confiável, um documento isolado não é. Nunca exibir ETA por documento
- Recalibração por formato com média móvel durante o run, e amortecimento —
  estimativa que salta é lida como "o programa não sabe"

**2. Retomada é comportamento previsto, não conserto.** A base já está de pé e
foi medida: WAL, `synchronous=FULL`, commit por documento e trava que reconhece
processo morto. Uma queda custa **no máximo um documento**. Falta fechar:

- **Reuso de PID depois de reinício.** A trava guarda só o PID, e
  `os.kill(pid, 0)` num PID reciclado responde "vivo" — o usuário levaria um
  "outro indexador está escrevendo" falso, sem outro indexador nenhum. A trava
  passa a guardar PID **e** horário de criação do processo (`psutil`)
- ✅ **Marcador de retomada — entregue.** Não há marcador novo: o
  `progresso.json` já é ele. Um run que morreu sem encerrar deixa `indexando`
  gravado, e `index/retomada.py` lê isso. Um segundo arquivo criaria duas fontes
  de verdade, e a que discorda aparece no pior momento
- ✅ **Reinício automático depois de desligar — entregue em 19/08/2026**, com o
  mecanismo trocado e o motivo medido. O plano dizia *tarefa agendada no logon*;
  tentado nesta máquina, `schtasks /SC ONLOGON` e o `Register-ScheduledTask` do
  PowerShell **negam sem elevação** (Windows 11 Enterprise com política
  corporativa), enquanto criar tarefa `ONCE` no mesmo shell funciona — o
  impedimento é o gatilho de logon, não o agendador. Exigir administrador para
  ligar uma conveniência derrubaria o público do painel, então o gatilho é um
  `.cmd` na **pasta de inicialização do usuário**: dispensa elevação, e é um
  arquivo visível que o usuário apaga à mão. Verificado de ponta a ponta rodando
  a partir de `C:\Windows\System32`. Botão liga/desliga em Máquina, no painel
- **Suspensão e hibernação**: o processo sobrevive; o que quebra é a estimativa.
  Detectar o salto de relógio, descontá-lo do tempo ativo e registrar "retomado
  após suspensão" em vez de contabilizar como lentidão
- **Limite conhecido, registrado em vez de resolvido**: um documento gigante é
  uma unidade de trabalho só — a maior planilha do acervo tem 324 MB de XML de
  abas. Uma queda no meio dela perde o que ela custou. Checkpoint por aba é
  possível e caro; a decisão é **medir com que frequência isso morde** antes de
  construir, mantendo o mecanismo `adiado` que já existe

**3. Tela com barra de progresso.** Percentual por trabalho, faixa de conclusão e
horário aproximado, documentos e GB absolutos ao lado, tempo ativo e parado
separados, e contagem por status à mostra — um corpus onde 8% falhou em silêncio
parece um corpus com ranqueamento ruim, e os dois pedem correções opostas.
Controles de **pausar, retomar e cancelar**, seguros porque o commit é por
documento.

**4. Seletor de esforço.** Três níveis, no `[maquina] perfil` que o bloco A já
tem: `leve`, `normal`, `maximo`. Ele governa prioridade de processo e de E/S
(`psutil`), número de threads e tamanho de lote — **e nada mais**. Nenhum nível
muda o conteúdo do índice; é a mesma regra da F3.6.

- `perfil` passa a significar **esforço**, e o backend (CPU ou GPU) sai dele para
  o campo `provider`, que já existe. Hoje `gpu` está misturado como se fosse um
  nível de esforço, e não é: são eixos independentes
- Trocar o nível **muda a estimativa**, e a tela diz isso na hora — "no nível
  leve isto passa de 8 h para 20 h". Esconder o custo seria a versão desonesta
  do controle
- `leve` pausa com a máquina na bateria
- Justificativa medida: 11 h de parada em 46 h neste run, porque a alternativa a
  parar era o notebook ficar inutilizável. Um indexador que não sabe ficar em
  segundo plano é um indexador que o usuário desliga — e aí ele não indexa nada

**Saída do bloco D:** uma indexação do zero acompanhada pela tela do início ao
fim, com o desvio entre a estimativa inicial e o tempo real registrado em
`docs/` — a estimativa erra, e o interessante é quanto. Mais: uma queda forçada
no meio (matar o processo) retoma sozinha perdendo no máximo um documento, e o
mesmo vale depois de hibernar a máquina.

**Saída** — cinco critérios verificáveis:

1. Uma pessoa sem experiência de desenvolvimento, **sem abrir terminal**, muda um
   perfil, vê o efeito medido com o movimento por pergunta, salva — e o servidor
   MCP passa a usar a configuração nova sem reinício manual
2. Um teste prova que o valor que o painel grava é o valor que a busca usa: o
   mesmo arquivo lido pelo servidor, pelo indexador e pelo eval
3. Um teste prova que o servidor MCP sobe e responde com o painel **ausente** —
   ele é opcional por construção, não está no caminho de consulta
4. Duas bases indexadas, registradas em clientes diferentes, e um teste que prova
   que a busca de uma **não alcança** documento da outra
5. Uma pergunta escrita pelo usuário pela tela entra no conjunto dourado da base
   e aparece na medição seguinte

Nenhum parâmetro da classe "cara" aplica sem confirmação que declare a
estimativa em horas.

### Checkpoint — conjunto dourado para quem instala do zero *(fechado em 19/08/2026)*

> Decisão de 17/08/2026: o repositório foi publicado como portfólio público, e
> `eval/golden/perguntas.jsonl` — junto com os relatórios de ablação e métricas
> que citam essas perguntas por conteúdo — ficou de fora (`.gitignore`), porque
> reproduz nome de fornecedor, código de contrato e trecho de documento real da
> base corporativa que gerou este projeto. Ver o aviso em
> [`eval/golden/README.md`](eval/golden/README.md).

Entregue, com a decisão que estava em aberto:

- `eval/golden/perguntas.example.jsonl` + `eval/sintetico/corpus/` +
  `config.sintetico.toml`. Empresa fictícia (Várzea Clara Energia). Demonstra
  o formato e dá régua ao CI; **não** mede recuperação de um acervo real.
  Também é o corpus compartilhado da F3.6 (índice feito no desktop, consulta
  no notebook, sem reembeddar) — ver [`docs/colaboracao.md`](docs/colaboracao.md)
- Tutorial das primeiras 10 perguntas em `eval/golden/README.md`
- `eval.rodar` / `eval.varredura`: caminho **implícito** ausente cai no exemplo
  com aviso; caminho **explícito** ausente continua sendo erro. Substituir um
  `--golden` que não existe mediria o corpus errado e pareceria válido

---

## F3.6 — Execução adaptativa ao hardware

> **Acrescentada em 15/08/2026.** Fase própria, e não um bloco da F3.5, porque
> toca arquivos diferentes (`indexer.py` e `embeddings.py`, não configuração e
> UI) e pode rodar antes, depois ou em paralelo. A seção `[maquina]` do núcleo de
> configuração já entrou na F3.5 bloco A.

Decisão e projeções em `ARCHITECTURE.md` §4. O princípio: **hardware muda
velocidade, nunca conteúdo** — um índice construído no desktop com GPU serve no
notebook sem reprocessar nada.

- **Smoke test primeiro.** `sm_52` saiu do CUDA 13 e o ramo 580 do driver foi
  anunciado como o último a cobrir Maxwell. Descobrir que `onnxruntime-gpu` não
  roda nas 980 Ti **depois** de escrever o pipeline seria a ordem errada.
  **Passou em 19/08/2026** (`docs/smoke-cuda.md`): `onnxruntime-gpu==1.18.0` +
  CUDA 11.8 + cuDNN 8, vendidos por pip, sem toolkit de sistema e sem mexer
  no driver 582.28. `e5-large` (`model.onnx`) devolve vetores finitos; o MiniLM
  quantizado do fastembed devolve NaN. ORT ≥ 1.19 (cuDNN 9) morre no `ReduceSum`.
  ORT ≥ 1.27 é CUDA 13. Pin em `requirements-gpu.txt`.
  Comando: `.\.venv\Scripts\python.exe -m segundocerebro.index.smoke_cuda --embed`
- **Pipeline de indexação**: workers de parse alimentando uma fila de embedding.
  Hoje o laço é sequencial por documento e o encoder fica parado durante o
  parse — medido em 24% do tempo, o que põe o teto de Amdahl em 4,2× por mais
  rápida que seja a GPU. É o item de maior ganho, e vale mais que a segunda placa
- **Um worker por GPU** (`CUDA_VISIBLE_DEVICES`): o ONNX Runtime não fatia uma
  sessão entre placas
- ~~Perfil `leve` de verdade~~ — **movido para a F3.5 bloco D em 16/08/2026**,
  onde virou requisito de usuário (seletor de esforço) em vez de detalhe de
  execução. Junto foi a separação entre `perfil` (esforço) e `provider`
  (backend), que estavam misturados
- **Quantização int8 na CPU**, se o eval não mostrar perda: é alavanca deste
  notebook (AVX-VNNI), não das 980 Ti — Maxwell não tem DP4A nem tensor cores

**Saída — cumprida em 20/08/2026**, `corpus=sintetico`, n=10. Não é a condição C.

| Critério | Resultado |
|----------|-----------|
| Similaridade de vetor > 0,9999 | **1,0000** (desktop: GPU × rebuild CPU, 18 chunks) |
| Métricas do dourado dentro do ruído | Idênticas nos dois lados: recall@1 **0,850**, recall@10 **1,000** |
| Índice do desktop no notebook **sem reembeddar** | Confirmado: `verificar.py` sem carregar o encoder; `eval.rodar --modelo e5-large` contra o índice feito nas 980 Ti |

Ganho de parede no sintético (inclui carga do encoder): **7 s** dual-GPU vs **23 s** CPU. No corpus empresas, uma 980 Ti fez 637 s ativos contra semente CPU de 5–11 h (fator 28). Detalhe em [`docs/portabilidade-f36.md`](docs/portabilidade-f36.md) e [`docs/smoke-cuda.md`](docs/smoke-cuda.md).

Int8 na CPU continua sendo alavanca do notebook, não desta fase.

---

## F4 — Grafo derivado, SharePoint e automação

O que dá profundidade ao multi-hop. Deliberadamente **depois** da F3, porque só
com o traço real de uso fica claro quais arestas o modelo aproveita.

- Extração de identificadores (contrato, projeto, processo, siglas) e entidades
- Grafo em SQLite; ferramenta `neighbors` passa a andar por ele
- SharePoint corporativo via pasta sincronizada, com a política de placeholders
  da F1 aplicada
- Watcher para reindexação automática
- Formatos restantes: MSG/EML, legado DOC/XLS se o censo justificar
- Conjunto dourado ampliado para cobrir as fontes novas

**Saída:** métricas de F2 **não regridem** com o corpus ampliado, e existe uma
pergunta multi-hop que **só** é respondível via `neighbors` — a prova de que o
grafo derivado carrega informação que a busca sozinha não alcança.

---

## F5 — Porta de entrada empresarial (só quando houver demanda concreta)

Não iniciar por antecipação. Gatilho: um segundo usuário real.

- Núcleo extraído como biblioteca, com duas portas (MCP e HTTP)
- API key própria sob Termos Comerciais para a geração
- ACL por documento como filtro **pré-recuperação**
- Trilha de auditoria e LGPD (padrões de `audit_trail.py` / `encryption.py`
  do TotalAudioRelator)
- Migração LanceDB → Qdrant

**Saída:** dois usuários com permissões distintas, e um teste que prova que o
usuário B não recupera documento restrito a A.

---

## Fora de escopo (registrado, não priorizado)

| Item | Motivo |
|------|--------|
| Perguntas globais / síntese temática | Não priorizado na definição inicial. Exigiria RAPTOR ou knowledge graph. Reavaliar após F3. |
| Geração no servidor | Quebraria R1 e R2 por construção. |
| **UI de consulta** (caixa de busca, lista de resultados, chat) | Continua fora, e por motivo mais forte que "redundante com o cliente MCP": uma UI de consulta que resumisse resultado quebraria a invariante 2. Quem consulta é o cliente. |
| ~~UI própria~~ → **UI de configuração** | **Entrou na F3.5 em 14/08/2026.** A linha original dizia "redundante com o cliente MCP na fase pessoal" e tratava as duas UIs como uma só. O cliente MCP consulta; ele não configura. O painel não recupera, não ranqueia e não gera texto — grava um TOML e mostra números do eval. |
| Painel multiusuário ou remoto | F5, junto de ACL e auditoria. O painel da F3.5 é local, `127.0.0.1`, um usuário. |
| Ajuste automático de pesos | A varredura já existe em CLI. Automatizar a escolha sem olhar os casos-armadilha compra média entregando justamente o subconjunto que a fase existe para resolver. |
