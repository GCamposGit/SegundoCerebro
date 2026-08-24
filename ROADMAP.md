# Roadmap — Segundo Cérebro RAG

Cada fase tem **critério de saída verificável**. Nenhuma fase *nova* começa
antes da anterior passar no seu critério. O que **resta** de uma fase aberta
entra em **pacotes** (ver abaixo): um PR, um dono, lista de paths fechada.
Indexação de horas não é pacote e **não bloqueia** o próximo PR — parser com
versão alcança o que já está no disco na passada seguinte.

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

## Pacotes — avançar enquanto a indexação corre

> **Acrescentado em 24/08/2026.** Duas máquinas, indexações de horas e uma suíte
> que trava se os dois mexem no mesmo arquivo. Fases F0–F3.6 estão fechadas; o
> que sobra não é “esperar a barra”. É um PR por vez **por path**, em paralelo
> entre os dois lados.

**Regra de um pacote**

| Campo | Valor |
|-------|--------|
| Dono | desktop **ou** notebook, nunca os dois |
| Paths | lista fechada no PR; o outro lado não toca |
| Saída | teste na suíte padrão (`tests/` + `eval/`, sem GPU, sem `perguntas.jsonl`) |
| Indexação | o indexador segue no fundo. Código novo vale na **próxima** passada |
| Schema / painel / `ROADMAP.md` | um de cada vez, como já era (`docs/colaboracao.md` §1) |

Dois pacotes só voam juntos se as listas de path **não se intersectam**.
`ingest/parsers/__init__.py` (despachante) é o mesmo contrato de `mcp/server.py`.

**Fila agora**, atualizada em 24/08/2026 pelo notebook. A passada OLE na base
privada do desktop **não** trava nenhum destes:

