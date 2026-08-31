# Roadmap — Segundo Cérebro RAG

Cada fase tem **critério de saída verificável**. Nenhuma fase *nova* começa
antes da anterior passar no seu critério. O que **resta** de uma fase aberta
entra em **pacotes** (ver abaixo): um PR, um dono, lista de paths fechada.
Indexação de horas não é pacote e **não bloqueia** o próximo PR — parser com
versão alcança o que já está no disco na passada seguinte.

> **Precedência, desde 25/08/2026.** [`docs/regra-de-ouro.md`](docs/regra-de-ouro.md)
> vem antes de qualquer prioridade deste arquivo, dos dossiês e do guia de
> engenharia: **o produto é para um leigo apontando uma pasta que nunca vimos.**
> Consequências já aplicadas abaixo — a **F6 virou porta de fase** (não trilha
> paralela), a ordem passou a ser `E5` → `E1` → `F4-P`, a `F4-P` encolheu ao
> defeito, e o contrato de pacote ganhou `Hipótese`, `Efeito mínimo`, `Orçamento`
> e `Critério de encerramento`.

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
`docs/portas-f1-condicao-c.md`.

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
  `docs/ablacao-rerank.md`. recall@1 0,644 → **0,678**,
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
  `docs/ablacao-glossario.md`. Expande nos dois
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
  `docs/ablacao-familias.md`. Agrupa por pasta +
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

**Regra de um pacote** — quatro campos novos em 25/08/2026, das regras 10 a 12
da §4 de `docs/colaboracao.md`. Pacote que não os preenche **não começa**.