| # | Pacote | Dono | Onda | Começa já? |
|---|--------|------|:---:|------------|
| F4-M | `[base.exclude.papel]` + `Meetings/` por papel | notebook | — | ✅ **fechado** (PR #10) |
| R9.1 + C5.b | Perfis sintéticos: **gerador + seed + manifesto**, corpus nunca commitado | **desktop** | **1** | **sim, agora** |
| C5.a | Porta de custo do MIRACL: smoke de throughput → `docs/custo-miracl.md` | **desktop** | **1** | **sim, agora** |
| F6-A / R8.1 | `pip install` sem `PYTHONPATH=src`; matriz 3×SO no CI | **desktop** | **1** | **sim, agora** |
| C4.5 | Fatia cross-lingual no harness (`mesma-língua` vs `cross-lingual`) | notebook | **1** | **sim, agora** |
| R9.3 | Porta de latência, sobre índice inflado | notebook define, **desktop infla o índice** | **1** | **sim, agora** |
| C1 | Política de particionamento + description gerada do censo | acordo; texto no `ARCHITECTURE.md` | **1** | **sim** — combinar quem escreve |
| C6 | Família de versões ≠ grupo de formatos (**subordina R1.3**) | notebook (ranking) + desktop (hash/MinHash no censo) | 2 | depois da onda 1 |
| F4-P + C3.a | Peso da coluna `caminho` no bm25 **e** peso por tipo de fonte | notebook | 2 | depois de R9.1 |
| R6.1 | Autotune: peso por base, fábrica vira prior | notebook | 2 | depois de R9.1 |
| C7.a · C7.d | Fórmula sem cache (recálculo LibreOffice) · rota do CSV | **desktop** | 3 | **sim** — não depende da onda 1 |
| R1.4 · R5.2 · R3.2 | Quarentena · orçamento de recursos · dois passes | **desktop** | 3 | **sim** — nenhum depende da onda 1 |
| R4.1 · R3.3 | ANN · quantização INT8 | desktop | 4 | depois da porta de latência |
| R3.1 + C4.1 + R2.1 | Modelo (com fatia cross-lingual) + contexto no chunk — **um rebuild só** | desktop roda, notebook mede | 5 | depois da régua multi-perfil |
| C7.b · C7.c | Cartão de modelo de planilha; número é payload no modelo | desktop | 5 | — |
| C2 + C3.b–d | Glossário automático do corpus + reescrita lexical (mesmo ponto de código) | desktop extrai, notebook mede | 6 | — |
| F4-L / R1.1 | OLE que mente + conversor de legado | desktop | 6 | **sim** — não bloqueia nada |
| F4-O / R1.2 | OCR de PDF digitalizado | a combinar (despachante) | 6 | **sim** |
| F4-W / R5.1 | Watcher, com camada USN Journal | desktop | 6 | **sim** |
| F4-S | SharePoint = pasta sincronizada, só política e tela | notebook | 6 | **sim** |
| R6.2+C4.2 · R7.1 · R7.2+C6.a · R6.3 | Rerank v2 · tools · descriptions · tempo/pasta | notebook | 7 | — |
| F6-B / R8.2 | Primeira base sem terminal, MCPB, com a UX de C1 | quem não estiver no painel | 8 | depois de F6-A |
| F4-D | Cobertura do dourado real | notebook | — | **reescopado**: piso de regressão e limitação declarada, não fila de perguntas |
| R1.3 | Dedup e near-dup | — | — | **absorvido por C6** |
| F5 | Segundo usuário, ACL | ninguém | — | gatilho: segundo usuário real |

Os pacotes `R*` são de [`docs/dossie-melhorias.md`](docs/dossie-melhorias.md); a
especificação de cada um mora lá, e as premissas conferidas estão na seção
seguinte.

---

## O dossiê de melhorias, conferido contra o índice real

> **Acrescentado em 24/08/2026 pelo notebook.** `docs/dossie-melhorias.md` é uma
> avaliação externa do repositório com 30 pacotes `R<seção>.<n>`. A
> **especificação de cada pacote mora lá e não é repetida aqui** — repetir lista
> longa em dois arquivos já envelheceu duas vezes neste projeto (a §6 de
> `docs/colaboracao.md` conta a história). O que o `ROADMAP.md` assume é o que
> ele já era dono: **ordem, dono, porta de saída** — e as premissas que a
> medição mudou.

O dossiê foi lido contra o acervo corporativo em 24/08/2026, índice com **2.156
documentos e 98.326 trechos**. Sete premissas foram conferidas; **quatro batem,
três não**, e duas delas mudam prioridade.

| Premissa do dossiê | Medido aqui | Efeito |
|---|---|---|
| "corpus dev: 434 docs / 11.208 chunks" | **2.156 / 98.326** | O ponto de partida da extrapolação é 8× maior. A direção (1000×) continua de pé |
| "10–30% dos PDFs são imagem" | **5,6%** — 37 de 665 | `R1.2` (OCR) segue P0 **pelo produto**, não por volume local. O ganho aqui é de 3 perguntas do dourado |
| "`pyproject.toml` declara `dependencies = []`" | ✅ verdade | `R8.1` confirmado como pré-requisito |
| "busca vetorial é flat (exata)" | ✅ verdade — nenhum `create_index` no `store.py` | `R4.1` confirmado |
| "`.pytest_cache/` versionado" | ❌ **falso** — está no `.gitignore:7` e `git ls-files` não o lista | Item 1 da §10 do dossiê sai |
| "escritas pelo usuário: o subconjunto mais fraco, recall@1 0,500" | ❌ **é o mais forte: 0,667**, acima do rascunho (0,538) | A motivação de `R2.1` muda: o fraco é `multihop` (0,250) |
| "perguntas temporais: recall@1 0,500" | ❌ **0,714**, e 1,000 em recall@3/@5/@10 — o melhor tipo | `R6.3` cai de P1 para P2: filtro de tempo é bom para acervo de décadas, mas não resolve fraqueza medida |

### A dependência que o dossiê não podia ver

Cinco pacotes do dossiê pedem "número no dourado real": `R2.1` (contexto no
chunk), `R3.1` (ablação de modelo), `R6.1` (autotune), `R6.2` (rerank v2) e
`R6.3` (tempo/pasta). **O dourado cobre 25% do índice** — 63 das 74 fontes numa
única pasta de topo, de 30 (ver [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md)).

Medir qualquer um deles hoje é medir um quarto do acervo e chamar de decisão. Por
isso **`F4-D` entra na onda 1**, à frente de tudo que ela destrava. É a correção
mais importante que a medição faz na §12 do dossiê.

### As portas de latência, com linha de base medida

`R9.3` propõe portas sem baseline. Medido em 24/08/2026, 25 consultas do dourado,
índice de 98.326 trechos, CPU de 15 W:

| | p50 | p95 |
|---|---:|---:|
| `search` sem reranking | **1.145 ms** | **1.418 ms** |
| `search` com reranking (10 candidatos) | 8.019 ms | 9.538 ms |

Duas consequências. A porta proposta de **300 ms sem rerank** está **4,7× à
frente do que a máquina faz hoje**, num índice **50× menor** que o alvo — o que
confirma `R4.1`/`R3.3` como P0 e dá o número que eles têm de bater. E a meta de
**"rerank de 30 candidatos em <500 ms em CPU de 4 núcleos"** de `R6.2` está a
**19× de distância com 10 candidatos**: não é alcançável com cross-encoder em
CPU, e o pacote precisa escolher entre GPU (a rota da F3.6) ou outra classe de
reranqueador. Registrado para não virar promessa.

### O que o dossiê chama de novo e já existe aqui

- **`R1.3`, metade "dedup exato"**: já feito. O `sha256` marca `duplicado` sem
  reembeddar — **156 documentos** hoje, 7,2% do índice. O que falta é a outra
  metade: near-dup e **política de ranking por família**.
- **`R1.3`, metade "família"**: encontra o achado de
  [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md) — as renderizações de
  reunião são o caso real, e a medição já matou a regra ingênua: escolher a irmã
  por nome erra, porque 4 de 11 perguntas só são respondíveis pela renderização
  **menor**. O mecanismo é colapsar irmãs no ranking. Os dois viram um pacote só.
- **`R6.1` (autotune)**: o dossiê o justifica por acervos *diferentes*. A medição
  daqui é mais forte — o peso já está errado **dentro de um acervo só**:
  desligar o ranqueador de nome sobe o MRR das perguntas de reunião em 60% e
  piora o resto. Isso é `F4-P`, que sobe de onda por causa disso.
- **`R5.1` (watcher USN)**: é o `F4-W`, com uma camada a mais que vale a pena.
- **`R8.1`**: é o `F6-A`. **`R8.2`**: é o `F6-B`, ampliado para MCPB.
- **`R1.1`/`R1.2`**: são `F4-L` e `F4-O`, com solução proposta.

### A decisão que reordena tudo: não escolher peso global de acervo nenhum

**24/08/2026, decisão do usuário.** O problema que a medição encontrou — o dourado
real cobre 25% do índice — tem duas respostas possíveis, e a errada é a óbvia.

A óbvia é **escrever mais perguntas para este acervo**. Ela conserta a cobertura e
não conserta o viés: o resultado continua sendo um número desta máquina, deste
corpus, com nome de arquivo excepcionalmente informativo. O alvo do produto é
acervo genérico em máquina desconhecida.

A resposta adotada é **parar de escolher peso global a partir de qualquer acervo
único**. Isso muda o papel de três pacotes:

- **`R6.1` (autotune) deixa de ser "a feature que mata o overfitting" e passa a
  ser a arquitetura de ranking.** Os pesos de fábrica viram *prior*; cada base
  ajusta os seus com perguntas geradas do próprio acervo. Se o peso é por base, a
  cobertura do dourado de **um** acervo deixa de ser o gargalo que era.
- **`R9.1` (dourados sintéticos multi-perfil) vira o instrumento principal**, não
  um item de onda 7. É o que prova generalização: perfis com características
  opostas — nome informativo contra `Scan_001.pdf`, planilha pesada contra texto
  corrido, versões plantadas contra documento único.
- **`R9.2` (benchmark público) sai de "registrado e não feito" para a onda 1.**
  O argumento do dossiê é o certo e ficou mais forte: nenhum dos dois setups
  *possui* esse número. É o único árbitro que não pertence a ninguém.

**O que não muda, e é regra escrita:** número do sintético e de benchmark público
**não substituem a condição C** (`docs/colaboracao.md` §4, regra 7). O que muda é
o que o dourado corporativo decide. Ele deixa de ser a autoridade que escolhe peso
global e passa a ser duas coisas mais honestas:

1. **Piso de regressão** deste acervo — 62 perguntas, recall@1 0,551, que nenhuma
   mudança pode derrubar sem justificativa.
2. **Um perfil entre N** que o autotune tem de satisfazer, ao lado dos sintéticos.

**`F4-D` não morre; muda de forma.** Deixa de ser "escrever perguntas até cobrir o
acervo" e passa a ser: declarar a cobertura como limitação conhecida em todo
relatório que a use, e manter as 62 como piso. As 11 de reunião continuam valendo
pelo que mediram — recall@1 0,091 e `exato` 0,000 são o sinal que originou o peso
por tipo de fonte, e esse sinal não depende de haver mais perguntas.

### Ordem revisada

| Onda | Pacotes | Por que aqui |
|---|---|---|
| **1** | `R9.1` (dourados multi-perfil) · `R9.2` (benchmark público) · `R9.3` (porta de latência, com a baseline acima) · `R8.1`/`F6-A` (empacotamento) | **Instrumento antes de conclusão.** Nenhum destes decide ranking; os três primeiros são a régua que as ondas seguintes vão usar, e o quarto não depende de nada |
| **2** | `R6.1` (autotune, peso por base) · `R1.3`+`F4-P` (família por ranking e peso por tipo de fonte) | O ranking deixa de ter número global. Medido nos multi-perfil **e** no dourado corporativo, que vira piso |
| **3** | `R1.4` (quarentena) · `R5.2` (orçamento de recursos) · `R3.2` (dois passes) | Sobreviver e ser útil em máquina desconhecida |
| **4** | `R4.1` (ANN) · `R3.3` (quantização INT8) | Escala, medida contra a porta da onda 1 |
| **5** | `R3.1` (ablação de modelo) + `R2.1` (contexto no chunk) | Um rebuild coordenado paga os dois — e agora com régua multi-perfil, não com um acervo só |
| **6** | `F4-L`/`R1.1` (legado) · `F4-O`/`R1.2` (OCR) · `F4-W`/`R5.1` (watcher) · `F4-S` (SharePoint) | As décadas de acervo |
| **7** | `R6.2` (rerank v2) · `R7.1`/`R7.2` (tools e descriptions) · `R6.3` (tempo/pasta, P2) | Precisão e agência |
| **8** | `R8.2`/`F6-B` (MCPB + wizard) | O produto |

Duas perguntas que a onda 1 tem de responder **antes** de escrever código, e que
o dossiê não dimensiona:

- **`R9.2` cabe nesta máquina?** O subconjunto PT do MIRACL tem corpus e conjunto
  de consultas próprios; indexá-lo aqui custa tempo de embedding que compete com
  o acervo real, e o índice dele não pode se misturar ao corporativo (invariante
  7 — base própria, diretório próprio). Medir o custo e declarar antes de adotar.
- **`R9.1` gera corpus ou gerador?** Versionar 4 perfis × ~80 documentos é peso no
  repositório; versionar **o gerador** e produzir o corpus na hora é o padrão que
  `eval/sintetico/` já segue. Manter o padrão.

`R4.3`, `R6.4` e a §11 do dossiê ficam **registrados e não feitos**, como
o próprio dossiê pede.

---

## O complemento C1–C7, conferido no código

> **Acrescentado em 24/08/2026 pelo notebook.**
> [`docs/dossie-complemento-update-devs.md`](dossie-complemento-update-devs.md)
> traz sete pacotes `C<n>` e, ao contrário do dossiê original, **lê o código**.
> Mesma regra de antes: a especificação mora lá, o `ROADMAP.md` assume ordem,
> dono e porta.

**Quatro afirmações de código foram conferidas e as quatro batem.** Isso é
incomum e muda o peso do documento:

| Afirmação | Conferido |
|---|---|
| `bm25(chunks_fts)` roda **sem pesos de coluna**, e as colunas são `texto, trilha, caminho` | ✅ `store.py:136` e `store.py:620` |
| `data_only=True` faz planilha nunca aberta pelo Excel vir com célula vazia | ✅ `sheets.py:377`; o aviso já existe em `sheets.py:420` |
| `.csv` está registrado no parser de **texto puro**, junto de `.txt` | ✅ `text.py:109` |
| `chave_de_familia` inclui a extensão, e `g045` é o motivo | ✅ `familias.py:77-86`, com o raciocínio na docstring |

**Duas correções de dimensionamento**, nenhuma fatal:

- **`C7.d` cita "o censo real tem 85 CSVs somando 492 MB".** Esse número vem de
  [`docs/estatisticas-arquivos-por-extensao.md`](estatisticas-arquivos-por-extensao.md),
  que é a varredura de **um disco inteiro** (224.850 arquivos, 642 GB) e não de
  uma base — o próprio `prioridade-de-indexacao.md` avisa isso. Lá são 85 CSVs e
  **216,90 MB**, não 492. No acervo corporativo, medido agora: **2 arquivos
  `.csv`/`.tsv`, ~0 MB**. A correção de rota continua certa — CSV no parser de
  texto perde o cabeçalho depois da primeira janela — mas o P0 dela não vem
  daqui. E `.tsv` **não é** extensão suportada hoje: o pacote a acrescenta.
- **`C1` cita "multi-hop, recall@1 0.200".** Hoje é **0,250** no escopo (6
  perguntas). Continua sendo o tipo mais fraco, que é o que o argumento precisa.

### O encaixe que vale mais que os dois documentos separados

`C3.a` descreve um mecanismo: o nome do arquivo pontua **duas vezes** — dentro do
bm25, pela coluna `caminho`, e de novo na fusão, pelo `RanqueadorDeNome` com peso
0,5. Em [`docs/dourado-cobertura.md`](dourado-cobertura.md) o notebook mediu o
**efeito**: desligar o ranqueador de nome sobe o MRR das perguntas de reunião em
60% e piora o resto.

São a mesma coisa vista dos dois lados, e nenhum dos dois documentos sabia do
outro. **A primeira coisa que `F4-P` deve varrer é o peso da coluna `caminho` no
bm25** — se a dupla contagem explica o efeito, a correção é mais barata e mais
geral que um peso por tipo de fonte.

### Subordinações que o complemento declara, e que valem

- **`C6` subordina `R1.3`.** Conferido: MinHash a 0,85 fundiria o que
  `familias.py` separa de propósito, e reintroduziria o `g045` por outra porta.
  Não implementar `R1.3` antes de `C6`.
- **`C5` condiciona `R9.2` e muda o empacotamento de `R9.1`.** É a resposta às
  duas perguntas que a onda 1 já tinha em aberto neste arquivo: MIRACL só
  amostrado, atrás de porta de custo, desktop-only, índice descartável — e o
  sintético versiona **gerador + seed + manifesto de hash do texto extraído**,
  nunca corpus.
- **`C4` altera `R3.1`, `R6.2` e `R9.1`.** A fatia cross-lingual é instrumento:
  sobe para a onda 1 junto de `R9.1`. O resto de `C4` viaja com os pacotes que
  ele altera.
- **`C7` casa com `R1.1`** — mesmo binário do LibreOffice serve conversão de
  legado e recálculo de fórmula.

### Ordem, com C1–C7 dentro

| Onda | Pacotes | Por que aqui |
|---|---|---|
| **1** | `R9.1`+`C5.b` (gerador, seed, manifesto) · `C4.5` (fatia cross-lingual no harness) · `R9.3` (porta de latência) · `C5.a` (porta de custo do MIRACL) · `R8.1`/`F6-A` (empacotamento) · `C1` (política de particionamento + description por censo) | **Instrumento e política antes de conclusão.** Nenhum decide ranking |
| **2** | `C6` (família de versões ≠ grupo de formatos) · `F4-P`+`C3.a` (peso da coluna `caminho` e peso por tipo de fonte) · `R6.1` (autotune) | O ranking deixa de ter número global — e `C6` vem antes de `R1.3` |
| **3** | `C7.a`+`C7.d` (fórmula sem cache, rota do CSV) · `R1.4` (quarentena) · `R5.2` (orçamento) · `R3.2` (dois passes) | Perda silenciosa de conteúdo e sobrevivência em máquina desconhecida |
| **4** | `R4.1` (ANN) · `R3.3` (quantização) | Escala, contra a porta da onda 1 |
| **5** | `R3.1`+`C4.1` (modelo, com fatia cross-lingual) · `R2.1` (contexto no chunk) · `C7.b`/`C7.c` (cartão de modelo) | Um rebuild coordenado paga os três primeiros |
| **6** | `C2`+`C3.b–d` (glossário automático e reescrita lexical, mesmo ponto de código) · `F4-L`/`R1.1` · `F4-O`/`R1.2` · `F4-W`/`R5.1` · `F4-S` | Vocabulário do corpus e as décadas de acervo |
| **7** | `R6.2`+`C4.2` (rerank v2, cross-lingual) · `R7.1`/`R7.2`+`C6.a` (tools, descriptions, `anteriores`) · `R6.3` | Precisão e agência |
| **8** | `R8.2`/`F6-B` (MCPB + wizard, com a UX de `C1`) | O produto |

`R4.3`, `R6.4`, `R1.3` (absorvido por `C6`) e as anti-recomendações consolidadas
da §11 do dossiê e do fim do complemento ficam **registrados e não feitos**.

### O que fica fora, e por quê

- **§10 item 1** (`.pytest_cache`): falso, ver tabela acima.
- **§10 item 6** (pre-commit que bloqueia nome real): já existe, e melhor —
  `tests/test_saneamento.py` roda na suíte e a lista de nomes **não** mora no
  repositório. Um pre-commit com a lista embutida seria o próprio vazamento.
- **§10 item 7** (ADRs): o `docs/colaboracao.md` já é a fonte única e está sendo
  seguido. Converter agora troca um arquivo que funciona por sete que ninguém
  lê. Reabrir quando existir um terceiro contribuidor — que é o gatilho que o
  próprio item nomeia.

---

## F4 — Grafo derivado, SharePoint e automação

O que dá profundidade ao multi-hop. Deliberadamente **depois** da F3, porque só
com o traço real de uso fica claro quais arestas o modelo aproveita.

> **Grafo e `neighbors` entregues em 20/08/2026** —
> [`docs/ablacao-f4-grafo.md`](docs/ablacao-f4-grafo.md). As duas metades do
> critério de saída estão cumpridas para esta parte: métricas da F2 **idênticas**
> (recall@1 0,667, MRR 0,787, nDCG@5 0,793) e o caso plano → norma respondível só
> pela aresta. MSG/EML e legado OLE **entraram**. Falta desta fase, em pacotes:
> F4-W (watcher), F4-S (SharePoint pasta sincronizada), F4-L (OLE que mente),
> F4-O (OCR) e F4-D (dourado que cubra o acervo). F4-M fechou em 24/08.
>
> **O "só" foi verificado, não presumido.** A norma não aparece em `search` com
> k=10, nem k=20, nem quando a consulta nomeia a norma. A razão é estrutural:
> `search` devolve trechos, e um documento sem texto extraível não tem trecho —
> nenhum ranqueador da pilha pode devolvê-lo, nem o de nome, que é construído
> sobre `paths_com_chunks()`. `neighbors` opera em nível de **documento**. O grafo
> não é ranking melhor: é **granularidade diferente**, cobrindo um ponto cego que
> nenhum peso alcançaria.
>
> **E há número.** `eval.rodar --com-grafo` compõe busca + um salto e mede: uma
> única pergunta muda em recall@10, a `g048`, de **0,50 para 1,00** — exigia todas
> as fontes e ficava travada porque a segunda era inalcançável. No conjunto
> completo, recall@10 0,840 → 0,850. Custo: duas perguntas descem de 5→8 e 8→10
> dentro do top-10, −0,018 de recall@5. Por isso o salto **não é padrão**: a troca
> é do cliente, que sabe se a pergunta dele precisa de duas fontes.
>
> Três decisões que valem para o resto da fase:
>
> **Passada separada do indexador.** O grafo é derivado do índice, não do disco:
> reconstruí-lo inteiro custa **30 s** contra 39 h de reindexação. Numa fase cujo
> trabalho é refinar regras de extração, isso é a diferença entre cinco iterações
> e nenhuma — e foram cinco. De brinde, o laço de `indexer.py` não foi tocado,
> que é dono do outro setup em `docs/colaboracao.md`.
>
> **Menção, não aresta.** Guardar as N² arestas entre documentos que citam o mesmo
> identificador envelheceria na primeira reindexação; a aresta é derivada por
> junção na consulta, como `familias.py` já fazia e pelo mesmo motivo.
>
> **Nome de arquivo é fonte de identificador.** O documento que a pergunta
> multi-hop precisa é um PDF digitalizado — 61 páginas, zero texto extraível. Só o
> nome o resgata, e daí saiu o desempate que decide a ordem: identificador no nome
> significa que o documento **é** o assunto; no corpo, que ele **fala sobre**.

- ✅ Extração de identificadores — norma, lei, código estruturado, CNPJ, processo.
  Entidade por NER ficou **fora**, com motivo: exigiria modelo no caminho de
  indexação, e a fonte de entidade que paga é o glossário que o usuário já
  constrói (medido na F2)
- ✅ Grafo em SQLite (tabela `mencoes`); ferramenta `neighbors` andando por ele,
  com o **motivo** de cada ligação e peso por raridade do identificador
- ✅ **MSG/EML** — 48 `.msg` e um `.pdf` com conteúdo MIME saíram de `sem_parser`.
  Ver [`docs/ablacao-f4-email.md`](docs/ablacao-f4-email.md)
- ✅ **Legado DOC/XLS/PPT/RTF** — parsers em bytes, sem COM (`ole_texto.py`,
  `xlrd`). Qualidade abaixo de OOXML, aceito. O que falta não é “ter parser”:
  é arquivo que **mente a extensão** (F4-L) e **número no dourado** (notebook).
- ✅ Fila em ondas, versão de parser, estimativa com intercepto por documento
- ✅ **Conjunto dourado ampliado** para email: `g001`, `g011` e `g033` perderam
  `fora_de_escopo: email`. Sobram exclusões `ocr` (F4-O)

O que **falta** da F4 virou pacote, não lista solta. Definição abaixo, depois da
saída e do orçamento do email.

**Saída:** métricas de F2 **não regridem** com o corpus ampliado, e existe uma
pergunta multi-hop que **só** é respondível via `neighbors` — a prova de que o
grafo derivado carrega informação que a busca sozinha não alcança.

> **A primeira metade do critério precisou ser lida como orçamento, em
> 21/08/2026** — ver [`docs/ablacao-f4-email.md`](docs/ablacao-f4-email.md). Com os
> 48 documentos de email dentro, as mesmas 45 perguntas medem recall@1 **0,644**
> contra 0,667, e três perguntas que mediam **zero** passam a medir **1,000 em
> recall@3**.
>
> Inspecionadas as duas que caíram, como a porta 5 da F1 exige: a `g045` perde o 1º
> lugar para um `.msg` da reunião diária da POC que ela cita — outro documento
> sobre o mesmo assunto, não resposta errada. A `g037` cai de ≤5º para 11º por
> causa de **três transcrições de reunião**, que não são email: entraram por
> acidente na primeira tentativa de indexação.
>
> Daí a leitura: "não regridem" ao pé da letra é exigência que nenhum corpus
> ampliado cumpre, porque documento novo e relevante compete. Como orçamento — no
> máximo três quedas do 1º lugar, cada uma inspecionada, que é como a F1 já
> escreveu a porta 5 — está cumprida com uma queda.
>
> **E o corpus ampliado é maior do que a fase supunha.** `iter_files` enumera 2.617
> documentos; o registro tinha 1.601. São **1.013 documentos nunca indexados**,
> 1.010 deles em `Meetings/` — transcrição de reunião. Toda métrica de F1 e F2 foi
> medida num corpus 39% menor que o disco. Nenhuma conclusão registrada muda (cada
> uma diz qual corpus mediu), mas indexar isso é o próximo número a decidir, e é
> decisão do usuário: custa horas.

### Pacotes que fecham a F4

Cada um é um PR. Saída da fase: F4-M medido no dourado + F4-W verde na suíte +
F4-S documentado no painel. **F4-M cumpriu a sua parte em 24/08** — e ao cumprir
mostrou que o dourado cobria 18% do índice, o que abriu a `F4-D`. F4-O (OCR) pode ficar para depois se o orçamento
da porta 5 continuar a tratar digitalizado como fora de escopo — mas o leigo
com scanner não espera.

#### F4-M — `Meetings/` por papel — **notebook** — ✅ FECHADO em 24/08/2026

> **Entregue no PR #10**, e com uma diferença que a medição impôs: não é
> `[base.excluir]` por padrão de nome, é **`[[base.exclude.papel]]` com escopo de
> pasta**. Glob solto casa pelo nome em qualquer lugar da raiz, e dois arquivos
> com a forma exata do relatório redundante moram fora da árvore de reuniões — um
> deles a única cópia do seu assunto. O glob o apagaria em silêncio.
>
> Medido: enumeração 2.619 → 2.156, `Meetings/` 1.014 → 551, baseline com
> métricas idênticas, índice e corpus enumerado **iguais** (2.156 dos dois lados).
> Recall@1 0,635 → **0,656** nas 48 perguntas de então. As três renderizações
> **ficaram** no índice: cortá-las por nome apagaria 15 reuniões.
>
> O que **não** foi cumprido é a cláusula do `eval/`, e ela virou pacote próprio:
> ver `F4-D`. Ver [`docs/ablacao-f4-meetings.md`](docs/ablacao-f4-meetings.md).

O levantamento está em [`docs/ablacao-f4-meetings.md`](docs/ablacao-f4-meetings.md).
Não continuar a passada pausada: o que estava em voo é andaime (`_context.txt`).

- **Toca:** schema de `config.py` (`[base.excluir]` por padrão de nome), filtro
  em `census.py` / `iter_files` (não no laço do indexador), `config.example.toml`,
  testes de config e de censo, `eval/` se o dourado ganhar pergunta de reunião
- **Não toca:** `index/indexer.py`, `index/embeddings.py`, `retrieve/*` (salvo
  se a medição pedir, e aí é outro PR), `ingest/parsers/*`
- **Saída:** andaime e PDF redundante de reunião **não entram** na enumeração;
  um teste com `tmp_path` prova o padrão; a passada corporativa de transcrições
  (não de `_context`) fecha com número no dourado
- **Paralelo à indexação do desktop:** sim. Schema é “um de cada vez”: enquanto
  este PR não mergear, o desktop **não** edita `config.py` nem `painel/*`

#### F4-D — Dourado que cubra o acervo — **notebook**

> **Aberto em 24/08/2026, por medição, não por plano.** Depois de `Meetings/`
> fechar, o índice tem 1.900 documentos alcançáveis em **30 pastas de topo**, e as
> 51 perguntas do dourado apontavam para 63 fontes **numa pasta só**: 18,2% de
> cobertura. As duas maiores pastas do acervo não podiam ganhar pergunta nenhuma —
> só competir como distrator. Isso torna qualquer crescimento de corpus
> negativo por construção, e foi o que se viu quando `Meetings/` entrou.
>
> Leitura completa, método e números em
> [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md).

- **Toca:** `eval/golden/perguntas.jsonl` (não versionado), `docs/` de dourado.
  Nada de código
- **Não toca:** `retrieve/*`, indexador, parsers, `config.py`
- **Feito:** 11 perguntas de reunião, fonte conferida renderização por
  renderização. Medem recall@1 **0,091** e recall@20 **1,000** — a resposta está
  sempre no top 20 e quase nunca no primeiro lugar. O grupo `exato` mede
  **0,000** em recall@1
- **Falta:** o lote do usuário na maior pasta do acervo (25,8% do índice, zero
  perguntas hoje), e uma multi-hop entre reunião e documento
- **Saída:** cobertura acima de metade do índice e um número por grupo de fonte,
  para a `F4-P` decidir peso com o corpus inteiro na mesa
- **Regra de método, para o número não medir o autor:** escolher o documento por
  enumeração antes de escrever a pergunta, ler o texto **já indexado**, conferir
  a fonte trecho por trecho, e só então rodar o eval

#### F4-L — OLE que mente — **desktop**

Parsers existem. O que a passada na base privada do desktop mostrou: `.xls` que é HTML ou está
criptografado, `.ppt` que não é OLE2, `xlrd` recusando codepage. Status vira
`erro` com detalhe; não volta a `sem_parser`.

- **Toca:** `ingest/parsers/sheets.py` (`.xls`), `ingest/parsers/ole_texto.py`,
  `ingest/parsers/slides.py` (`.ppt` se o conteúdo for OOXML disfarçado),
  testes em `tests/test_ingest.py` / fixture `tests/cfb.py`. **Sobe a versão do
  parser** se o texto extraído mudar
- **Não toca:** `mail.py`, despachante, `indexer.py`, `retrieve/*`, `config.py`
- **Saída:** HTML-como-xls e PPTX-como-ppt não derrubam a passada; teste com
  bytes sintéticos (VCE, sem arquivo real)
- **Paralelo:** sim. A passada em curso usa o parser velho; a próxima repesca
  por versão

#### F4-W — Watcher — **desktop**

Processo à parte. Não é o laço do indexador: observa a raiz e dispara
`indexer --prefixo` / documento único. Sem IPC novo — o contrato é o de
`comando.txt` + `progresso.json`.

- **Toca:** `src/segundocerebro/index/watcher.py` (**arquivo novo**),
  `tests/test_watcher.py`, `requirements.txt` (`watchdog`, hoje comentado),
  um atalho em `scripts/` se precisar. Opcional: uma linha no painel **só
  depois** de F4-M soltar o painel
- **Não toca:** laço de `indexer.py` (chama o módulo, não reescreve),
  `retrieve/*`, schema de `config.py`
- **Saída:** criar/alterar um `.txt` em `tmp_path` dispara indexação; placeholder
  de nuvem **não** é aberto; dois watchers no mesmo índice recusam pela trava
- **Paralelo:** sim. Não precisa do índice privado do desktop

#### F4-S — SharePoint via pasta sincronizada — **notebook** (depois de F4-M)

A política de placeholder já está no `reader.py` (F1). O que falta é o leigo
entender e o painel mostrar “arquivo só na nuvem”. Graph API continua F5.

- **Toca:** `painel/*` (depois de F4-M), docs de uso, talvez um status
  `placeholder` mais visível na barra
- **Não toca:** `indexer.py`, parsers
- **Saída:** a tela distingue placeholder de arquivo local; teste sem OneDrive
  real (atributo fabricado)

#### F4-O — OCR — **a combinar** (depois de F4-M)

Três perguntas do dourado ainda são `fora_de_escopo: ocr`. Parser novo = bump de
versão + despachante. Dois PRs se o OCR entrar no laço e no ranking.

- **Toca:** módulo novo em `ingest/parsers/`, uma linha no despachante, testes
  com PDF sintético digitalizado (não o acervo)
- **Não toca:** `retrieve/*` no mesmo PR
- **Saída:** um PDF sem camada de texto vira trechos; as três perguntas perdem
  a anotação `ocr` **só** com número antes/depois no corporativo

#### F4-P — Porta 3, o bm25 e o peso de nome por tipo de fonte — **notebook**

Só depois do lote de perguntas do usuário em `F4-D`. Ranking não muda sem número.

O escopo cresceu por medição em 24/08. Nas 11 perguntas de reunião, **desligar o
ranqueador de nome sobe o MRR 60%** (0,287 → 0,459) e o recall@1 três vezes
(0,091 → 0,273); no conjunto inteiro ele continua se pagando (recall@1 0,551
contra 0,534). Ou seja: o peso certo do nome provavelmente **não é um número só**,
é peso por tipo de fonte — no documento de escritório o identificador está no
nome, na transcrição o nome só tem assunto e data. `n = 11` é sinal, não decisão.

- **Toca:** `retrieve/*`, `eval/*`, pesos da base corporativa — **não** `[padrao]`
  sem o desktop saber
- **Não toca:** indexador, parsers
- **Braços a medir:** bm25 no padrão; peso de nome por tipo de fonte; família de
  renderização **colapsando irmãs no ranking** (não escolhendo por nome — a ordem
  de preferência por nome foi medida e está errada, ver `docs/dourado-cobertura.md`)
- **Saída:** decisão registrada, com armadilhas medidas e um número por grupo
  de fonte

---

## F6 — Primeiro uso em máquina desconhecida

> **Acrescentada em 24/08/2026.** Não é a F5: não há segundo usuário, ACL nem
> API paga. É o buraco entre “os dois setups usam o repo” e “um leigo instala
> numa pasta qualquer e pergunta”. Pode **correr em paralelo com a F4** — não
> precisa do dourado corporativo nem das 980 Ti.

**Saída da fase:** numa máquina Windows sem o nosso `config.toml`, em ≤ 30 min,
o usuário aponta uma pasta, espera a barra, liga um cliente MCP e recebe trecho
com arquivo + seção. Sem editar `PYTHONPATH`. Sem saber o que é `sm_52`.

### F6-A — Pacote pip — **desktop** (já)

Hoje `pyproject.toml` declara o pacote mas `dependencies = []` e o servidor
ainda pede `PYTHONPATH=src`. O leigo cai em `ModuleNotFoundError`, que o
cliente MCP mostra como “não conecta”.

- **Toca:** `pyproject.toml` (deps a partir de `requirements.txt`), scripts de
  entrada (`segundocerebro-painel`, `segundocerebro-indexar`),
  `requirements-gpu.txt` como extra `[gpu]`, teste de instalação em venv
  fresco **sem** `PYTHONPATH`
- **Não toca:** laço do indexador, `retrieve/*`, schema, painel
- **Saída:** `pip install -e .` e `segundocerebro-mcp --base sintetico` sobe
  do `C:\Windows\System32` como o teste do Claude Desktop já prova o bloco

### F6-B — Estágio 0 do painel, zero terminal — **depois do painel livre**

O painel já cria base e mostra custo. Falta o caminho único: pasta → indexar →
botão “ligar no Claude Desktop / Grok”.

- **Toca:** `painel/*` apenas
- **Não toca:** ranking, `indexer.py`
- **Saída:** um teste HTTP do estágio 0 que não exige GPU

### F6-C — Hardware: CPU padrão, CUDA opcional — **desktop**

- **Toca:** `index/smoke_cuda.py`, `index/esforco.py`, docs de F3.6, extra
  `[gpu]`. **Não** põe `cuda` em `model_id`
- **Não toca:** `retrieve/*`, chunking
- **Saída:** numa máquina sem NVIDIA a indexação é CPU e a suíte padrão passa;
  com GPU incompatível (CUDA 13, MiniLM-Q) o smoke recusa em português

### F6-D — Uma página em português — **qualquer lado, arquivo novo**

- **Toca:** `docs/comecar.md` (novo). Não reescrever `CLAUDE.md`
- **Saída:** instalar, apontar pasta, esperar barra, perguntar. Sem jargão de
  fase. O vocabulário de exemplo é a VCE

**Teste da fase, numa máquina que não é a nossa:** Windows sem NVIDIA, pasta
nova, corpus sintético, um cliente MCP. Enquanto isso não passou, não é
produto — é o laboratório dos dois setups.

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