| Campo | Valor |
|-------|--------|
| Dono | desktop **ou** notebook, nunca os dois |
| Paths | lista fechada no PR; o outro lado não toca |
| **Serve base desconhecida** | que defeito isto conserta para quem instala amanhã. Se a resposta só existe em termos do nosso acervo, o pacote é **de laboratório** e fica atrás de qualquer item de produto |
| **Hipótese** | uma frase falsificável, escrita antes de medir |
| **Efeito mínimo** | fatia **e** valor declarados antes de olhar a tabela. Menor que o ruído medido da fatia ⇒ **não se mede**: registra-se a conta e encerra |
| **Orçamento** | uma medição por hipótese. Segunda passada precisa de instrumento novo ou acervo novo, não de outra grade |
| **Critério de encerramento** | empate no Δ pareado **encerra** o pacote, com "hipótese refutada" no doc. "Meça mais" não é critério |
| **Classe generalizada** | que classe de defeito ficou fechada, e qual teste ou método passa a pegá-la sozinho (regra 12). Sem esta linha o PR não fecha |
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
| ~~R9.1 + C5.b~~ | **Absorvido pelo `E1`** em 24/08/2026. O gerador passou a ser do **notebook** — ver a seção de pacotes E e [`docs/avaliacao-pacote-e1.md`](docs/avaliacao-pacote-e1.md) | notebook | 2 | **o desktop não pega este** |
| E5 | **IC bootstrap em toda métrica** — `Δ ± IC95`, teste pareado, regra de adoção | notebook | **1** | ✅ **fechado** — e achou que a **porta 5 não rodava**; ver [`docs/rigor-estatistico.md`](docs/rigor-estatistico.md) |
| E1 + E2 | Gerador sintético endurecido (7 condições do laudo) + matriz de armadilhas | notebook | **1** | ✅ **fechado em 25/08/2026** — `E1.a`–`f`, PRs #27, #28 e #29 |
| E3 | Protocolo de três camadas + test-set selado (`seed + caps`) | acordo | 3 | depois do `E1` |
| E4 | Red-team por fase, modelo DynaBench | notebook | 4 | no fecho da fase corrente |
| Q1 · Q2 | CI com lint/format/types/cov · `pyproject` como fonte única | qualquer | — | **sim** — eixo ortogonal, não decide ranking |
| C5.a | Porta de custo do MIRACL: smoke de throughput → `docs/custo-miracl.md` | **desktop** | **1** | ✅ **fechado** — MIRACL-PT não existe no dataset publicado; ver [`docs/custo-miracl.md`](docs/custo-miracl.md) |
| C5.c | Sucessor da camada 3: Quati amostrado, sem download → `docs/alarme-externo.md` | **desktop** | **1** | ✅ **fechado** — `quati-50k` adota (~1,1 h); 1M/mMARCO/MIRACL fora |
| F6-A / R8.1 | `pip install` sem `PYTHONPATH=src`; matriz 3×SO no CI | **desktop** | **1** | ✅ **fechado** (PR #14) |
| R8.1.b | `tests/test_pacote.py`: achar o script pelo `sysconfig`, e pular fora do CI em vez de falhar | notebook | 3 | sim — não bloqueia nada |
| C4.5 | Fatia cross-lingual no harness (`mesma-língua` vs `cross-lingual`) | notebook | **1** | ✅ **fechado** — ver [`docs/fatia-cross-lingual.md`](docs/fatia-cross-lingual.md) |
| R9.3 | Porta de latência, sobre índice inflado | notebook define, **desktop infla o índice** | **1** | ✅ **portas definidas** — ver [`docs/porta-de-latencia.md`](docs/porta-de-latencia.md); falta o índice inflado |
| C1 | Política de particionamento + description gerada do censo | acordo; texto no `ARCHITECTURE.md` | **1** | **sim** — combinar quem escreve |
| C6 | Família de versões ≠ grupo de formatos (**subordina R1.3**) | notebook (ranking) + desktop (hash/MinHash no censo) | 2 | depois da onda 1 |
| C3.a | Peso da coluna `caminho` no bm25 | notebook | 2 | ✅ **fechado, hipótese refutada** — ver [`docs/ablacao-c3a-pesos-fts.md`](docs/ablacao-c3a-pesos-fts.md) |
| F4-P.0 | O eval mede o caminho entregue (`buscar_chunks`), aditivo | notebook | 2 | ✅ **fechado** — ver [`docs/ablacao-caminho-entregue.md`](docs/ablacao-caminho-entregue.md) |
| F4-P | **Reconciliar os dois caminhos** — encolhido ao **defeito** em 25/08: aceite binário, sem varredura de peso | notebook | 2 | ✅ **fechado, aceite cumprido** — ver [`docs/ablacao-f4p-nome-no-entregue.md`](docs/ablacao-f4p-nome-no-entregue.md) |
| R6.1 | Autotune: peso por base, fábrica vira prior | notebook | 2 | mecanismo já; critério de generalização espera o `E1` (era `R9.1`) |
| C7.a · C7.d | Fórmula sem cache (recálculo LibreOffice) · rota do CSV | **desktop** | 3 | C7.d ✅ PR #34; C7.a ✅ PR #35 |
| R1.4 · R5.2 · R3.2 | Quarentena · orçamento de recursos · dois passes | **desktop** | 3 | ✅ **fechado** PR #36 |
| R4.1 · R3.3 | ANN · quantização INT8 | desktop | 4 | depois da porta de latência |
| R3.1 + C4.1 + R2.1 | Modelo (com fatia cross-lingual) + contexto no chunk — **um rebuild só** | desktop roda, notebook mede | 5 | depois da régua multi-perfil |
| C7.b · C7.c | Cartão de modelo de planilha; número é payload no modelo | desktop | 5 | — |
| C2 + C3.b–d | Glossário automático do corpus + reescrita lexical (mesmo ponto de código) | desktop extrai, notebook mede | 6 | — |
| F4-L / R1.1 | OLE que mente + conversor de legado | desktop | 6 | F4-L (mente) + R1.1 ✅ PR #37 |
| F4-O / R1.2 | OCR de PDF digitalizado | **desktop** + notebook (O.3) | 6 | **O.0 ✅** PR #38 · **O.1 neste PR** · O.2/O.3 em [`docs/plano-ocr.md`](docs/plano-ocr.md) |
| F4-T | Parser de transcrição (`.vtt`/`.srt`/`.sbv`) — a saída nativa de todo gravador de reunião era contada e não indexada | notebook | 6 | ✅ **fechado em 27/08/2026**: fatia `reunião` de **0 para 100** perguntas alcançáveis, 17 → 20 extensões. [`docs/fatia-reuniao-invisivel.md`](docs/fatia-reuniao-invisivel.md) |
| F4-O.3 | Dourado de OCR no acervo | notebook | 6 | **bloqueada em 28/08/2026** — não pelo dourado nem pelo motor: a passada com `--ocr` quarentena o acervo a 61 s por documento, com 0% de CPU. Laudo: [`docs/ocr-no-acervo-bloqueado.md`](docs/ocr-no-acervo-bloqueado.md) |
| F4-R | Regime de máquina: a indexação varia 22× por estado do SO que o produto não observa | notebook (`esforco.py` emprestado) | 6 | **R.1 sim** — achar o gatilho. Laudo: [`docs/afinidade-e-estado-de-maquina.md`](docs/afinidade-e-estado-de-maquina.md) |
| F4-W / R5.1 | Watcher, com camada USN Journal | desktop | 6 | **sim** |
| F4-S | SharePoint = pasta sincronizada, só política e tela | notebook | 6 | **sim** |
| R6.2+C4.2 · R7.1 · R7.2+C6.a · R6.3 | Rerank v2 · tools · descriptions · tempo/pasta | notebook | 7 | — |
| F6-B / R8.2 | Primeira base sem terminal, MCPB, com a UX de C1 | quem não estiver no painel | 8 | depois de F6-A |
| **J.b1** | `doc_id` público por conteúdo, índice em `documentos.sha256`, URI `sc://`, regra de preferência entre os **223 caminhos duplicados** | notebook | **1** | **sim** — a coluna já existe, não espera o store |
| **J.c-mapa** | `outline` + `list_folder`, servidos do registro (`chunks.trilha`/`locator`/`ordinal` + `documentos` + `quarentena`) | notebook | **1** | **sim** — nasce em `mcp/leitura.py`, não em `server.py` |
| **J.a · J.f** | Parse Store canônico + indexador lendo dele (rebuild ≥80% mais barato) | desktop, **ou notebook se o crédito não voltar** | **1** | **sim, e antes da onda 5** — é ela que paga o store |
| **J.b2 · J.c-conteúdo** | Sidecar com offsets + `get_document` paginado por cursor | notebook | 2 | depois do `J.a` — **não** sai dos chunks (+11,1% de sobreposição) |
| **J.d** | `pack_folder` manifest-first, corte em fronteira de documento | notebook | 3 | depois do `J.c`; depende de `familias.py`, **não** de `R1.3` |
| **J.e** | Exportador de vault Markdown (Obsidian) como *view* one-way | qualquer | 4 | depois do `J.b2`; menções e glossário já existem |
| F4-D | Cobertura do dourado real | notebook | — | **reescopado**: piso de regressão e limitação declarada, não fila de perguntas. **Instrumento fechado em 29/08/2026** — `eval/cobertura.py`; a cobertura entra em todo relatório e a omissão virou impossível. Medido: alcance **38,5%**, fontes **3,3%**. [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md) |
| F4-D.2 | **`dourado-v1` é frase, não mecanismo** — nada congela quais ids compõem a série histórica, e o conjunto é gitignorado: pergunta editada move a linha de base sem deixar diff | notebook | — | **aberto em 29/08/2026**, achado ao fechar a `F4-D` |
| R1.3 | Dedup e near-dup | — | — | **absorvido por C6** |
| F5 | Segundo usuário, ACL | ninguém | — | gatilho: segundo usuário real |

Os pacotes `R*` são de [`docs/dossie-melhorias.md`](docs/dossie-melhorias.md); a
especificação de cada um mora lá, e as premissas conferidas estão na seção
seguinte. Os pacotes `J*` entraram em 30/08/2026 e são de
[`docs/pacote-j-camada-acesso-corpus.md`](docs/pacote-j-camada-acesso-corpus.md),
com a conferência contra o código em
[`docs/plano-pacote-j.md`](docs/plano-pacote-j.md) — **ler a conferência antes da
especificação**: cinco premissas dela não batem com esta base, e o `J.b`
original virou dois subpacotes com dependências diferentes.

**`R8.1.b` — o teste de pacote falha onde devia pular, e procura no lugar errado.**
Levantado na revisão do [PR #14](https://github.com/GCamposGit/SegundoCerebro/pull/14)
em 24/08/2026, não pedido como mudança naquele PR. **São dois defeitos e a ordem
importa**, porque medir no notebook depois do merge mostrou que só o segundo era
conhecido:

1. **`_script()` procura no diretório errado no Windows fora de venv.** Ele usa
   `Path(sys.executable).parent`, e o `pip` instala console script em
   `sysconfig.get_path("scripts")` — que num venv é o mesmo diretório do
   interpretador, e numa instalação base do Windows é `…\Python312\Scripts`, um
   nível abaixo. Medido nesta máquina depois de `pip install -e .`: os quatro
   `.exe` existem, `segundocerebro-mcp.exe --help` roda de `C:\Windows\System32`
   sem `PYTHONPATH` e devolve 0 — e dois testes continuam vermelhos. O CI passa
   porque roda em venv, o que faz o acerto ser coincidência de layout.
2. **Falhar em vez de pular quando o pacote não está instalado.** Todo outro teste
   dependente de ambiente aqui pula: `test_golden` sem `perguntas.jsonl`,
   `test_saneamento` sem a lista, os markers `modelo` e `cuda`. O efeito é
   `pytest` vermelho em máquina que ainda não migrou. O contra-argumento é bom e
   fica registrado: pular esconderia um passo de instalação quebrado no CI. O
   meio-termo é `skipif(not instalado and not os.environ.get("CI"))`.

**Consertar o 1 antes do 2**, senão o `skipif` do 2 mascara o 1: a máquina teria o
pacote instalado e funcionando, o teste pularia para sempre, e ninguém veria que a
busca pelo script nunca esteve certa fora de venv.

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
`R6.3` (tempo/pasta). **O dourado alcança de 3,3% a 38,5% do índice** — piso
exato (só as fontes esperadas, 63 de 1.900) e teto generoso (a pasta inteira de
cada pergunta, 732 de 1.900), medidos pelo instrumento do `F4-D` em 30/08/2026
com 62 perguntas. A leitura honesta fica entre os dois. As 51 perguntas de
24/08 mediam 18,2% pelo teto (ver [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md));
o "25%" que circulava aqui não era nenhum dos dois.

Medir qualquer um deles hoje é medir um quarto do acervo e chamar de decisão. Por
isso **`F4-D` entra na onda 1**, à frente de tudo que ela destrava. É a correção
mais importante que a medição faz na §12 do dossiê.

### A fatia cross-lingual, medida — `C4.5` fechado em 24/08/2026

O complemento chamava a falta de recorte bilíngue de "lacuna: regressão bilíngue
hoje passaria invisível". Medido: a lacuna escondia **uma queda de 47% em
recall@1**.

| Fatia | n | recall@1 | recall@5 | MRR@10 |
|---|---:|---:|---:|---:|
| mesma-língua | 44 | 0.625 | 0.852 | 0.750 |
| **cross-lingual** | **12** | **0.333** | **0.625** | **0.496** |

Razão em recall@5 **0.73**, contra o **0.80** que o próprio `C4.5` pede. O acervo
é 15% inglês (284 de 1.900 documentos com conteúdo) e um quinto do dourado cruza
idioma — não é caso de borda. E o perfil localiza o defeito: recall@20 é **1.000**
na fatia cross-lingual, então o documento certo é **alcançado e mal ordenado**,
que é o sintoma de ranqueador cego na fusão, não de busca que não encontra.

Três consequências para a fila, e nenhuma delas muda ranking hoje:

- `R3.1` e `R6.2` deixam de poder ser decididos pela média. `eval.ablacao_f2`
  passou a emitir MRR mesma-língua e cross-lingual lado a lado.
- `F4-P` (onda 2) herda a pergunta de qual ranqueador paga a conta — dois dos
  três votos da fusão (bm25 e nome) são cegos a idioma por construção.
- `R9.1` ganha contrato: o perfil bilíngue **tem** de emitir `idioma` e
  `idioma_fonte` no dourado gerado. Sem eles a fatia sai de tamanho zero e o
  relatório parece aprovado. Formato em `eval/golden/README.md`.

### As portas de latência — `R9.3` fechado em 24/08/2026

O instrumento é `eval/latencia.py`, as portas moram em
`eval/portas-latencia.toml` e o raciocínio inteiro em
[`docs/porta-de-latencia.md`](docs/porta-de-latencia.md). Falta só o índice
inflado de 1M trechos, que é do desktop.

**São duas portas, e essa é a primeira correção que a medição faz na proposta.**
Uma porta que a máquina reprova no dia em que é escrita não guarda nada — fica
vermelha para sempre e ninguém repara quando piora. Então: `produto` é o alvo
hardware-neutro, hoje reprovado, que `R4.1` e `R3.3` têm de alcançar; `regressão`
é o que **cada máquina nomeada** faz hoje, mais margem, e é a única que falha.

Medido na condição C, índice de 98.326 trechos, braço isolado, CPU de 15 W:

| Operação | p50 | p95 | porta de produto | distância |
|---|---:|---:|---:|---:|
| `search` | 1.363 – 2.506 ms | **1.840 – 2.877 ms** | 300 ms | **6,1× a 9,6×** |
| `search+rerank` (10 cand.) | 10.119 ms | **11.331 ms** | 800 ms | **14,2×** |
| `read_note` | 0,3 – 0,4 ms | 0,9 – 2,8 ms | 100 ms | passa por 36× |
| `neighbors` | 0,2 ms | 1,6 – 2,1 ms | 100 ms | passa por 48× |

**Todo o orçamento de latência é `search`** — os outros dois passam por mais de
uma ordem de grandeza em qualquer regime.

Três coisas que a medição mudou, e que valem além deste pacote:

- **A faixa é o estado térmico, não ruído.** Cinco passadas do mesmo código no
  mesmo índice deram p95 entre 1.840 e 2.877 ms — **1,6×** — conforme o notebook
  estivesse descansado ou saturado. Isto **reconcilia a linha de base de 1.145 ms
  que este arquivo registrava**: ela não estava errada, estava sem protocolo, e
  por isso não era reproduzível. É o problema de `R9.3` demonstrado no próprio
  número do projeto.
- **Um braço por passada.** Medir `search` e `search+rerank` no mesmo laço dava
  4.394 ms para o braço barato contra 2.713 ms sozinho — 53%, porque o
  cross-encoder satura o pacote térmico. O número contaminado é plausível, então
  passaria.
- **`R6.2` tem meta impossível, e agora dá para dizer por quê.** Reranquear custa
  **~761 ms por par** neste CPU. Os "30 candidatos em <500 ms" do pacote são
  ~22,8 s, **46× a meta** — não é ajuste, é a classe do modelo. `R6.2` escolhe
  entre GPU (F3.6) ou outro reranqueador.

`overview` **não entra** nas portas: o dossiê lhe dá 200 ms e ele não existe (é
`R7.1`, onda 7). Porta de ferramenta ausente mede zero e reporta aprovado.

A próxima medição que falta é a **decomposição de `search`** — quanto é encoder,
quanto é varredura densa, quanto é bm25 e nome. Sem ela, "ANN resolve" é
hipótese. É a primeira coisa que `R4.1` deve medir.

E uma limitação declarada em vez de escondida: **a porta não roda no CI.** Lá não
há acervo, índice nem encoder. Ela é local e manual, antes de fundir mudança de
ranking. Automatizá-la depende do índice sintético inflado, que é do desktop.

### A dupla contagem do nome — `C3.a` fechado em 24/08/2026

Leitura em [`docs/ablacao-c3a-pesos-fts.md`](docs/ablacao-c3a-pesos-fts.md);
grade, referência, porta e regra em `eval/varredura_fts.py`, declaradas antes de
rodar com a conclusão negativa junto. 18 braços em 4 minutos, condição C.

**Pela regra declarada, nada passa: nenhuma configuração muda.** Mas o resultado
não é um "não" — é que **os dois critérios vivos do projeto discordam sobre o mesmo
peso**, e isso só ficou visível porque a onda 1 construiu o recorte cross-lingual
antes.

O `C3.a` estava certo sobre o **mecanismo** e errado sobre o **efeito**. Nada do
que `docs/dourado-cobertura.md` mediu vem da coluna do bm25:

| eixo | amplitude do MRR das 11 perguntas de reunião |
|---|---:|
| `caminho` de 0 a 1,0 | 0,005 a 0,012 |
| `nome` (fusão) de 0 a 0,5 | **0,172** |

**14× mais sensível ao ranqueador da fusão que à coluna do bm25.** Em MRR e
recall@1 a coluna `caminho` se paga: zerá-la custa até 0,062 de MRR e 6,8 pontos
de recall@1. A hipótese está refutada nesses dois eixos.

Cinco coisas que valem além do pacote:

- **O ranqueador de nome é uma ponte entre idiomas, e ninguém tinha visto.** MRR
  cross-lingual cai monotonicamente com o peso do nome: 0,496 → 0,475 → 0,461. O
  nome do arquivo é sinal **agnóstico a idioma** — identificador, código, data e
  nome próprio casam igual em PT e EN, enquanto o bm25 não casa `contrato` com
  `agreement`. Dos três votos, o nome é uma das duas pontes que existem.
  **Isto retira a recomendação de `nome = 0,25`**, que sobe agregado (+0,004),
  nDCG@5 (+0,013) e reunião (+0,122) e derruba a ponte em 0,021 — a média esconde,
  a fatia mostra.
- **Ótimo reconfirmado por razão diferente é resultado.** O 0,5 saiu da varredura
  de 13/08, num dourado **sem nenhuma pergunta de reunião**; rederivar era
  obrigatório (**quando a régua cresce, o ótimo anterior não se herda**) e deu 0,5
  outra vez, agora por dois motivos — escritório **e** ponte PT↔EN.
- **A coluna `caminho` troca recall@1 por recall@5**, e isso não estava na
  hipótese. Com `nome` 0,5: `caminho` 0,3 tem o **maior recall@5 da grade**
  (0,847 contra 0,797), `recall@10` **idêntico** nos três, e recall@1 0,517 contra
  0,551. Não se ganha documento, reordena-se dentro do top-10. É decisão de
  produto — o primeiro resultado ou os cinco primeiros — e é de `F4-P`.
- **`fts_caminho = 0,3` é a coisa mais barata já medida a mexer o critério
  cross-lingual:** razão de 0,73 para 0,79 com as **duas** fatias subindo (r@5
  cross 0,625 → 0,708, mesma 0,852 → 0,898), custo zero por consulta. As rotas
  previstas para essa lacuna eram `R3.1` (rebuild) e `R6.2`/`C4.2` (6,9× de
  latência). **É uma pergunta de doze** — pista, e o lugar de confirmar é o perfil
  bilíngue de `R9.1`.
- **O critério de aceite de `C4.5` é satisfazível piorando o denominador.** Dois
  braços desta grade com recall@5 cross-lingual idêntico (0,708): o de fatia
  mesma-língua **pior** (0,875) marca razão 0,81 e passa; o melhor nas duas (0,898)
  marca 0,79 e reprova. O recorte está certo, a forma do critério não — precisa de
  piso absoluto ao lado da razão.

E o que `F4-P` herda de concreto: **a referência já é o ótimo do escritório** (MRR
0,761, o maior da grade), então toda a folga do peso por tipo de fonte está na
reunião — teto de **+0,032** de MRR agregado (0,680 → 0,712). Teto de **oráculo**,
com n = 11, e **3 dessas 11 perguntas são cross-lingual**: baixar `nome` na reunião
tira a ponte de 27% do grupo que se quer melhorar, e o teto não desconta isso.

Sobre o instrumento: **recorte por tipo de fonte é derivável, idioma de fonte não
era.** O dourado já carrega `fontes`, então o grupo sai do caminho e não envelhece —
ao contrário de `idioma_fonte`, que exige o índice e por isso é anotação estática
(`C4.5`). A regra derivada errou na primeira versão por prefixo de ordenação de
pasta (`09. `, `10 - `, `260722_`): **14 dos 36 segmentos** do dourado real têm um,
e ela media 10 reuniões onde já se sabia que eram 11. Corrigida, reproduz
`dourado-cobertura.md` em quatro números com três decimais.


### O eval media o que o cliente não executa — `F4-P.0`, 24/08/2026

Leitura em
[`docs/ablacao-caminho-entregue.md`](docs/ablacao-caminho-entregue.md).
Instrumento em `eval/entregue.py`, ligado por `--entregue`, **aditivo**: `search`
segue sendo a série F0 → F4, porque trocar o recuperador canônico apagaria a
comparabilidade entre fases.

A ferramenta `search` do MCP chama `buscar_chunks` (`mcp/server.py:191`), onde o
`RanqueadorDeNome` **não participa** — ele pontua documentos e não há posição de
trecho honesta para dar a ele. Verificado no índice real, antes de escrever código:
mudar `peso_nome` de 0,5 para 0 **não altera nada** em `buscar_chunks` e altera a
ordem em `search` em todas as consultas. **O peso do nome é inerte em produção**, e
`painel/medir.py:79` herda a cegueira — o controle do painel não move o número que
o painel exige antes de salvar.

No agregado os dois medem parecido, e é por isso que ninguém tinha reparado:

| caminho | recall@1 | recall@5 | recall@10 | recall@20 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|
| `search` — a série | 0,551 | 0,797 | **0,907** | **0,955** | **0,680** | 0,682 |
| `buscar_chunks` — o entregue | 0,551 | **0,805** | 0,881 | 0,921 | 0,671 | **0,693** |

O recorte é que mostra, e ele corrige duas coisas:

- **O caminho entregue é 3× melhor em reunião** — recall@1 **0,273** contra 0,091,
  MRR **0,452** contra 0,287. Ele é, na prática, a configuração "sem ranqueador de
  nome" que `docs/dourado-cobertura.md` mediu, e ganha isso de graça.
- **E paga com a ponte PT↔EN.** O achado de manchete de `C4.5` — *"recall@20 é
  1.000 na fatia cross-lingual: o documento é alcançado e mal ordenado, não é busca
  que não encontra"* — **vale só em `search`**. No caminho entregue o recall@20
  cross-lingual é **0,750**: três das doze não são alcançadas no top-20. Para um
  quarto da fatia, no produto, é busca que não encontra. Corrigido em
  [`docs/fatia-cross-lingual.md`](docs/fatia-cross-lingual.md).

**Isto reescopa o `F4-P`** e invalida o teto de oráculo de +0,032, que foi
calculado sobre `search`. O pacote deixa de ser afinação de peso e passa a ser a
reconciliação: trazer o sinal de nome para o caminho de trecho **sem** deixá-lo
votar em documento de reunião. Alvo declarado: reunião ≥ 0,452 de MRR e
cross-lingual voltando a recall@20 = 1,000, sem perder o recall@1 de 0,551.

Duas lições que valem além do pacote:

- **Conferir qual caminho de código o produto executa vem antes de afinar peso
  nele.** Custou três consultas e veio antes da primeira linha do `F4-P` — que
  teria afinado um botão inerte contra um teto calculado no caminho errado.
- **O princípio já estava escrito e não tinha sido aplicado.**
  `docs/ablacao-familias.md` diz "ligado em `search` **e** em `buscar_chunks`, para
  o que se mede ser o que se entrega". Vale conferir isso para **todo** sinal, não
  só para o próximo — e a verificação é barata: variar o peso e ver se a saída
  muda.

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
real alcança um quinto do índice pelo teto por pasta, e 3,3% pelo piso exato —
tem duas respostas possíveis, e a errada é a óbvia.

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
relatório que a use, e manter as 62 como piso.

> **Cumprido em 29/08/2026 na metade da declaração.** `eval/cobertura.py` põe a
> limitação em todo relatório, medida a cada passada. A outra metade — "manter as
> 62 como piso" — segue sendo **frase, não mecanismo**: `dourado-v1` não existe
> como arquivo, nada congela quais ids compõem a série, e o conjunto é
> gitignorado, então uma pergunta editada muda a linha de base histórica sem
> deixar diff. Ver `F4-D.2`. As 11 de reunião continuam valendo
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
> [`docs/dossie-complemento-update-devs.md`](docs/dossie-complemento-update-devs.md)
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
  [`docs/estatisticas-arquivos-por-extensao.md`](docs/estatisticas-arquivos-por-extensao.md),
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
0,5. Em [`docs/dourado-cobertura.md`](docs/dourado-cobertura.md) o notebook mediu o
**efeito**: desligar o ranqueador de nome sobe o MRR das perguntas de reunião em
60% e piora o resto.

São a mesma coisa vista dos dois lados, e nenhum dos dois documentos sabia do
outro. **A primeira coisa que `F4-P` deve varrer é o peso da coluna `caminho` no
bm25** — se a dupla contagem explica o efeito, a correção é mais barata e mais
geral que um peso por tipo de fonte.

**Varrido em 24/08/2026, e a resposta é "depende do critério".** Em MRR e recall@1
o mecanismo é real e o efeito não é dele — o grupo de reunião é 14× mais sensível
ao peso do ranqueador de nome que à coluna `caminho`. No critério cross-lingual do
`C4.5`, `fts_caminho = 0,3` é a coisa mais barata já medida a mexê-lo. Ver
[`docs/ablacao-c3a-pesos-fts.md`](docs/ablacao-c3a-pesos-fts.md). Nada foi
aplicado, e `F4-P` ganhou um **teto de oráculo** de +0,032 de MRR agregado, com a
interseção medida: 3 das 11 perguntas de reunião são cross-lingual.

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
| **2** | ~~`C3.a`~~ (peso da coluna `caminho` — **fechado, refutado**) · `F4-P` (peso por tipo de fonte, teto medido de +0,020) · `C6` (família de versões ≠ grupo de formatos) · `R6.1` (autotune) | O ranking deixa de ter número global — e `C6` vem antes de `R1.3` |
| **3** | `C7.a`+`C7.d` (fórmula sem cache, rota do CSV) · `R1.4` (quarentena) · `R5.2` (orçamento) · `R3.2` (dois passes) | Perda silenciosa de conteúdo e sobrevivência em máquina desconhecida |
| **4** | `R4.1` (ANN) · `R3.3` (quantização) | Escala, contra a porta da onda 1 |
| **4½** | `J.a`+`J.f` (Parse Store e o indexador lendo dele) | **Acrescentado em 30/08.** Tem de vir **antes** da onda 5: é ela que paga rebuild, e sem o store paga o parse duas vezes |
| **5** | `R3.1`+`C4.1` (modelo, com fatia cross-lingual) · `R2.1` (contexto no chunk) · `C7.b`/`C7.c` (cartão de modelo) | Um rebuild coordenado paga os três primeiros |
| **6** | `C2`+`C3.b–d` (glossário automático e reescrita lexical, mesmo ponto de código) · `F4-L`/`R1.1` · `F4-O`/`R1.2` · `F4-W`/`R5.1` · `F4-S` | Vocabulário do corpus e as décadas de acervo |
| **7** | `R6.2`+`C4.2` (rerank v2, cross-lingual) · `R7.1`/`R7.2`+`C6.a` (tools, descriptions, `anteriores`) · `R6.3` · `J.d` (`pack_folder`) · `J.e` (export vault) | Precisão e agência |
| **8** | `R8.2`/`F6-B` (MCPB + wizard, com a UX de `C1`) | O produto |

`R4.3`, `R6.4`, `R1.3` (absorvido por `C6`) e as anti-recomendações consolidadas
da §11 do dossiê e do fim do complemento ficam **registrados e não feitos**.

**Onda 1 ganhou dois itens em 30/08/2026**, e é a única alteração que o pacote J
faz nesta tabela sem esperar nada: `J.b1` (o `doc_id` público) e `J.c-mapa`
(`outline` e `list_folder`). Os dois saem do registro que já existe — a
conferência que mostra isso é a seção *"O pacote J — camada de acesso ao corpus,
conferido no código"*, mais abaixo.

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

## A arquitetura de avaliação resiliente — pacotes E1–E6

> **Acrescentado em 24/08/2026.** Fonte:
> [`docs/relatorio-avaliacao-resiliente.md`](docs/relatorio-avaliacao-resiliente.md),
> que declara substituir `R9.1`/`R9.2` do dossiê e `C5` do complemento. O pacote
> de código que veio com ele foi **executado** antes de entrar no plano — o laudo
> é [`docs/avaliacao-pacote-e1.md`](docs/avaliacao-pacote-e1.md), e ele muda a
> ordem.

### O diagnóstico, que o repositório confirma

O relatório aponta duas coisas com nome na literatura de IR, e as duas têm
evidência aqui dentro:

- **Viés de coleção.** O dourado real foi escrito a partir de um acervo só, e
  `docs/ablacao-bm25-com-nome.md` já declarava o viés de origem das perguntas.
  Peso de fusão varrido nesse acervo é peso de *aquele* acervo — foi exatamente o
  que `docs/dourado-cobertura.md` concluiu em 24/08, por conta própria e antes do
  relatório existir.
- **Ruído maior que o ganho.** Com 45 perguntas no escopo, mover duas move
  recall@1 em 4,4 p.p. Vários ganhos já celebrados em ablação são dessa ordem —
  o reranking da F2 vale +0,011 de nDCG@5.

O que o relatório **não** propõe, e é o acerto: descartar o dourado real. Ele é
rebaixado de juiz único a camada de regressão, com a série F1→F2 intacta.

### As três camadas

| Camada | O que é | Papel |
|---|---|---|
| 1 | dourado real, congelado como `dourado-v1` | **regressão** — bloqueia merge, nunca decide arquitetura sozinho |
| 2 | sintético gerado por código, dev-set + test-set selado | **decisão** — cobre a matriz de armadilhas |
| 3 | benchmark externo amostrado (MIRACL-PT, `C5`) | **alarme** — nunca decide; detecta endogamia do gerador |

Regra de adoção que isto instala, e que vai para o `ARCHITECTURE.md` com o `E3`:
**feature entra se ganha na camada 2 na fatia que ela mira, sem regredir nenhuma
outra fatia além do ruído, e sem regredir a camada 1.**

### Os pacotes

| # | Pacote | Dono | Onda | Estado |
|---|---|---|:---:|---|
| E1 | Gerador de corpus sintético como código versionado | **notebook** (assumido em 24/08) | 2 | ✅ **fechado em 25/08/2026** — sete condições (`E1.a`–`c`) + revisão de completude (`E1.d`–`f`) |
| E2 | Matriz de armadilhas: fatia ↔ pacote do roadmap | notebook | 2 | ✅ **fechado junto do `E1.c`** — [`docs/matriz-de-armadilhas.md`](docs/matriz-de-armadilhas.md) v1.0, 12 fatias |
| E3 | Protocolo de três camadas + set selado | acordo entre setups | 3 | não começou |
| E4 | Loop adversarial por fase (red-team de agente) | notebook | 4 | não começou |
| E5 | **Rigor estatístico mínimo — IC bootstrap** | notebook | **1** | ✅ **fechado em 24/08/2026** — ver [`docs/rigor-estatistico.md`](docs/rigor-estatistico.md) |
| E6 | Preservação e uso honesto da base real | notebook | contínuo | parcialmente já feito |

`E1` absorve `R9.1`+`C5.b`; `E3` absorve `C5`; `E5` **altera o harness que todas
as ablações R/C pendentes usam**.

### O laudo do E1 muda a ordem, e o motivo é uma medição

O relatório manda instrumento antes de conclusão, e a leitura ingênua disso seria
`E1` antes de `F4-P`. **A execução do gerador desmente essa ordem.** Medido em
24/08 com `grupo_de_pergunta` de `eval/fonte.py` sobre as 260 perguntas que o
gerador produz:

```
grupo de fonte: {'escritório': 234, 'misto': 26}
fatia de idioma: {'não declarado': 260}
```

O alvo declarado da `F4-P` é o grupo `reunião`, e o corpus sintético **não tem
nenhuma pergunta de reunião nem de email** — nem `.msg`, nem `.eml`, nem `.vtt`,
nem pasta de transcrição. A fatia cross-lingual sai de tamanho zero porque
`idioma_fonte` nunca é emitido, que é o defeito contra o qual
`eval/golden/README.md` escreveu contrato no mesmo dia.

Rodar o `E1` antes da `F4-P` não protegeria a `F4-P` de nada. O que protege é o
intervalo de confiança sobre o dourado corporativo, que já é o piso declarado —
e ele é o `E5`, o item mais barato da lista inteira.

**Ordem adotada em 24/08: `E5` → `F4-P` → `E1` endurecido. Revista em 25/08 para
`E5` → `E1` → `F4-P`.**

O argumento de 24/08 estava certo sobre o instrumento e errado sobre o alvo: ele
supunha que a `F4-P` valia o lugar na frente. Sob a
[regra de ouro](docs/regra-de-ouro.md) ela não vale — o que ela persegue é **peso
de um acervo**, com teto de oráculo de +0,032 de MRR agregado e efeito concentrado
em 11 perguntas, que é a forma que o próprio `E5` mostrou ser indetectável. O `E1`
é a camada 2, a única que fala de base desconhecida, e por isso vai primeiro.

A `F4-P` **não morre e não regride**: fica com a metade que é defeito de produto —
o caminho que o cliente executa alcança menos que `search` na fatia cross-lingual
(recall@20 0,750 contra 1,000), e isso é busca que não encontra para um quarto da
fatia. Aceite binário, sem grade de pesos.

### O que o E1 tem de satisfazer para entrar — **fechado em 25/08/2026**

Sete condições, todas vindas do laudo, todas verificáveis. Entregues em três PRs,
com a leitura completa em
[`docs/matriz-de-armadilhas.md`](docs/matriz-de-armadilhas.md):

| PR | Condições | O número que mudou |
|---|---|---|
| `E1.a` | 1, 5, 6 | `n=27` e `n=30` travavam; agora `n=100` dá 2.112 docs · 1.000 perguntas |
| `E1.b` | 2, 7 | fatia cross-lingual de **0** para 30 em `n=30`; `armadilha_fatia` como 3º eixo |
| `E1.c` | 3, 4 | `grupo_de_fonte` ganha reunião e email, com **interseção** cross-lingual de 10 cada; PDF de 0,5% para 45,7% |

Três coisas que a execução mudou em relação ao laudo, e que valem mais que as
condições em si:

- **O achado 2 não era achado.** "A escala declarada não existe" era consequência
  do laço de siglas do achado 1: com o teto removido, a escala aparece sozinha.
- **A parede era `n = 27`, não `i = 26`.** Com `n = 26` o índice vai de 0 a 25 e a
  26ª chamada ainda acha sigla livre. A recomendação de `--n-por-fatia 26` do
  laudo estava certa; o número que a explicava era um a menos.
- **O produtor passou a não conseguir emitir código inválido.** `perg()` valida
  contra `harness.IDIOMAS_ACEITOS` na emissão. Produtor que não emite inválido é
  melhor que consumidor que rejeita depois — e é a diferença entre o defeito
  aparecer na hora e aparecer uma fase adiante.

O que **não** mudou, e é o limite declarado: métrica deste corpus **não é condição
C**. Ele é a camada 2; ganho que só aparece aqui é ganho deste gerador, e é para
isso que a camada 3 (`C5`) existe.

As sete condições, como o laudo as escreveu:

1. `--n-por-fatia 30` **termina** — o espaço de siglas tem 26 elementos e o
   gerador entra em laço infinito em `i = 26`. Teto explícito, erro em vez de
   laço, e um teste que roda no `n` do `E5` e não no `n` que passa.
2. Emitir `idioma` **e** `idioma_fonte` no vocabulário fechado do harness
   (`pt`/`en`/`misto`/`indefinido`). `pt->en` não é código de idioma.
3. Fatia de **reunião** e fatia de **email**, com a interseção cross-lingual: 3
   das 11 perguntas de reunião do dourado real cruzam idioma, e a fatia sintética
   tem de cruzar os dois eixos em vez de somá-los.
4. Distribuição de formato calibrada pelo censo (`E6.1`), não 80% `.txt` contra
   os 74% PDF+DOCX do acervo real.
5. O selo do `E3` é **seed + caps**: o hash do manifesto muda conforme
   `python-docx` esteja instalado, e hoje isso é indetectável sem ler `caps`.
6. Nenhuma lista de nome real em arquivo versionado — reusar
   `tests/test_saneamento.termos()`, que lê de fora do Git.
7. Adaptador para o formato do harness, com `armadilha_fatia` como **terceiro**
   eixo de recorte: `fatia` fica reservado ao idioma, para não reescrever `C4.5`.

### A revisão de completude — `E1.d`, `E1.e`, `E1.f` (25/08/2026)

> **Decisão do usuário, e ela corrige o critério, não a execução.** As sete
> condições do laudo eram a régua de um *sample*: elas diziam o que o pacote que
> chegou por zip precisava consertar. A pergunta certa é outra — **o que o produto
> tem de aguentar** — e por ela o corpus estava incompleto em três eixos.

| Pacote | Lacuna medida antes | Depois |
|---|---|---|
| `E1.d` formatos | 9 dos 17 parsers **nunca exercitados**, entre eles o `.msg` (3,5% do acervo real) | 20 extensões no corpus, `.xls` válido declarado fora |
| `E1.e` pasta hostil | 4 dos 9 `ParseStatus` **nunca ocorriam** | todos, com 3 lacunas declaradas e conferidas |
| `E1.f` ranking | 5 classes de defeito **documentadas neste repositório** sem nada que as medisse | 5 fatias novas, 651 perguntas no total |

O que os três têm em comum, e é o método: **a régua sai de um contrato que o
produto já declara** — `supported_extensions()`, `ParseStatus`, os módulos de
`retrieve/`. Cada um com tabela de lacunas declarada, e cada tabela com um segundo
teste que a impede de crescer por conveniência.

**Seis defeitos foram achados ao construir**, e cinco eram meus: o gerador não
usava caminho estendido (e por isso o corpus **não conseguia conter** a armadilha
de caminho longo), um laço `O(n²)` que não terminava, uma fixture hostil que só
armava conforme o comprimento da base, um teste que dependia de onde o pytest
guarda temporários, uma fatia caindo no grupo `reunião` por acidente, e a
distribuição de `.txt` indo de 0,4% a 8,3% por uma fatia que gravava formato fixo.
O sexto é geral e vale registrar: **`pathlib.rglob` e `os.walk` perdem em silêncio
o arquivo de caminho longo**, enquanto `census.iter_files` o acha — não é defeito
do produto, é de ferramenta de teste, e já estava no repositório.

### O que fica registrado e não feito

- **GAN / conjunto adaptativo contínuo.** O relatório já rejeita, e com o
  argumento certo: treinar gerador contra recuperador produz pergunta patológica
  sem valor de produto. O `E4` adota o modelo DynaBench — degraus versionados,
  com filtro de razoabilidade.
- **Substituir o dourado real.** Congelar, não trocar. É `E3.1` e é inegociável:
  trocar o recuperador canônico ou a régua canônica apaga a comparabilidade entre
  fases, que é a razão de o harness ter sido construído antes dos recuperadores.

---

## O guia de engenharia — pacotes Q1–Q19

> **Acrescentado em 24/08/2026.** Fonte:
> [`docs/guia-engenharia-5-estrelas.md`](docs/guia-engenharia-5-estrelas.md).
> Eixo **ortogonal** ao dos pacotes R/C/E: nenhum Q decide ranking, nenhum passa
> pelo invariante 4. Por isso não entram na fila de ondas acima — correm em
> paralelo, e o critério é "um sênior clonando o repo a frio consegue sozinho".

| # | Pacote | Dono | Prioridade |
|---|---|---|:---:|
| Q1 | CI ganha lint, format, types e coverage — **lint, tipos e cobertura entraram em 28/08; o `select` cresceu em 29/08** e os `noqa` inertes viraram o `Q18` | qualquer | **P0 · em curso** |
| Q2 | `pyproject` como fonte única: `dependencies = []` contradiz o `requirements.txt` | desktop (é `R8.1`) | **P0** |
| Q3 | Teto de tamanho de módulo — **o teto virou teste em 29/08** (`tests/test_tamanho_dos_modulos.py`) e o `indexer.py` caiu de 1.753 para 1.368; o que falta é o `Q16` | cada um no seu | **feito em parte** |
| Q4 | Política escrita de `except Exception` (os 34 `BLE001`) | desktop | P1 · **neste PR** |
| Q5 | **e2e do protocolo MCP** (**feito** em 25/08 — `tests/test_protocolo_mcp.py`) · property-based `consulta_fts`/`chave_de_familia` (P1) · smoke de mutação (P3) | notebook + desktop | **P0 feito / P1 / P3** |
| Q6 | template de PR (**feito** em 25/08 — é onde as regras 10 a 12 mordem) · `CONTRIBUTING`, `SECURITY`, `pip-audit` | qualquer | **P0 feito / P2** |
| Q7 | Tag e CHANGELOG por fase fechada | qualquer | **P3 · vitrine** |
| Q8 | `docs/README.md` com índice temático — **feito em 29/08**, linkando só o que o clone tem; o resto é o `Q19` | notebook | **feito** |
| Q9 | `docs/processo-ia.md`: o contrato de fronteira entre agentes como peça pública | acordo | **P3 · vitrine** |
| Q10 | Observabilidade local do servidor (SQLite, nunca remota) | notebook | P2 |
| Q11 | Config aceita chave desconhecida em silêncio — **fechado em 30/08/2026**, cinco níveis mais tipo errado, com a guarda derivada do modelo e do AST | notebook | **feito** |
| Q12 | Defaults escritos duas vezes — **fechado em 30/08/2026**; eram **sete**, não seis (o `index.html` tinha uma quarta cópia dos tetos) | qualquer | **feito** |
| Q13 | `pesos.fts_*` **documentado em 30/08**; o dialeto de `RootSpec` fica, e depende da costura de `census.py` (`Q16`) | notebook | **metade feita** |
| Q14 | Hook de teste vivo em produção — **fechado em 30/08/2026**: só vale sob `PYTEST_CURRENT_TEST`, e avisa | notebook (assumido) | **feito** |
| Q15 | OCR sumia em silêncio — **fechado em 30/08/2026**; resto declarado no `Q15.a` (status fica `vazio` depois da quarentena) | notebook (assumido) | **feito** |
| Q16 | O que falta decompor, com as costuras levantadas (continua o `Q3`) | cada um no seu | P3 · laboratório |
| Q17 | Conftest informal — **fechado em 30/08/2026**; eram **18 sítios em 14 arquivos**, e a guarda achou mais quatro | notebook | **feito** |
| Q18 | 265 `noqa` inertes — **a escolha foi resolvida por medição em 30/08** e a execução é dos dois lados (ver abaixo) | **acordo** | P2 · laboratório |
| Q19 | Links quebrados e a cobertura obsoleta — **fechado em 30/08/2026**; eram **6** links, não 64, e a cobertura tinha **três** valores | notebook | **feito** |

**Revisado em 25/08/2026 pela [regra de ouro](docs/regra-de-ouro.md).** O guia
mirava um juiz imaginário — "um sênior clonando o repo a frio" — e cinco dos dez
pacotes agradavam esse juiz sem entregar nada ao usuário. Eles não foram apagados:
foram para **P3 · vitrine**, com o motivo escrito, e não começam enquanto houver
item de F6 aberto. A Parte 0 do guia tem o raciocínio inteiro.

Dois avisos para quem pegar:

- **`Q2` já andou.** `F6-A`/`R8.1` fechou no PR #14 e o pacote instala com
  `pip install -e .`. O que sobra é o lockfile e os extras — e `R8.1.b`, que é o
  defeito de `_script()` achar o console script pelo `sys.executable`.
- **`Q6` item pre-commit não se faz**, pelo mesmo motivo já registrado na §10 do
  complemento: um pre-commit com a lista de nomes embutida seria o próprio
  vazamento. `tests/test_saneamento.py` já resolve, e melhor.
---

---

## Auditoria de base — o que a passada de 29/08/2026 fechou, e o que ela achou

> Uma passada de refatoração estrutural sobre as 45.731 linhas de Python do
> repositório, com mandato explícito de **não mudar funcionalidade**. Ela nasceu
> de um pedido de "deixar a base exemplar", e o que encontrou não foi desleixo:
> foi o custo de dezenove dias de fase medida com lint entrando no CI só no
> penúltimo dia.
>
> Esta seção tem duas metades. A primeira é o que **entrou** — sete commits, cada
> um com a classe generalizada que o fecha. A segunda são os pacotes `Q11`–`Q19`,
> que é o que ela **achou e não implantou**, com o contrato de sempre.
>
> A régua continua sendo [`docs/regra-de-ouro.md`](docs/regra-de-ouro.md). Vários
> destes itens são **de laboratório** — custam a nós, não a quem instala amanhã —
> e estão marcados como tal, para que ninguém os promova por parecerem urgentes.

### Os números de partida, medidos antes de tocar em nada

| Medida | Antes | Depois |
|---|---|---|
| Suíte | **7 falhas** em 141,8 s | **1 falha** em ~2 min |
| Idas ao SQLite por consulta, índice corporativo | **350** | **6** |
| `import segundocerebro.painel.app` | **1,08 s**, com `fastembed` carregado | **0,11 s**, sem |
| `index/indexer.py` | 1.753 linhas | 1.368 + quatro módulos |
| `main()` do indexador | 224 linhas | 101 |
| `noqa` que não suprimem nada | **352** | 264, com a escada medida |
| Módulos acima de 500 linhas | 9 | 9, agora com teto que só desce |

A falha que sobra é `eval/test_golden.py::test_toda_fonte_existe`: duas fontes do
dourado saíram do disco na troca de notebook. É condição de dado, não código.

### O que entrou

| Commit | Classe que ficou fechada, e quem passa a pegá-la |
|---|---|
| `fronteira: o produto para de depender do repositório` | `retrieve/hybrid.py::search` importava `Hit` de `eval.harness`, e `eval/` é o único diretório que o `pyproject.toml` não empacota — o método onde a série histórica inteira foi medida levantava `ModuleNotFoundError` para quem instalou com `pip`. **Guarda:** `tests/test_pacote.py` varre o AST de `src/` atrás de qualquer import de `eval`, inclusive dentro de função, que é onde o caso real se escondia |
| `ambiente: a suíte para de entregar `os.environ` sujo` | `aplicar_provider` escreve no ambiente, e `monkeypatch.delenv` sobre variável ausente não registra nada para desfazer: um teste envenenava os seis seguintes que chamassem `indexar()`. **Guarda:** fixture autouse `ambiente_devolvido` no `conftest.py` da raiz |
| `fronteira: o painel para de carregar o encoder` | duas linhas que liam o nome de um arquivo de trava arrastavam `fastembed` inteiro. **Guarda:** `tests/test_painel.py` sobe um subprocesso e reprova se seis módulos pesados aparecerem em `sys.modules` |
| `teste: OCR declara a janela de máquina` | o mesmo arquivo reprovava com 3,5 GB livres e passava com 3,9 GB. **Guarda:** `PISO_RAM_OCR_MB`, e o teste pula com o número em vez de reprovar pela janela |
| `consulta: 350 idas ao SQLite viram 6` | três padrões de N+1 invisíveis num índice de teste com quatro trechos. Resultado idêntico, conferido por `diff` de JSON contra o índice corporativo. **Guarda:** `tests/test_hybrid.py` conta `execute()` e reprova acima de 12 |
| `higiene: código morto fora, regra derivada` | a extensão de OLE legado estava declarada em três módulos que não se importam. **Guarda:** `tests/test_quarentena.py` percorre a tabela do conversor e exige o timeout de convert para **cada** extensão dela |
| `indexer: 1.753 linhas viram 1.368` | regra de teto escrita em 25/08 e não conferida: o arquivo cresceu 610 linhas em quatro dias. **Guarda:** `tests/test_tamanho_dos_modulos.py`, escada que só desce |

Fora dos commits de código: `docs/README.md` (o `Q8`, feito), `eval/arquivo/`
com o marcador `arquivo`, e o `select` do `ruff` com `BLE`, `S603` e `DTZ`.

---

### A passada de execução de 30/08/2026 — o que fechou, e o que ela corrigiu do próprio diagnóstico

> Cinco commits no notebook fecharam `Q11`, `Q12`, metade do `Q13`, `Q17` e
> `Q19`, mais a superfície de pontos de entrada. A suíte foi de **1 falha /
> 1.232 passes** para **1 falha / 1.361 passes** — a falha é a mesma condição de
> dado (`eval/test_golden.py::test_toda_fonte_existe`) — e o tempo caiu de
> **143,5 s para 113,6 s**.
>
> O que mais importa registrar não é o que fechou: é que **quatro dos números
> desta auditoria estavam errados**, e cada um errava para o lado que faz o
> pacote parecer maior ou menor do que é.

| O diagnóstico dizia | A execução mediu |
|---|---|
| `Q12`: seis defaults duplicados | **sete** — `painel/index.html` tinha uma quarta cópia dos tetos de fábrica, num literal JS de fallback que nunca dispara |
| `Q17`: conftest informal de **dez** arquivos | **18 sítios em 14 arquivos**, três deles em `eval/`; e a guarda nova achou **mais quatro** conftests informais que ninguém tinha listado |
| `Q17`: 12 construções de raiz única em 5 arquivos | **16 em 7** — a contagem não incluía a variante em tupla |
| `Q19`: **64 links** para arquivo que o clone não tem | **6 links**. Os outros ~70 são menção em prosa, que é a forma que o próprio pacote prescreve. O número misturava as duas coisas |
| `Q19`: a cobertura é 25%, e o valor medido é 38,5% | **nem um nem outro sozinho.** O `F4-D` reporta um **par**: 3,3% de piso (só as fontes esperadas) e 38,5% de teto (a pasta inteira de cada pergunta). O `README.md` ainda chamava 38,5% de "% das **pastas**", que é a unidade errada |

**E a revisão adversarial do conjunto achou uma regressão que a suíte não pegou.**
A conferência de topo subiu para antes do desvio do censo legado com uma lista de
**uma** chave (`roots`), quando `census.load_config` lê **três** (`roots`, `top`,
`exclude`): `census.example.toml`, que é versionado e é o que o clone copia,
parou de carregar por caminho explícito — a forma documentada em `index/cli.py`.
Assimétrico e por isso enganoso: `carregar()` sem caminho desviava antes da
conferência e funcionava.

Das cinco listas de chaves deste pacote, quatro eram derivadas (do modelo, do
AST, do `pyproject.toml`) e **a única escrita de cabeça foi a que quebrou** — e
o teste que devia prová-la foi escrito pela mesma cabeça, montando um
`census.toml` mínimo com exatamente a chave que a lista tinha. Fechado: a quinta
lista passou a ser derivada do AST de `census.load_config`, e o teste roda contra
os arquivos **reais**.

**Duas coisas que a execução achou e que não estavam em pacote nenhum:**

- **`scripts/abrir-painel.cmd` ainda faz `set PYTHONPATH=src`.** É a mesma classe
  que o repositório já nomeou — *código que só roda de dentro do repositório* —
  e ela sobreviveu ao `F6-A` porque ninguém varreu `scripts/`. Fica como pacote
  próprio: remover exige decidir como um clone sem `pip install -e .` abre o
  painel, e isso encosta na `F6-B`.
- **`config.py` (1.081) e `census.py` (978) estão no teto exato da escada.**
  Toda mudança neles agora exige a costura do `Q16` primeiro. Já aconteceu duas
  vezes nesta passada: o `Q11` empurrou `config.py` para 1.185 e a escada
  reprovou com a instrução certa, o que forçou a extração de
  `config_escrita.py` — a primeira das quatro costuras do `Q16`. E é o que
  **bloqueia** a outra metade do `Q13`: o dialeto de `RootSpec` mora em
  `census.py::load_config`, e não cabem lá as oito linhas que ele custa.

---

### `Q11` — A configuração aceita em silêncio o que não entende — ✅ **FECHADO em 30/08/2026**

**Serve base desconhecida:** sim, e é o caso mais direto desta lista. Quem instala
amanhã escreve o `config.toml` à mão, erra o nome de uma chave, e o produto roda
com o padrão sem dizer nada.

`_secao` recusa chave desconhecida dentro de `pesos`, `busca`, `chunking`,
`limites`, `[maquina]` e `exclude`. Fora dessas, o silêncio é total:

| Onde | Código | O que acontece |
|---|---|---|
| chave direto num `[[base]]` (`apelido = "x"`, `pesoss = {...}`) | `config.py:712-740` | ignorada |
| seção de topo desconhecida (`[bogus]`) | `config.py:1051-1088` | ignorada |
| chave dentro de `[indexacao]` | `config.py:778-792` | ignorada |
| chave extra numa entrada de `raizes` | `config.py:609-621` | ignorada |

É a classe que este repositório já nomeou duas vezes — *regra que não casa com
nada falha em silêncio, e o silêncio parece sucesso*
([`docs/duas-falhas-silenciosas.md`](docs/duas-falhas-silenciosas.md)) — agora na
porta de entrada do usuário.

Tipo errado também não é tratado igual: `LimitesDeIndexacao.validar` confere tipo
antes de comparar (`config.py:217`), e `Pesos`/`Busca`/`Chunking` não —
`candidatos = "muitos"` sai como `TypeError: '<' not supported between instances
of 'str' and 'int'`, não como `ErroDeConfig`.

- **Toca:** `config.py`, `config.example.toml`, `tests/test_config.py`
- **Não toca:** `retrieve/*`, indexador, parsers
- **Saída:** chave desconhecida em qualquer nível vira `ErroDeConfig` citando a
  chave e as conhecidas, como já acontece nas seções; tipo errado idem
- **Classe generalizada:** um teste que varre as dataclasses de `config.py` e
  exige, para **cada** nível de aninhamento, que uma chave inventada levante —
  lista derivada do modelo, não escrita à mão, no desenho de
  `tests/test_formatos.py` e `eval/test_ranking_sintetico.py`

#### `Q11.a` — o que ficou, e por que não entrou junto

Entregue: os cinco níveis, o tipo errado nas quatro seções de base **e** em
`[maquina]`, `exclude` recusando texto onde espera lista, e `[[bases]]` no plural
saindo como o typo que é. `tests/test_config_chaves.py` é a guarda derivada.

**Fica um caso da mesma classe, e é o pior dos que sobraram:** valor booleano
escrito por extenso é engolido em silêncio. Medido em 30/08/2026:

| No `config.toml` | O produto entende |
|---|---|
| `[indexacao] dois_passes = "verdadeiro"` | **`False`** |
| `[indexacao] ocr = "talvez"` | **`False`** |
| `[indexacao] ocr = 3` | `True` |

É **mais grave** que a chave desconhecida, não menos: a chave é conhecida, o
usuário escreveu o valor de propósito, e o silêncio resulta no recurso
**desligado** — o estado que parece normal. Quem escreve `ocr = "sim, por favor"`
não recebe OCR e não recebe erro.

O conserto é um `_booleano(valor, chave)` que recusa o que não reconhece, e custa
**+7 linhas líquidas** em `config.py`. O arquivo está em **1.081 linhas, o teto
exato da escada**, então isto entra junto com a costura `leitura.py` do `Q16` — é
o primeiro item concreto a cobrar daquele pacote.

### `Q12` — Defaults escritos duas vezes — ✅ **FECHADO em 30/08/2026** (eram sete)

**Serve base desconhecida:** sim. Quem copia o exemplo comentado do
`config.example.toml` recebe um teto diferente do que o painel pré-preenche.

| Valor | Onde diz uma coisa | Onde diz outra |
|---|---|---|
| teto de `.xlsx` | `LIMITES_RECOMENDADOS.xlsx = 15.0` (`config.py:240`) | `xlsx = 40` (`config.example.toml:160`) |
| teto de `.md` | `5.0` (`config.py:243`) | `md = 0` (`config.example.toml:163`) |
| tetos de `.pdf/.docx/.pptx` | `50/30/50` (`config.py:237-239`) | `0/0/0` (`config.example.toml:156-158`) |
| porta do painel | `PORTA_PADRAO = 18787` (`painel/app.py`) | `--porta 18787` fixo em `scripts/abrir-painel.cmd` |
| peso de rerank | `config.toml`, `config.example.toml` | `eval/rodar.py` |
| lista de modelos | `MODELOS_CONHECIDOS` (`config.py:371`) | `index.embeddings.MODELOS` — espelho **sem** teste de paridade |

`tests/test_config.py:43-69` já amarra os espelhos de `Pesos`, `Busca`,
`Chunking`, `Maquina.lote` e `LimitesDeIndexacao().txt` contra as constantes de
origem. Os seis acima ficaram de fora — não por decisão, por não terem sido
notados.

- **Saída:** cada valor num lugar só, ou amarrado por teste
- **Classe generalizada:** estender o teste-amarra existente para **derivar** os
  pares a conferir, em vez de listá-los — espelho novo nasce conferido

### `Q13` — Duas chaves que o produto lê e o exemplo não documenta — **metade feita em 30/08/2026**

- **`pesos.fts_texto` / `fts_trilha` / `fts_caminho`** (`config.py:75-77`) chegam
  a `Store.buscar_lexical` e não aparecem em nenhum `.toml`. São a alavanca do
  `C3.a`; quem quiser repetir a medição não descobre que elas existem lendo o
  exemplo.
- **`RootSpec` tem dois dialetos.** `config.py:619` espera `caminho`/`nome`;
  `census.py:858` espera `path`/`name`, para a **mesma** dataclass. Copiar um
  bloco `[[roots]]` de um arquivo para o outro falha com mensagem que cita a
  chave que o usuário não escreveu.

### `Q14` — Um hook de teste vivo em produção — **P1 · produto**

`SEGUNDOCEREBRO_OCR_FAKE` (`ingest/ocr.py:43,149`) desvia o motor de OCR para um
texto fixo, sem nenhuma guarda de "só em teste". Uma variável herdada de sessão de
shell muda o comportamento do produto sem nada no log dizer que o motor é falso.

- **Saída:** ou a variável só vale sob `PYTEST_CURRENT_TEST`, ou o motor falso
  emite `log.warning` em toda passada, com o texto que está injetando
- **Classe generalizada:** um teste que varre `src/` atrás de `os.environ.get`
  cujo nome contenha `FAKE`, `TEST`, `DEBUG` ou `MOCK` e exige guarda ou aviso

### `Q15` — Sob pressão de memória, o OCR some em silêncio — ✅ **FECHADO em 30/08/2026** (com resto declarado)

A causa era uma linha: `ocr_pdf` tinha um `except Exception` que devolvia `None`
— e `None` já significava *"esta instalação não tem OCR"*. Duas condições
opostas, um valor só, e a silenciosa vencia. O mesmo defeito estava numa segunda
porta, e essa desligava o recurso inteiro: `backend_disponivel` fazia
`except Exception: pass` em volta do probe de import, então pressão de memória
era lida como "o extra não está instalado".

O discriminador que faltava é `ausencia_declarada`: `import X` que falha **por X
faltar** é ausência legítima; falhar por outro módulo (`import pymupdf` →
`No module named 'mupdf'`) é condição de máquina. Sem ele, todo probe de extra
opcional lê RAM curta como "o extra não está aqui".

**O que fechou.** Falha de ambiente vira `FalhaDeAmbiente` e, nos **dois** ramos
de `parse_isolado` — o filho e o em-processo —, `erro` com o prefixo `recurso:`.
Há linha de quarentena com motivo, e o documento é repescado. A guarda é
`tests/test_falha_de_ambiente.py`, matriz `modo de falha × ponto de entrada`:
com o conserto revertido, **18 das 20 células reprovam**.

**O piso de RAM saiu de `tests/test_ocr.py`**, que era o critério de saída
declarado. Nesta máquina, com ~3,4 GB livres, os 14 testes de OCR passam com
zero skips em cinco passadas seguidas — antes dois pulavam por falta de veredito.

#### `Q15.a` — o resto, medido e declarado

Sob pressão de memória a fase de OCR quarentena corretamente, mas o **status
final do documento fica `vazio`**, não `erro`. O silêncio acabou — há linha e há
motivo, e desde 30/08 o documento também **continua na fila de OCR** e **não é
aposentado** —, mas a saída declarada dizia "nunca `vazio`", e isso não está
inteiro. A causa é a ordenação de fases do indexador, que repesca `erro` e
reprocessa sem `ocr=True`; mexer nela é mudança no laço de `indexar()`.

#### O conserto do `Q15` estava pior que o defeito, e uma revisão pegou

Registrado porque a lição é maior que o caso. A primeira versão re-levantava
`MemoryError` de dentro do laço de páginas e deixava a falha subir mesmo quando
havia texto nativo. Consequência medida:

| | `main` | primeira versão do conserto |
|---|---|---|
| scan com uma página gorda no meio | 3 páginas, uma vazia | **arquivo inteiro perdido** |
| PDF misto, OCR caindo por recurso | `ok`, com o texto nativo | **`erro`, zero blocos** |

E `indexer.aplicar` chama `remover_documento`, que apaga chunks **e vetores já
gravados**; com `MAX_TENTATIVAS_QUARENTENA = 2`, duas passadas com a máquina
apertada aposentavam o documento até os bytes mudarem — sendo que falha de
ambiente é, por definição, a transitória.

**A regra que ficou:** o OCR é *segunda* passada, e a falha dela nunca pode
apagar a primeira. Página que estoura é pulada; `ImportError` é a máquina,
`MemoryError` é recurso, o resto é o documento.

**Uma segunda revisão achou que o conserto ainda perdia dado, por dois caminhos
que a primeira não viu:**

- O `ParseResult` de recurso não carregava `natureza`, e o `UPDATE` zerava
  `digitalizado` — o scan **saía da fila de OCR** em silêncio.
- `MAX_TENTATIVAS_QUARENTENA = 2` não lia `MOTIVO_RECURSO`, então duas passadas
  apertadas **aposentavam o documento por 100 anos**. O marcador era escrito por
  três sítios e lido por nenhum.
- E qualquer falha na fase de OCR — não só a que o `Q15` tratou — levava
  `aplicar` a `remover_documento` antes de regravar, apagando o que as ondas de
  texto tinham produzido.

Fechados por `index/quarentena.py` (costura do `Q16` para o `store.py`, que caiu
de 1.285 para 1.273) e `repesca.preservar_no_erro_de_ocr`.

### `Q16` — O que falta decompor, com as costuras levantadas — **P3 · laboratório** · continua o `Q3`

O `Q3` foi rebaixado em 25/08/2026 com o argumento certo — *"nenhum leigo tropeça
em `indexer.py` ter 1.143 linhas"* — e com uma ação que era só uma frase: *"regra
em `colaboracao.md`: novo módulo ≤ ~500 linhas"*. Entre aquele dia e 29/08 o
arquivo foi de 1.143 para **1.753**.

A passada decompôs o `indexer.py` (1.753 → 1.368, mais `cli.py`, `trava.py`,
`repesca.py`, `resultado.py`) e instalou o teto como teste
(`tests/test_tamanho_dos_modulos.py`): escada que só desce, módulo novo acima do
teto reprova, e degrau vencido tem de sair da tabela.

O que **falta**, com as costuras já levantadas — decompor não precisa de
releitura, precisa de um PR por linha desta tabela:

| Módulo | Linhas | Costuras propostas |
|---|---:|---|
| `index/indexer.py` | 1.368 | `execucao.py`: o corpo de `indexar()` (1.042 linhas, 24 parâmetros, dez closures com `nonlocal`) como classe, com `relogio`, `estimador`, `publicador`, `fila` e `controle` como atributos |
| `index/store.py` | 1.274 | `registro.py` · `quarentena.py` · `vetores.py` · `busca.py` · `grafo_armazenamento.py` · `execucoes.py`, com `Store` composto e a fachada preservada |
| `config.py` | 1.093 | `modelos.py` (dataclasses) · `leitura.py` (TOML → dataclass) · `ambiente.py` (`SEGUNDOCEREBRO_*`) · `escrita.py` (`como_toml`, `gravar`) |
| `painel/app.py` | 1.025 | `sessao.py` (é o conjunto que `__main__.py` já importa) + rotas por domínio: `ajuste`, `processo`, `base`, `ensino`, `cliente`. `criar_app()` tem **818 linhas** e 20 handlers aninhados |
| `census.py` | 974 | `modelo.py` · `varredura.py` (`iter_files`, caminho longo, nuvem) · `relatorio.py` · `distribuicao.py` (contrato `E6.1`) · `cli.py` |
| `index/calibracao.py` | 931 | `ajuste_rls.py` (o método numérico, sem domínio) · `perfil_maquina.py` · `perfil_formato.py`; persistência fica |
| `ingest/parsers/sheets.py` | 868 | `planilha_bloco.py` (janelamento, compartilhado) · `csv.py` · `xlsx.py` · `xls_legado.py` · `xls_disfarcado.py`. Atenção ao efeito colateral de `@register` no import |

**Duas regras que a decomposição tem de cumprir**, e valem mais que o resultado:

1. **Docstring de decisão se move verbatim.** Elas têm número e data e são o ativo
   mais raro do repositório. O próprio guia já reprova refactor que apaga
   histórico de decisão.
2. **A fachada continua.** Símbolos privados são importados por teste
   (`_precisa_indexar`, `_extensoes`, `_limites_efetivos`, `_deve_ativar_mcp`), e
   `tests/test_painel.py` faz monkeypatch por string em
   `segundocerebro.painel.app.subprocess.Popen`.

### `Q17` — A suíte tem um conftest informal — ✅ **FECHADO em 30/08/2026**

`tests/test_index.py` exporta `EmbedderFalso`, `DIM` e `chunk()` para **dez**
arquivos, por `from tests.test_index import ...`. Qualquer refator ali quebra os
dez. E `tests/test_mcp.py:18-37` define **outro** `EmbedderFalso`, com o mesmo
nome e contrato diferente.

Outros itens da mesma passada, todos de custo baixo:

- `Config(roots=[RootSpec(...)])` com uma raiz só, repetido textualmente em **12**
  lugares de 5 arquivos.
- `tests/test_reconciliar.py::montar()` grava um chunk por vez em laço, em vez de
  um append em lote: **10,7 s dos 162 s** da suíte, em três testes.
- `tests/test_gerador_sintetico.py` — 11 dos 13 testes exercitam só internals de
  `eval/gerador` e pertencem a `eval/`, pela regra que o próprio repositório
  segue (`tests/` ancora em `segundocerebro.*`).
- Cobertura: `ingest/report.py` em **0%** — é uma CLI real
  (`py -m segundocerebro.ingest.report`), 139 linhas, sem um teste.
  `painel/__main__.py` 0%, `index/smoke_cuda.py` 16%.

### `Q18` — 265 `noqa` inertes: a escolha foi resolvida por medição — **P2 · execução dos dois lados**

Com `select = ["E","F"]` os **352** `# noqa` do repositório não suprimiam nada —
era o culto à carga que o próprio `Q1` avisou que aconteceria. A passada ligou
`BLE` (custo zero, deu sentido a 77), `S603` (cinco `noqa` com motivo escrito, que
é o que o `Q4` pede) e `DTZ` (três, com a razão da hora local escrita ao lado), e
tirou três que tinham ficado obsoletos.

Sobram **264**, dos quais **243 são bare** — `# noqa: ANN001` sem uma palavra de
motivo. Há duas saídas, e a escolha não é óbvia:

- **Apagar os 243.** Diff mecânico, tira 243 linhas de ruído que todo agente lê
  toda sessão. Custo: quando `ANN001` for ligado, 195 deles voltam.
- **Ligar as regras.** Medido em 29/08 sobre `src` **apenas** (onde é barato):
  `ANN001` 10 · `ANN201` 1 · `ANN202` 9 · `ANN401` 6 · `ARG001` 4 · `ARG002` 2 ·
  `T201` 1 · `B007` 2 · `N801` 3 · `C901` 26. Sobre `src tests eval` os mesmos
  números explodem (`ANN001` 359, `ANN201` 193), então a rota é
  `per-file-ignores` para `tests/` e `eval/` — que por sua vez torna os `noqa`
  deles inertes de novo.

A escada de fora do `ANN`, medida no mesmo dia sobre `src tests eval`:
`RET` 3 · `B` 17 · `SIM` 25 · `I` 49. **`I` e `ruff format` são PR próprio:**
reescrevem import de 49 arquivos e o corpo de 136, e um diff desse tamanho apaga
`git blame` das docstrings de decisão — que é o que o guia proíbe.

- **Classe generalizada:** `ruff check --extend-select RUF100` no CI, que só passa
  a ser possível quando este pacote fechar

#### A escolha deixou de não ser óbvia — medido em 30/08/2026

A pergunta acima ("apagar ou ligar?") era um empate porque faltava **uma** conta:
quantos dos `noqa` existentes passariam a suprimir algo de verdade. Medida:

| | `src` |
|---|---:|
| `noqa` inertes hoje (`RUF100`) | **92** |
| ... e com `ANN001,ANN201,ANN202,ANN401,ARG001,ARG002,T201,B007,N801,RET` ligados | **17** |
| Achados novos a consertar para ligar essas dez | **40** |

**75 dos 92 passam a ter sentido por 40 correções.** Apagar seria destruir esse
valor: o `noqa` bare não é ruído por natureza, é ruído porque a regra está
desligada. Os inertes fora de `src` são 99 em `tests/` e 74 em `eval/`, e lá a
rota continua sendo `per-file-ignores` — logo, **lá se apaga**.

Fica, portanto: **ligar em `src`, apagar em `tests/` e `eval/`, e então `RUF100`
global**, que é a classe generalizada já escrita acima e que passa a ser possível.

**Por que não entrou nesta passada, e é o ponto que precisa de acordo:** as 40
correções caem em **oito arquivos do desktop** — `index/indexer.py` (5),
`index/gpu_pool.py` (7), `index/smoke_cuda.py` (2), `index/estimativa.py` (2),
`ingest/ocr.py` (2), `ingest/parsers/ole_texto.py` (1), mais `mcp/registrar.py` e
`painel/app.py`, que são "um de cada vez". Ligar a regra obriga o outro lado a
anotar os arquivos dele; isso é decisão de política de repositório com efeito
cruzado, e a regra 8 manda declarar, não fazer. **O notebook recomenda ligar, e
o número acima é o argumento.**

### `Q19` — A documentação promete arquivos que o clone não tem — ✅ **FECHADO em 30/08/2026**

**47 dos `docs/*.md` estão versionados.** Os outros — quase todos
`metricas-*.md` — ficam fora por regra, porque citam nome de arquivo do acervo
real. Isso é correto e documentado. A consequência não é: um link em arquivo
versionado que aponte para um deles resolve em 404 num clone. É a `F6` aplicada à
documentação — quem clona não vê o que nós vemos.

**O diagnóstico deste pacote dizia 64 links; a execução mediu 6** — o 64 somava
link com menção em prosa, e são coisas diferentes (tabela da passada de
30/08/2026, acima). Hoje a varredura acha **0**.

O `docs/README.md` entrou nesta passada (o `Q8`) e **só linka o que o clone tem**.
O que falta:

- **A cobertura de 25% ainda circula como se fosse atual** em cinco lugares
  (`docs/colaboracao.md:239`, `docs/dossie-melhorias.md:10`,
  `docs/fatia-cross-lingual.md:103`, `ROADMAP.md:887` e `ROADMAP.md:1116`),
  enquanto o valor medido é 38,5%. O `F4-D` fechou o instrumento; a correção não
  foi para trás nesses cinco.
- **`docs/censo-conhecimento.md`** é duplicado de `docs/censo.md` com zero
  backlinks — poda, não fusão.

Feitos nesta passada, do mesmo pacote: os **três links quebrados do próprio
`ROADMAP.md`** — o texto dizia `docs/X.md` e o href omitia o `docs/`, e como
este arquivo está na raiz o link resolvia para a raiz. O `README.md` deixou de
anunciar 480 testes
(são 1.288) e de exibir a tabela da era F2 com **reranking ligado** como
"condição de medição mais recente"; o `ARCHITECTURE.md` deixou de descrever o alvo
como "vault Obsidian", que é a premissa que o `CLAUDE.md` marca como já tendo
causado mal-entendido.

- **Classe generalizada:** um teste que resolve todo link markdown de arquivo
  **versionado** e reprova o que aponta para arquivo que o Git não tem. Link para
  arquivo local vira menção em texto, não link

---

## O pacote J — camada de acesso ao corpus, conferido no código

> **Acrescentado em 30/08/2026 pelo notebook.** Documento recebido:
> [`docs/pacote-j-camada-acesso-corpus.md`](docs/pacote-j-camada-acesso-corpus.md),
> marcado *FINAL* e datado do mesmo dia. Ele pede, no próprio texto, o tratamento
> que os dossiês `R1–R10` e `C1–C7` receberam: **mapear cada contrato para o
> layout real vigente antes de criar arquivo**. A conferência inteira está em
> [`docs/plano-pacote-j.md`](docs/plano-pacote-j.md); esta seção é o resumo e a
> mudança de ordem. **Nenhuma linha de código foi escrita nesta passada.**

### O requisito é novo, e nenhuma tool de hoje o serve

O produto tem um modo de consumo: pergunta curta → top-k trechos → o cliente
responde. O modo que o pacote J acrescenta é **ingestão integral dirigida por
agente** — *"escreva um paper sobre o projeto X"* apontando para uma pasta com
dezenas de arquivos, com citação confiável e sob orçamento de contexto.

`search` devolve top-k por relevância; `read_note` devolve um trecho e sua
janela. Nenhuma das duas **enumera, mapeia ou empacota**, e o agente que tenta
hoje lê o que a busca escolher sem saber o que não viu. É a truncagem silenciosa
outra vez, numa camada acima. Serve base desconhecida: **sim** — quem aponta o
produto para uma pasta que nunca vimos quer, no primeiro dia, tanto perguntar
quanto ler tudo.

A peça que habilita os dois modos com um parse só é o **Parse Store**: a
representação canônica persistida de cada documento, promovida de cache interno a
camada de produto. Seis subpacotes, `J.a` a `J.f`.

### O que já existe, e não se duplica

Metade dos contratos sugeridos **já tem dono no código**, e a tabela inteira está
na §2 do plano. Os que mais importam:

- **`ParseCanonico.blocos[]` é `ingest/document.py::Block`** — `heading_path`,
  `text`, `locator`, `kind`, já com trilha de headings e página/slide/aba. Existe
  em memória e nunca foi persistido: o pacote J é a persistência, não o contrato.
- **A política de canônicos é `retrieve/familias.py`**, que já existe, é por nome
  de arquivo e é do notebook.
- **A fonte dos wikilinks do `J.e`** é `retrieve/identificadores.py` + a tabela
  `mencoes` + `glossario.py`. Falta a renderização, não o dado.
- **`parser_version` existe** em `parsers/__init__.py::register(version=)` e na
  coluna `documentos.parser`.

Não existe em forma nenhuma: o store físico, o Markdown canônico, os offsets,
`doc_id` público, a URI `sc://`, as quatro tools, o exportador e a dependência
`zstd`.

### Cinco coisas que a especificação assume e que foram medidas aqui

| O pacote J assume | Medido em 30/08/2026 |
|---|---|
| `doc_id` derivado do hash cobre o acervo | **29 de 2.156 documentos (1,3%) não têm `sha256`** — 27 `sem_parser`, 2 `travado`. O portão de leitura recusa placeholder de nuvem **antes** de abrir, e `list_folder` promete `doc_id` justamente para o item `so_censo`. Ou o manifesto admite id nulo, ou o censo baixa o acervo |
| "um conteúdo, N caminhos, um preferido" é refinamento | **223 de 2.127 paths (10,5%) são byte-idênticos a outro.** É 1 em 10, e hoje o "preferido" é a ordem de indexação — `path_ok_por_sha256` devolve o primeiro `ok` que o SQLite entregar. Para workflow repetível, isso é aleatoriedade com cara de determinismo |
| `get_document` pode sair dos chunks já indexados | **Não pode.** Um bloco de 14.399 caracteres vira 9 chunks que somam 15.999 — **+11,1% de texto duplicado** pela sobreposição de 200 caracteres. O aceite do `J.c` (*"concatenação == .md canônico"*) falha por construção |
| as quatro tools entram em `mcp/server.py` | **Não entram.** `construir` tem 148 linhas e já está em `FUNCOES_ACIMA_DO_TETO`, cuja tabela **só desce**. O `J.c` nasce em módulo próprio, ou o PR fica vermelho |
| `J.d` depende de `R1.3` | `R1.3` está **absorvido por `C6`** desde 24/08 e a instrução vigente é *não implementar* — MinHash a 0,85 refaz a `g045`. A dependência real é `familias.py`, que já existe |

E uma que não é medição, é leitura de invariante: **determinismo byte-a-byte não
vale para três rotas de parse do produto** — LibreOffice, OCR e o recálculo de
planilha passam por binário externo ou motor de ML. A chave da entrada tem de
carregar a **versão do motor externo**, senão um upgrade de sistema deixa o cache
servindo parse velho para sempre — e a mitigação que a especificação propõe
(regra de PR no bump de `parser_version`) não dispara, porque ninguém commitou
nada.

### A mudança de ordem, e por que ela existe

A especificação sugere **a → f → b → c → d → e**, tudo serializado atrás do
store. A medição do `get_document` mostrou o contrário do que parecia: as tools
de **conteúdo** precisam do store, mas as de **mapa** não.

`outline` sai de `chunks.trilha` + `chunks.locator` + `ordinal`; `list_folder`
sai de `documentos` + `census.py` + `quarentena` + `familias_de`. Tudo já existe
e já está indexado. E `doc_id` sai de `documentos.sha256`, que é coluna de hoje —
só falta o índice, que a tabela não tem.

Por isso o `J.b` **divide**: `J.b1` (ids e URI, sem store) e `J.b2` (sidecar com
offsets, com store). Duas frentes em paralelo em vez de uma fila:

| Onda | Subpacote | Dono proposto |
|---|---|---|
| **1** | `J.b1` (ids, índice em `sha256`, URI) · `J.c-mapa` (`outline`, `list_folder`) | notebook — não espera ninguém |
| **1** | `J.a` (store) · `J.f` (indexador lê do store) | desktop se houver crédito, senão notebook |
| **2** | `J.b2` (sidecar) · `J.c-conteúdo` (`get_document`) | notebook |
| **3** | `J.d` (`pack_folder`) | notebook |
| **4** | `J.e` (export vault Markdown) | qualquer |

**`J.a`+`J.f` entram antes da onda 5** (`R3.1`+`C4.1`+`R2.1`), que é o rebuild
coordenado — é ela que paga o investimento do store, e fazer na ordem inversa é
pagar o parse duas vezes.

**A tabela de donos da especificação chega desatualizada:** `J.a`, `J.b` e `J.f`
são dados ao desktop, e o desktop está sem créditos do Grok desde 30/08 — o
notebook assumiu os pacotes dele por autorização explícita
([`docs/colaboracao.md`](docs/colaboracao.md) §6). Ou os três também são do
notebook, ou o P0 não anda.

**Calendário, dito na cara:** seis subpacotes e uma dependência nova não cabem em
dois dias. O que cabe e entrega valor sozinho é `J.b1` + `J.c-mapa` — enumerar e
mapear é o que transforma "ler 50 arquivos" em plano viável para o agente, mesmo
sem `pack_folder`.

### O que o pacote J traz de novo para as regras daqui

Duas coisas que valem além dele:

- **Cursor explícito sempre** (§2.6 da especificação) é a lição da truncagem
  silenciosa aplicada a uma superfície **antes** de o defeito acontecer. É a
  primeira vez neste projeto que uma classe conhecida é fechada preventivamente.
- **O Obsidian volta pela porta certa.** O `CLAUDE.md` registra que ele foi
  deliberadamente não adotado, e isso continua valendo para a *entrada*: não há
  vault, não há wikilink no acervo, o grafo é derivado. O `J.e` é **saída** — uma
  view descartável, one-way, por comando explícito.

### O que fica registrado e não feito

- **MCP resources** como segunda superfície (a própria especificação marca
  "opcional"): duas superfícies para o mesmo conteúdo é a anti-recomendação 5
  aplicada ao transporte, e o ganho depende de cliente que não usamos.
- **Sync bidirecional** com vault e **escrita de derivado dentro do acervo**:
  anti-recomendações 1 e 2 do pacote, e invariante daqui antes disso.
- **Síntese server-side** no `pack_folder`: invariante 2, sem discussão.

**Ablação nula, obrigatória em todo PR do pacote J:** ele não toca ranking, e
provar isso é o dourado antes/depois com **Δ exatamente zero** — não "dentro do
IC". Δ diferente de zero significa que alguém mexeu no caminho de consulta.

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

> **Fechado em 29/08/2026 como instrumento, não como fila de perguntas.** Os dois
> números abaixo (18,2% aqui, 25% no doc) estavam velhos: o de 29/08 é **38,5%**
> de alcance por pasta e **3,3%** de fontes esperadas. Cobertura escrita à mão
> envelhece calada enquanto a métrica que ela qualifica segue sendo citada — e
> essa é a classe que o pacote fecha. `eval/cobertura.py` recalcula a cada
> passada, o bloco entra em `eval.rodar`, `eval.comparar` e `eval.ablacao_f2`, e
> `render_markdown` sem cobertura imprime **"não medida"** em vez de omitir.
> O que segue abaixo é o registro de 24/08, mantido como história.

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

#### F4-O — OCR — **desktop** (R1.2)

O parser de PDF já marca `digitalizado` e devolve zero blocos. O OCR é a
**segunda passada**, depois das quatro ondas de texto — não uma extensão nova,
então o despachante não muda. Extra `[ocr]` (RapidOCR); sem o extra a indexação
é bit a bit a de hoje.

**O.0 (porta) está no código.** A suíte padrão prova a fila com motor **falso**.
Isso não mede RapidOCR, dpi, PDF misto nem o dourado. Tratar O.0 como fase
fechada seria vender `--ocr` como leitura de ofício antigo.

Plano do que falta, com hipótese / efeito mínimo / empate encerra, em
[`docs/plano-ocr.md`](docs/plano-ocr.md):

| Fatia | Dono | Porta | Começa |
|---|---|---|---|
| **O.1** motor de verdade lê identificador VCE plantado numa página-imagem | desktop | binário; marker `ocr` (extra não vai no CI) | **neste PR** |
| **O.2** unidade = página (PDF misto) + raster ≥ 200 dpi + RAM página a página | desktop | três testes, um braço cada | depois do O.1 verde |
| **O.3** `g015`/`g025`/`g048` no `dourado-v1`, recall@5 do trio e Δ agregado com IC95 | notebook | 2 de 3 no top-5; agregado não cai além do ruído | depois de O.1+O.2 em `main` |

- **Toca (O.1):** `ingest/ocr.py`, `tests/test_ocr_motor.py` (marker `ocr`)
- **Toca (O.2):** `ingest/parsers/pdf.py` (sinal **por página**; bump de versão
  só se o texto nativo mudar), `ingest/ocr.py`, `index/orcamento.py`
- **Toca (O.3):** `eval/` do notebook, doc de ablação; nada de `[padrao]`
- **Não toca:** `retrieve/*`, `parsers/__init__.py` (salvo bump combinado no O.2),
  `[padrao]`. `ocr = true` **não** vira padrão antes do O.3
- **Saída da fase:** O.1+O.2 verdes na máquina com extra; O.3 medido ou
  declarado “motor não alcança este acervo”. Empate no O.3 deixa `--ocr` opt-in

#### F4-R — Regime de máquina — **notebook** (`esforco.py` emprestado)

Aberto em 27/08/2026 por uma retratação, não por uma ideia. O achado 16.1 da
spec de estimativa dizia que a máscara de afinidade do perfil `normal` custa
**12×**; medindo com braços intercalados, a mesma máscara custa **zero** no regime
benigno e **8×** noutro, e a mesma máquina entrega 0,141 e 3,19 s/chunk sem que
nada do produto mude. Laudo, com as três hipóteses refutadas:
[`docs/afinidade-e-estado-de-maquina.md`](docs/afinidade-e-estado-de-maquina.md).

Não é pacote de laboratório: a máquina do leigo é um notebook Windows híbrido, e
o perfil **padrão** é o que converte um estado de 2× num estado de 16×.

| Fatia | Porta | Começa |
|---|---|---|
| **R.1** o regime fica observável e **reproduzível sob comando** (gatilho do EcoQoS isolado; tomada/bateria e classe de eficiência gravados em toda observação) | ligar e desligar o estado lento por comando, e o braço `contiguo6` reproduzir 3,1 e 0,18 sob demanda | **sim**, nada bloqueia |
| **R.2** a `Calibracao` não agrupa regimes — regime na chave da observação, ou descarte declarado | teste que prova que observação de regime diferente não entra no mesmo coeficiente | depois do R.1 |
| **R.3** escolher a máscara. Candidato **não medido**: `[0,2,4,5,6,7]` (2 de P-core + 4 de E-core) contra `[0..5]` | ≤1,5× do `livre` no regime lento **e** ≤1,1× do `contiguo6` no benigno. Empate ⇒ hipótese refutada e o pacote vira remover a máscara | depois do R.1 |

- **Toca (R.1):** harness de medição, `index/esforco.py` (relato do regime), doc
- **Toca (R.2):** `index/calibracao.py`, `tests/test_calibracao.py`
- **Toca (R.3):** `index/esforco.py` (`_afinidade`), com número dos dois regimes
- **Não toca:** `retrieve/*`, `[padrao]`, `model_id`, chunking. Nada de grade de
  máscaras, e **nada de trocar máscara antes do R.1** — sem o estado
  reproduzível, o braço mede a janela, que é o erro retratado
- **Saída da fase:** R.1 verde é o que autoriza R.2 e R.3. Sem R.1, a passada de
  calibragem no acervo real **não roda**: ela aprenderia coeficiente de dois
  regimes misturados, com viés a favor e milhares de observações

#### F4-P — Reconciliar os dois caminhos de recuperação — **notebook**

> **Reescopado em 25/08/2026 pela [regra de ouro](docs/regra-de-ouro.md).** O
> pacote era "peso de nome por tipo de fonte" e virou **conserto de defeito**, com
> aceite binário. O que saiu do escopo, e o motivo, está na caixa abaixo — não é
> abandono, é a regra 11 aplicada antes de gastar a varredura.
>
> **Fica no escopo:** o sinal de nome existir em `buscar_chunks` de forma honesta,
> medido com `--entregue` nos dois braços. **Aceite:** cross-lingual recall@20 do
> caminho entregue de **0,750 → 1,000**, recall@1 agregado **≥ 0,551**, nenhuma
> fatia abaixo do piso além do ruído. É binário: alcança ou não alcança.
>
> **Sai do escopo:** a grade de peso por tipo de fonte. No melhor caso teórico ela
> vale **+0,032** de MRR agregado (teto de oráculo, otimista de propósito), com o
> ganho todo concentrado nas 11 perguntas de reunião — e a tabela de simulação do
> `E5` mostra que +0,273 concentrado em três perguntas **empata**. Gastar a
> varredura para chegar a "empate" é o padrão que a regra 11 existe para cortar.
> Ela volta quando houver **duas** coisas que em 25/08 de manhã não existiam: os
> perfis sintéticos do `E1` (para saber se o peso generaliza) e n maior na fatia.
> **As duas passaram a existir no mesmo dia** — o `E1` fechou, e o corpus dele dá
> `reunião` com n=30 em `--n-por-fatia 30` e n≈100 em `--n-por-fatia 100`, contra
> os 11 do dourado real. O pacote é o `F4-P.1`, declarado abaixo.
>
> **Fechado em 25/08/2026, aceite cumprido** —
> [`docs/ablacao-f4p-nome-no-entregue.md`](docs/ablacao-f4p-nome-no-entregue.md).
> Cross-lingual recall@20 do caminho entregue **0,750 → 1,000**, recall@1 agregado
> em 0,551, e o caminho entregue passou a bater o `search` no agregado (MRR 0,696
> contra 0,680). Três coisas ficam declaradas e não escondidas:
>
> 1. **A reunião paga** — nDCG@5 −0,089 [−0,172, −0,017], a única célula da tabela
>    pareada cujo intervalo não cruza zero. Contra o **piso** ela sobe (MRR 0,287 →
>    0,378); a perda é contra o braço anterior, que era o defeito.
> 2. **A porta 5 reprova** contra aquele braço: `g036` 20 → não encontrada, `g010`
>    2 → 3, `g037` 1 → 2. `g036` **também não é encontrada pelo `search`** — é a
>    falha única e histórica do projeto, e o caminho entregue a segurava na
>    posição 20 por não ter o ranqueador de nome. O piso que vale é o `search`, e
>    o próprio número de aceite (0,551) é o número dele.
> 3. **A varredura de peso por tipo de fonte volta a ser defensável.** A regra 11 a
>    cortou por não haver efeito mínimo declarado; agora há, e é esta perda em
>    reunião. **A outra metade também já existe** — o `E1` fechou no mesmo dia e
>    o corpus dele foi construído para esta pergunta. A frase original desta
>    linha dizia o contrário e foi corrigida; ver a caixa da `F4-P`.
>
> **Classe generalizada** (regra 12): "o eval mede um caminho e o cliente executa
> outro" ficou fechada pelo `F4-P.0` — `eval/entregue.py` e `--entregue` em
> `eval.rodar` **e** em `eval.comparar`. **A ponta fechou em 25/08/2026** com o
> `Q5` P0: `tests/test_protocolo_mcp.py` sobe o servidor por stdio contra uma
> `BuscaHibrida` cujo `search` — o ranqueador de **documento** — explode. Trocar
> `buscar_chunks` por `search` na ferramenta MCP agora põe quatro testes em
> vermelho no mesmo commit, e há um segundo teste que impede a armadilha de virar
> no-op em silêncio.

Ranking não muda sem número.

O escopo cresceu por medição em 24/08. Nas 11 perguntas de reunião, **desligar o
ranqueador de nome sobe o MRR 60%** (0,287 → 0,459) e o recall@1 três vezes
(0,091 → 0,273); no conjunto inteiro ele continua se pagando (recall@1 0,551
contra 0,534). Ou seja: o peso certo do nome provavelmente **não é um número só**,
é peso por tipo de fonte — no documento de escritório o identificador está no
nome, na transcrição o nome só tem assunto e data. `n = 11` é sinal, não decisão.

**O que `C3.a` já resolveu deste pacote, em 24/08/2026** — ver
[`docs/ablacao-c3a-pesos-fts.md`](docs/ablacao-c3a-pesos-fts.md):

- o braço "bm25 no padrão" está **varrido**, com 18 configurações na mesa, e a
  dupla contagem não é a causa do efeito. Nada mudou de padrão: `fts_caminho`,
  `fts_trilha` e `nome` ficam como estavam;
- o recorte por grupo de fonte **existe** (`eval/fonte.py`), sai em todo relatório
  do harness e reproduz `dourado-cobertura.md` com três decimais;
- **a linha de base a bater é a de hoje** — `nome = 0,5`, MRR 0,680, nDCG@5 0,682,
  recall@1 0,551, reunião 0,287. A varredura confirmou o 0,5, por dois motivos em
  vez de um: escritório **e** ponte PT↔EN;
- há um **teto de oráculo de +0,032** de MRR agregado (0,680 → 0,712). A referência
  já é o ótimo do escritório (MRR 0,761, o maior da grade), então toda a folga está
  na reunião. Otimista de propósito: supõe rotear pelo grupo da fonte esperada, e o
  recuperador só conhece o grupo do documento candidato;
- **e a interseção que o teto não desconta: 3 das 11 perguntas de reunião são
  cross-lingual.** Baixar `nome` na reunião tira a ponte de 27% do próprio grupo
  que se quer melhorar. Medir a interseção, não só os dois eixos;
- dois candidatos registrados e **não** aplicados, para `F4-P` decidir:
  `fts_caminho = 0,3` (−0,034 de recall@1 e −0,009 de MRR contra +0,050 de
  recall@5, +0,010 de nDCG@5 e razão `C4.5` 0,73 → 0,79) e o piso absoluto no
  critério de aceite do `C4.5`, que esta grade mostrou ser satisfazível piorando o
  denominador.

- **Toca:** `retrieve/*`, `eval/*`, pesos da base corporativa — **não** `[padrao]`
  sem o desktop saber
- **Não toca:** indexador, parsers
- **Braços a medir:** peso de nome por tipo de fonte (pelo grupo do **documento**,
  que é o que se sabe em tempo de consulta); família de renderização
  **colapsando irmãs no ranking** (não escolhendo por nome — a ordem de
  preferência por nome foi medida e está errada, ver `docs/dourado-cobertura.md`)
- **Saída:** decisão registrada, com armadilhas medidas, um número por grupo de
  fonte e a distância até o teto

---

#### F4-P.1 — Peso de nome por tipo de fonte — **notebook**

> **Estava BLOQUEADA, e o `F4-T` a desbloqueou no mesmo dia (27/08/2026).** A fatia que decidiria
> o pacote tem **n=0**, não n≈100: as 100 perguntas de `reunião` da camada 2
> apontam para `.vtt`, e `.vtt`/`.srt`/`.sbv` **não estão** em
> `supported_extensions()` — não existe parser de transcrição. Auditado no
> `index-e1`: grupo `reunião` com **3** documentos candidatos de 200 registrados,
> e **0** das 100 perguntas com fonte indexada.
>
> Rodar a medição declarada daria Δ pareado 0,000, IC cruzando zero, e o critério
> de encerramento fecharia o pacote com **"hipótese refutada"** — cumprindo todas
> as regras e registrando a conclusão errada. Laudo e a classe generalizada em
> [`docs/fatia-reuniao-invisivel.md`](docs/fatia-reuniao-invisivel.md); a porta que
> passa a pegá-la é `tests/test_fonte_contrato.py`.
>
> O que estava pronto continua válido: o mecanismo, a definição única de grupo e a
> base da camada 2.
>
> **FECHADA em 27/08/2026 — hipótese mal especificada, não refutada.**
> [`docs/ablacao-f4p1-nome-por-fonte.md`](docs/ablacao-f4p1-nome-por-fonte.md). A
> medição rodou (2.119 perguntas, fatia `reunião` com n=100 e 100 de 100 fontes
> indexadas) e deu **`+0.000 [+0.000, +0.000]` em todas as células**. Intervalo de
> largura zero é ausência de manipulação, não empate: no corpus sintético o
> ranqueador de nome **não pontua um único documento de reunião** (0 de 40
> sondadas), então zerar o peso dele não tinha em que agir.
>
> E o motivo de fechar é mais forte que o instrumento. Na camada 1, onde o dano de
> **−0,089** existe, os documentos que passam à frente da fonte de reunião são
> **11 de escritório contra 1 de reunião**: a alavanca zera o peso nas **vítimas**,
> não na causa. O contrato derivou o efeito mínimo de uma fatia definida pelo grupo
> da **fonte esperada** e aplicou a alavanca ao grupo do **candidato** — dois
> conjuntos diferentes, e o nome igual escondeu isso.
>
> `PESO_NOME_POR_GRUPO` e `retrieve/fonte.py` ficam, desligados por padrão e
> exercitados por teste: a definição única de grupo já se paga servindo o recorte
> do harness. Não reabre com outra grade.

> **Aberto em 25/08/2026, e é a metade que a regra 11 tinha adiado.** A `F4-P`
> cortou a varredura por não haver efeito mínimo declarado. Ela mediu um, e no
> mesmo dia o `E1` entregou a outra condição. As duas linhas abaixo são o que
> desbloqueou o pacote, e nenhuma delas é intuição:
>
> - **efeito mínimo**: nDCG@5 de reunião **−0,089 [−0,172, −0,017]** no caminho
>   entregue, a única célula da tabela pareada da `F4-P` cujo IC não cruza zero;
> - **instrumento**: o corpus do `E1` tem o eixo `grupo_de_fonte`, e a fatia
>   `f_reuniao` foi escrita para esta pergunta —
>   *"a `F4-P` decide sobre reunião e sobre cross-lingual"*, na docstring dela.
>   `reunião` sai com n=30 em `--n-por-fatia 30` e n≈100 em `--n-por-fatia 100`,
>   contra os **11** do dourado real.

**A camada que decide é a 2, e isto não é detalhe de procedimento.** No dourado
real a fatia `reunião` tem n=11 e o Δ pareado dela na `F4-P` saiu com IC de
largura 0,165 em MRR — maior que o efeito de +0,074 que se espera recuperar.
Medir a decisão ali seria pedir à fatia que responda o que ela não consegue
distinguir, que é a forma exata que o `E5` provou indetectável. O dourado real
entra como **piso de regressão**, e só.

| Campo | Valor |
|-------|--------|
| Dono | **notebook** |
| Paths | `src/segundocerebro/retrieve/fonte.py` (novo), `retrieve/hybrid.py`, `eval/fonte.py`, `eval/comparar.py`, testes dos três |
| **Serve base desconhecida** | sim, e é a razão de existir. A regra é de **formato e vocabulário genérico** — `.vtt`/`.srt`/`.sbv` é transcrição onde estiver, `.msg`/`.eml` é email onde estiver. A afirmação é estrutural: **a transcrição tem no nome o assunto e a data, nunca o identificador**, porque é assim que gravador de reunião nomeia arquivo. Isso vale no acervo do próximo, não só no nosso |
| **Hipótese** | zerar o peso do ranqueador de nome **para o documento candidato do grupo `reunião`**, mantendo 0,5 nos demais, melhora a fatia `reunião` sem derrubar o agregado |
| **Efeito mínimo** | fatia `reunião` do corpus sintético do `E1` (n≈100), Δ pareado de **MRR@10 ≥ +0,05 com IC95 que não cruza zero**. Declarado antes de gerar o corpus |
| **Orçamento** | **uma** medição. Sem grade: o valor 0 não é escolhido por busca, vem do que `dourado-cobertura.md` já mediu (reunião com `nome = 0` dá MRR 0,459 contra 0,287). Segunda passada exigiria acervo novo, não outra grade |
| **Critério de encerramento** | empate no Δ pareado **encerra** o pacote com "hipótese refutada" no doc. Também encerra se o piso cair: recall@1 agregado do dourado real abaixo de 0,551, ou orçamento de armadilha estourado |
| **Classe generalizada** | "a régua que mede e a regra que ranqueia divergem em silêncio". Hoje `grupo_de_fonte` só existe em `eval/`, e nada impede o produto de classificar diferente do relatório. A função passa a morar em `retrieve/` e o `eval/` a importa — **uma definição**, com teste que falha se o `eval` ganhar a sua própria cópia |
| Saída | teste na suíte padrão, sem GPU e sem `perguntas.jsonl`; ablação em `docs/` com os dois braços e as duas camadas |

- **Toca:** o que está em Paths. **Não** `[padrao]` sem o desktop saber
- **Não toca:** indexador, parsers, chunking, o glossário
- **A interseção que precisa aparecer no relatório:** no dourado real, 3 das 11
  perguntas de reunião são cross-lingual, e o nome é a ponte PT↔EN. Zerar o peso
  na reunião tira a ponte de 27% do grupo que se quer melhorar. **A tabela tem de
  trazer a célula `reunião ∩ cross-lingual`**, não só os dois eixos — foi a
  ressalva que o `C3.a` registrou e que o teto de oráculo não descontava

---

## F6 — Primeiro uso em máquina desconhecida — **porta de fase**

> **Acrescentada em 24/08/2026. Promovida a porta de fase em 25/08/2026.** Não é a
> F5: não há segundo usuário, ACL nem API paga. É o buraco entre "os dois setups
> usam o repo" e "um leigo instala numa pasta qualquer e pergunta". Continua sem
> depender do dourado corporativo nem das 980 Ti — o que mudou é que ela deixou de
> ser trilha paralela.
>
> **A promoção tem motivo, e é o de sempre neste repositório: o que corre em
> paralelo sem porta não corre.** A F6 foi escrita em 24/08 com a frase mais forte
> do plano — *"enquanto isso não passou, não é produto"* — e marcada "pode correr
> em paralelo", que na prática é dono nenhum. Agora: **nenhuma fase F4+ fecha sem
> o teste da F6 passar**, e um pacote de vitrine (`Q3`, `Q7`, `Q8`, `Q9`) não
> começa enquanto houver item de F6 aberto.
>
> **A régua de prontidão** — instala frio, sobrevive a pasta estranha, devolve
> procedência, cabe na latência, generaliza, não derruba o piso — está em
> [`docs/regra-de-ouro.md`](docs/regra-de-ouro.md).

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

### F6-C — Hardware: CPU padrão, CUDA opcional — ✅ **FECHADA em 30/08/2026**

Estava **implementada e não declarada**, e é um estado que este repositório
produz com frequência: `cuda_runtime.diagnosticar` já recusava em português nos
seis motivos, com `gpus`/`versao_ort`/`providers` injetáveis para teste. O que
faltava era a prova de que a fase continua fechada.

- **"Numa máquina sem NVIDIA a indexação é CPU e a suíte padrão passa"** — este
  notebook tem 0 GPUs e a suíte roda verde; `test_sem_placa_a_suite_padrao_passa_e_o_produto_diz_cpu`
  é a linha que torna isso uma asserção em vez de uma coincidência.
- **"Com GPU incompatível o smoke recusa em português"** — os seis motivos
  (`sem_gpu`, `cuda13`, `minilm_q`, `ep_ausente`, `driver_maxwell`, `sem_ort`)
  têm mensagem e teste.

**A guarda derivada achou uma lacuna que a leitura não tinha achado:** `SEM_ORT`
— placa presente e extra `[gpu]` ausente, que é o caso mais comum de quem
instala — tinha mensagem e **não tinha teste**. Escrito junto.

- **Classe generalizada:** `test_toda_recusa_alcancavel_tem_teste_proprio` varre
  o AST de `diagnosticar`, colhe os `DiagnosticoCuda(...)` que ela constrói e
  exige teste para cada motivo; `test_todo_motivo_de_recusa_tem_mensagem_em_portugues`
  deriva os motivos do módulo e exige mensagem. Ramo de recusa novo nasce
  conferido — que é a diferença entre "a fase fechou" e "a fase continua fechada".

### F6-D — Uma página em português — ✅ **FECHADA em 25/08/2026**

- **Toca:** `docs/comecar.md` (novo). Não reescrever `CLAUDE.md`
- **Saída:** instalar, apontar pasta, esperar barra, perguntar. Sem jargão de
  fase. O vocabulário de exemplo é a VCE

> **Todo comando da página foi rodado antes de entrar nela**, e três afirmações
> caíram por isso: os quatro console scripts existem nesta máquina e **nenhum** é
> achado pelo nome, então a página ensina a forma `py -m …` e explica o atalho em
> vez de mandar digitá-lo (era a condição que `colaboracao.md` §6 exigia); o
> `python` puro não é comando aqui, só o `py`; e a indexação **registra a base
> sozinha** no `.mcp.json` ao terminar, o que encurta o passo de conectar.
>
> **Duas afirmações minhas eram invenção e saíram** — "1 GB de disco" e "o índice
> fica em 3% do acervo". Medido: 2,1 GB o `e5-large`, 241 MB o `minilm`, e o
> índice do corpus sintético saiu **maior** que o corpus (225 KB contra 179 KB),
> porque em acervo minúsculo o que se vê é o custo fixo. A página passou a não dar
> número de disco de índice: o censo estima **tempo**, não espaço, e prometer o
> que não se mede é o defeito que a regra 7 nomeia.
>
> **Classe generalizada** (regra 12): "doc de usuário afirma coisa que o código
> não sustenta". O precedente estava no mesmo dia — `usar-o-mcp.md` dizia "duas
> ferramentas" um mês depois de a `neighbors` estar servindo. Três guardas
> fecham as três instâncias mensuráveis: a lista de ferramentas contra o que o
> protocolo entrega (`tests/test_protocolo_mcp.py`), e em
> `tests/test_docs_do_usuario.py` o `py -m <modulo>` de cada página contra o
> ponto de entrada que existe, e a lista de formatos contra
> `supported_extensions()`, nos dois sentidos.

**Teste da fase, numa máquina que não é a nossa:** Windows sem NVIDIA, pasta
nova, corpus sintético, um cliente MCP. Enquanto isso não passou, não é
produto — é o laboratório dos dois setups.

**F6-E — a pasta hostil** — ✅ **FECHADA em 25/08/2026, dentro do `E1.e`.**

> Foi acrescentada em 25/08 com "dono a combinar" e fechou no mesmo dia, absorvida
> pelo gerador sintético: **o gerador é o montador de pastas**, e manter as duas
> separadas produziria duas fixtures da mesma classe, divergindo. A leitura está
> em [`docs/matriz-de-armadilhas.md`](docs/matriz-de-armadilhas.md); o código é
> [`eval/gerador/hostil.py`](eval/gerador/hostil.py) e
> [`tests/test_pasta_hostil.py`](tests/test_pasta_hostil.py).
>
> **E o checklist mudou de natureza, que é o que vale.** A lista abaixo era de dez
> armadilhas escritas de cabeça, e lista escrita de cabeça envelhece. A cobertura
> passou a sair de **`ingest.document.ParseStatus`** — o catálogo que o produto já
> declara — com tabela de lacunas declarada e um segundo teste que a impede de
> crescer por conveniência. **Status novo sem fixture reprova**, e quem escreveu o
> status descobre no mesmo dia.

O teste da fase mede a máquina; esta parte mede o **acervo**. Uma pasta montada de
propósito com o que uma base desconhecida tem e a nossa não: nome tipo
`Scan_001.pdf`, caminho acima de 260 caracteres, placeholder de nuvem, arquivo
aberto no Word, planilha sem cache de fórmula, PDF sem texto extraível,
`.doc`/`.xls`/`.ppt` legado, nome com emoji e com acento, arquivo de 0 byte,
extensão que mente sobre o conteúdo.

- **Aceite:** a indexação **termina**, o registro diz por documento o que
  aconteceu, e nada entra no índice como se tivesse texto quando não tem. Falhar é
  aceitável; travar ou mentir em silêncio, não.
- **Por que é porta e não teste unitário:** cada item desses já apareceu aqui uma
  vez, um por vez, achado por acidente — caminho longo na F1, arquivo travado na
  F1, `data_only` em planilha no `C7.a`, `sem_parser` silencioso na F4. A classe é
  "documento que o disco tem e o índice não conta", e ela só se pega com uma pasta
  que a contenha inteira (regra 12).

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
