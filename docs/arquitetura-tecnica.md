# Segundo Cérebro — descrição técnica da arquitetura

> Documento para revisão técnica. Estado: F0 concluída, F1 em andamento (parsers
> e chunking prontos, índice em construção). Data: 12/08/2026.
>
> Todo número aqui foi **medido no acervo real**, não estimado. Onde há
> suposição, está marcada como tal.

---

## 1. O problema e as restrições

Recuperação de alta precisão sobre ~3.150 documentos corporativos (PDF, Word,
Excel, PowerPoint) em pasta sincronizada do OneDrive/SharePoint, consumível por
qualquer cliente de IA, com **custo marginal zero por consulta**.

Quatro invariantes que governam todas as escolhas. Violar qualquer uma exige
mudar o documento de arquitetura, não contornar no código:

| # | Invariante | Consequência |
|---|-----------|--------------|
| I1 | Nenhuma chamada a API paga no caminho de consulta | Embedding e reranking são locais; geração é do cliente |
| I2 | Nenhuma ferramenta que gere texto na superfície | Sem `answer`, `summarize`. Isso reintroduziria custo e amarraria a fornecedor |
| I3 | Multi-hop é do cliente | O servidor oferece primitivas componíveis, não orquestrador |
| I4 | Toda mudança de chunking, embedding ou ranking passa pelo eval | Sem número antes e depois, não entra |

A I4 é a que mais afeta o dia a dia: existe um conjunto dourado de **51
perguntas com fonte conferida documento por documento**, e um harness que mede
recall@k, MRR e nDCG. É a régua de todas as fases.

---

## 2. Decisão estrutural: servidor MCP, não aplicação

O sistema não tem UI e não gera texto. Expõe ferramentas de recuperação via
Model Context Protocol; o cliente (Claude Code, Copilot, Antigravity) fornece
modelo, loop de agente e interface.

```
Cliente MCP (assento já pago)          Servidor local
┌───────────────────────────┐   stdio   ┌──────────────────────────────┐
│ modelo: entende, raciocina│ ◄───────► │ superfície de ferramentas    │
│ e escreve a resposta      │           │ recuperação híbrida + rerank │
└───────────────────────────┘           │ índice (LanceDB + SQLite)    │
                                        └──────────────┬───────────────┘
                                                       │ leitura local
                                        ┌──────────────▼───────────────┐
                                        │ pastas em disco / SharePoint │
                                        └──────────────────────────────┘
```

**Por que isso satisfaz I1 e I2 ao mesmo tempo.** As etapas de alto volume
(embedding de todo o corpus, busca a cada consulta, reranking de ~50 candidatos)
rodam localmente. A etapa de baixo volume (uma geração por consulta) roda no
cliente, cujo custo já está pago. Trocar de modelo é trocar de cliente; nenhuma
linha do servidor muda.

**Por que resolve I3 de graça.** Recuperação agêntica é um modelo chamando
ferramentas de busca em loop. O cliente já faz isso. O servidor só precisa
oferecer `search`, `read_note`, `neighbors`, `list_recent`, `glossary`.

---

## 3. Pipeline de ingestão

```
iter_files ──► reader (portão) ──► parser ──► chunker ──► embedder ──► índice
  metadados      bytes            blocos      chunks      vetores
```

### 3.1 O portão de leitura — um único ponto que abre arquivo

`ingest/reader.py` é o **único** lugar do sistema que chama `open()` sobre o
acervo. Todo parser recebe `bytes`. Há teste que proíbe `open()` durante o parse
e falha se algum parser tentar. Isso não é purismo: sem o portão, o próximo
formato adicionado furaria a checagem de nuvem sem ninguém notar.

Três riscos concretos que o portão trata, todos encontrados no acervo real:

| Risco | Evidência no acervo | Tratamento |
|-------|---------------------|------------|
| **Placeholder de nuvem** — ler dispara download de arquivo que não está em disco | 1 arquivo detectado em amostra de 222, num acervo que o censo reportou como 100% local 20h antes | Atributos `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`/`OFFLINE` checados **antes** de abrir; hidratação só com flag explícita |
| **Caminho acima de 260 caracteres** | 34 arquivos; o mais longo tem 293. E 17 **diretórios** cuja varredura falhava, escondendo 57 arquivos e 0,9 GB | Prefixo `\\?\` na travessia e na abertura |
| **Arquivo travado por Word/Excel** | 2 em 5 arquivos conferidos à mão; o acervo é pasta de trabalho viva | Nova tentativa e depois status `travado`, reindexado na passada seguinte — nunca exceção, nunca descarte silencioso |

Toda falha vira **status registrado**, não exceção: `ok`, `vazio`, `travado`,
`placeholder`, `sem_parser`, `erro`. Um corpus onde 8% falhou em silêncio é
indistinguível de um corpus com ranking ruim, e os dois pedem correções opostas.

### 3.2 Parsers — a unidade de bloco é decidida por formato

| Formato | Arquivos | Unidade de bloco | Decisão que importa |
|---------|---------:|------------------|---------------------|
| PDF | 1.509 (47,8%) | Seção detectada por tamanho de fonte, com `p. N` | Ver §3.3 |
| XLSX | 686 (21,7%) | Aba + cabeçalho + janela de linhas | **Uma linha não é um chunk.** Ver §3.4 |
| DOCX | 463 (14,7%) | Seção sob heading real do Word | Percorre o XML do corpo, não `paragraphs` e `tables` em separado — senão toda tabela gruda no último título. Estilos reconhecidos em inglês **e** português |
| PPTX | 251 (8,0%) | O slide | Slide já é um chunk: autorado como uma ideia com título. Notas viram bloco à parte |
| MSG | 110 (3,5%) | — | F4 |

Todo bloco carrega **trilha de headings** e **localizador** (`p. 12`,
`slide 4`, `Orçamento!A1:F40`). O localizador é procedência, que é invariante do
projeto, não conveniência.

### 3.3 PDF: motor por fonte, não por análise de layout

`pymupdf4llm` faz análise completa de layout e produz markdown com headings.
Medido contra extração direta em 4 PDFs do acervo:

| Motor | Tempo | Caracteres | Profundidade de títulos |
|-------|------:|-----------:|------------------------:|
| `layout` (pymupdf4llm) | 12–34 s/arquivo | referência | referência |
| `fonte` (nosso) | 0,1–1,2 s/arquivo | −3% a +7% | empata |

**11 a 129× mais rápido.** Nenhuma opção da biblioteca muda isso
(`table_strategy=None`, `ignore_graphics=True` — testados, sem efeito): o custo
é a análise de layout em si. Projeção para 1.509 PDFs: **8,4 h contra 19 min.**

A diferença não é conforto. Uma passada de 8 h não é repetível, e sem repetir, a
I4 deixa de valer na prática. O motor `fonte` reconstrói a hierarquia pelo
tamanho da fonte: o tamanho que cobre mais caracteres é o corpo; linha curta em
fonte maior vira título, ranqueado por tamanho.

**Os dois motores ficam no código.** A decisão tomada foi de custo, que foi
medido. Qualidade de recuperação só o eval prova, e a ablação `fonte` vs
`layout` está prevista na F2 com nDCG.

*Detecção de PDF digitalizado:* dois sinais, não um. Texto quase ausente
(< 15 chars/página) **ou** página coberta por imagem com pouco texto (< 100
chars/página). O limiar inicial de 50 chars/página reprovou num teste com um
recibo legítimo de 42 caracteres — o acervo tem dezenas de faturas e recibos
curtos. Digitalizado é **marcado**, não indexado: ~3% dos PDFs, projetando ~45
no acervo. OCR fica como decisão separada.

### 3.4 XLSX: três regimes, porque planilha não é texto

Com janela fixa de 30 linhas, as 48 planilhas de uma amostra de 222 arquivos
geravam **4.116 blocos contra 2.684 de 100 PDFs** — planilha seria a maioria do
índice com 21% dos arquivos, e cada chunk custa um forward pass de CPU.

Medição sobre 80 planilhas (1.037 abas com dados): mediana de **230 linhas × 22
colunas**, mas 4,6% das abas passam de 5.000 linhas e concentravam **3,1 milhões
de linhas** que o corte anterior descartava em silêncio. Duas abas batem no
limite do Excel (1.048.576 linhas).

| Regime | Critério | Tratamento |
|--------|----------|------------|
| Resumo | ≤ 200 linhas | Janela de 30 linhas, cabeçalho repetido em cada janela |
| Tabela | 200–5.000 linhas | Janela de 200 linhas + cartão descritivo da aba |
| Despejo | > 5.000 linhas | Cartão + **digesto de valores distintos das colunas identificadoras**, cobrindo a aba até o fim, sem limite de linha |

O digesto responde à pergunta que se faz a uma exportação — "esta aba tem o
fornecedor X?" — de forma compacta. O valor exato de uma célula sai depois, via
`read_note` na faixa: recuperação dá procedência, o cliente aprofunda.

Duas correções que testes forçaram no desenho:

- **Coluna de medida é ignorada.** A coluna `Valor` gerava 16 chunks de números
  decimais que ninguém busca. Detectada por presença de separador decimal.
- **Coluna de chave única não cabe inteira.** Um milhão de identificadores
  distintos seriam milhares de chunks. O teto de 8.000 valores fica declarado em
  `meta['digesto_parcial']`. Cobertura é **completa para coluna categórica** —
  três fornecedores repetidos em um milhão de linhas ficam inteiros — e
  **limitada para chave única**. A distinção está em teste.

Resultado: blocos de XLSX de 4.116 → 1.413, e caracteres por chunk de **22.296 →
6.655**, o que também resolveu um problema de qualidade que não era o alvo —
chunk de 22 mil caracteres embute um vetor diluído.

### 3.5 Chunking — determinístico, sem modelo

Três regras, código puro:

1. Bloco que cabe no limite **é** o chunk. Nada é cortado. Os parsers já
   segmentaram por estrutura real, e estrutura vence corte por tamanho.
2. Bloco maior é cortado com sobreposição de 200 caracteres, preferindo
   fronteira de parágrafo, depois de frase, depois de palavra. A trilha de
   headings é **repetida em cada pedaço**.
3. Blocos pequenos vizinhos sob a mesma trilha são juntados até o limite.

Planilha e tabela nunca são cortadas: cortar tabela desalinha coluna e valor.

**Id estável** derivado de `(versão do chunker, documento, trilha, localizador,
ordinal)`. A versão do chunker entra de propósito — mudar a regra muda todos os
ids, porque um chunk produzido por outra regra é outro chunk.

**Nenhum LLM decide onde cortar.** Três razões, em ordem de importância:

1. **Não determinismo mata o eval.** Chunk dependente de LLM muda a cada
   reindexação, e a métrica de antes deixa de ser comparável com a de depois.
   Todo o método (I4) para de funcionar. Este é o motivo forte, e não é dinheiro.
2. Custo por documento a cada reindexação — viola I1.
3. Chunking semântico por LLM ajuda de fato em texto sem estrutura (transcrição
   corrida). Se entrar algum dia, será enriquecimento offline com resultado
   versionado, nunca no caminho da consulta, e passando pelo eval.

**Cabeçalho contextual.** O texto embeddado é a trilha prefixada:

```
6. DESCRIÇÃO DO PROCESSO > 6.1 Visão Geral do Fluxo
---
O processo de classificação de risco segue as etapas abaixo...
```

Sem a trilha, esse parágrafo não diz de que processo fala. Custa duas linhas e é
um dos maiores ganhos de precisão disponíveis.

**Limite de 1.800 caracteres, imposto pelo encoder.** Medido: **4,49 caracteres
por token em português**, logo a janela de 512 tokens é ~2.298 caracteres. Com o
limite anterior de 2.500, o p90 dos chunks batia exatamente em 512 — cerca de
**10% eram truncados em silêncio**, com o índice parecendo completo. É o pior
modo de falha possível.

---

## 4. Embedding e índice

### 4.1 O BGE-M3 saiu do plano — e por quê

O plano original era BGE-M3 via `fastembed`: um modelo produzindo dense e sparse
no mesmo forward pass, dispensando índice lexical separado.

**O `fastembed` 0.8.0 não tem BGE-M3.** Listando o catálogo: os densos são todos
ingleses (`bge-base-en`, `bge-small-en`), os esparsos também (SPLADE inglês,
BM25, BM42). Descoberto instalando, não lendo documentação.

Substituição, mantendo as invariantes:

| Papel | Escolha | Alternativa descartada e por quê |
|-------|---------|----------------------------------|
| Denso | `paraphrase-multilingual-MiniLM-L12-v2` (384 dim) em desenvolvimento; `multilingual-e5-large` (1024 dim, MIT) como alvo | `jina-embeddings-v3` era tecnicamente melhor (8192 tokens, adaptadores separados para consulta e passagem) mas a licença é **CC BY-NC** — impedimento para uso corporativo |
| Lexical | **SQLite FTS5** com `bm25()` nativo | `Qdrant/bm25` como vetor esparso: exige que o banco vetorial aplique IDF, e a fusão RRF já é nossa. FTS5 dá IDF real, sem modelo, sem dependência nova |

Consequência assumida: **o esparso deixa de ser aprendido.** BM25 pesa por
frequência, não por relevância aprendida. Para os casos que justificam o esparso
no acervo — código de contrato, número de processo, sigla interna — casamento
exato é casamento exato e o BM25 resolve. Onde perde é em vocabulário próximo
mas não idêntico.

*Nota de implementação sobre FTS5:* hífen, ponto e barra são operadores na
sintaxe MATCH. Um código como `PO-ACME-007` sem aspas vira `PO NOT ACME NOT 007`.
Cada termo da consulta é aspado antes de ir ao FTS5 — verificado.

### 4.2 A escolha do modelo é imposta pelo hardware

Medido nesta máquina (i7-1355U, 12 threads, 15 W, sem GPU CUDA), 40 chunks reais
do acervo, `threads=10`:

| Modelo | dim | chunks/s | Indexar 89 mil chunks |
|--------|----:|---------:|----------------------:|
| `multilingual-e5-large` | 1024 | 0,63 | **39 h** |
| `paraphrase-multilingual-mpnet-base-v2` | 768 | 2,10 | 11,8 h |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | 13,22 | **1,9 h** |

`batch_size` não muda nada (16 e 64 empatam); `threads=10` rende +26% sobre o
padrão. O gargalo é compute por token.

**Decisão:** MiniLM durante o desenvolvimento, porque 1,9 h permite reindexar e
iterar; e5-large como alvo de produção, com indexação em segundo plano e
retomável. O modelo é parte configurável, e a escolha final sai da ablação no
eval sobre o corpus estreito de 434 documentos, onde indexar custa minutos.

`model_id` carrega modelo, dimensão **e versão do fastembed** — a 0.8.0 mudou o
pooling do e5-large de CLS para média, o que altera todos os vetores sob o mesmo
nome de modelo. O índice guarda `model_id` por documento e reprocessa o que não
casar. É isso que permite trocar de modelo sem reindexar do zero por acidente.

### 4.3 Índice e retomabilidade

| Componente | Papel |
|------------|-------|
| **LanceDB** | Vetores densos + metadados para filtro. Arquivo local, sem servidor |
| **SQLite** | Registro de documentos, linhagem de chunks, FTS5 lexical, grafo derivado (F4) |

**Retomabilidade por documento.** A indexação processa documento a documento e
grava o registro ao final de cada um. Uma interrupção custa no máximo **um
documento**. Na retomada, um documento é pulado quando `(tamanho, mtime)` não
mudaram **e** o `model_id` e a versão do chunker são os mesmos. Reprocessamento
de um documento apaga seus chunks antes de reinserir, então é idempotente.

Isso é o que torna aceitável uma indexação de 39 h com o e5: roda em segundo
plano, em blocos, e pode ser interrompida e retomada sem perda.

---

## 5. Recuperação

```
1. consulta → embedding local (prefixo `query:` quando o modelo pede)
2. denso (LanceDB, cosseno) ‖ lexical (FTS5, bm25)   → fusão RRF → top ~50
3. reranking cross-encoder local (bge-reranker-v2-m3) → top ~8
4. expansão de contexto: seção completa + vizinhos
5. expansão pelo grafo derivado (F4): mesmo contrato, mesma pasta, entidade
```

Bi-encoder para revocação, cross-encoder para precisão. O reranker vê o par
(consulta, documento) junto e por isso julga relevância muito melhor que
similaridade de cosseno — é a diferença entre "a resposta está no top-50" e "a
resposta está no top-5".

Latência esperada por consulta: ~20-50 ms de embedding, poucos ms de busca,
0,3–1 s de reranking. **Zero chamada de API.**

---

## 6. Números do baseline e o que a escala faz

O baseline da F0 é busca por sobreposição de tokens em **nome de arquivo e
caminho de pastas**, sem abrir conteúdo. Sobre as 51 perguntas:

| Corpus | recall@1 | recall@10 | MRR@10 | multi-hop MRR |
|--------|---------:|----------:|-------:|--------------:|
| 434 documentos | 0,55 | 0,83 | 0,69 | 0,67 |
| 3.332 documentos | 0,48 | 0,81 | 0,62 | **0,29** |

**recall@10 de 0,83 com busca por nome de arquivo.** Não é sorte: as pastas são
organizadas e os nomes descritivos. Isso reposiciona o valor da F1 — o ganho não
virá de *achar o documento*, e sim de **achar o trecho** e de responder o que só
existe no conteúdo.

O experimento de escala foi medido com **uma variável por vez**, depois que a
primeira comparação deu um resultado impossível (uma pergunta melhorou com mais
distratores — o prefixo do caminho novo injetava tokens no conjunto dourado):

- **Escala degrada ranqueamento, não recuperação.** 7,7× mais documentos:
  recall@10 cai 5%, recall@1 cai 16%, MRR cai 13%.
- **Multi-hop colapsa: −57%.** Essas perguntas exigem *todas* as fontes no
  top-k, e trazer duas ao mesmo tempo fica muito mais difícil que trazer uma.
  É o argumento mais forte a favor do reranking (F2) e do `neighbors` (F4) — não
  como refinamento, mas como condição para multi-hop funcionar.

### Critério de saída da F1

O critério original — "recall@10 ≥ 2× o baseline" — foi descartado: o baseline
mediu 0,83 e o dobro não existe. Cinco portas, no corpus completo:

| # | Porta | Baseline |
|---|-------|---------:|
| 1 | recall@1 ≥ 0,80 | 0,48 |
| 2 | MRR@10 ≥ 0,80 | 0,62 |
| 3 | **casos-armadilha: recall@10 ≥ 0,85** | 0,50 |
| 4 | multi-hop MRR@10 ≥ 0,60 | 0,29 |
| 5 | Nenhuma regressão no que o baseline já acerta em primeiro | — |

A porta 3 é a que justifica a F1 existir. São 6 perguntas desenhadas para
quebrar busca por nome: sigla trocada no nome do arquivo (`AGCR` vs `ACGR`),
fornecedor que só aparece no conteúdo, versão vigente sem o maior `_vN`. Se ela
não passar, indexar conteúdo não valeu o esforço neste acervo — e é melhor
descobrir por medição.

---

## 7. Limites conhecidos

| Limite | Detalhe |
|--------|---------|
| Sem UI própria | A interface é o cliente MCP. Insuficiente para usuário final não-técnico |
| Sem automação | O Agent SDK exige API key; OAuth de assinatura é bloqueado. Digest agendado precisa de key própria |
| Índice herda o acesso de quem indexou | Não pode ser compartilhado antes do trabalho de ACL (F5). LGPD se aplica ao índice como aos documentos |
| Perguntas panorâmicas | "Temas recorrentes dos últimos 6 meses" não é recuperação por chunk. Fora de escopo; exigiria RAPTOR ou knowledge graph |
| PDF digitalizado | ~45 arquivos projetados. Marcados, não indexados. OCR é decisão à parte |
| MSG/EML e Office legado | 110 `.msg` e ~32 `.xls/.xlsb/.xlsm` sem parser. F4 |
| `.pst` | 3 arquivos, 17 GB de caixa postal. Excluídos: indexar caixa postal inteira tem implicação de privacidade própria |

---

## 8. Onde queremos revisão do time

1. **O esparso ser BM25 em vez de aprendido** é aceitável para o perfil de
   consulta de vocês? O caso crítico é sigla e código de contrato, onde BM25
   resolve; a dúvida é vocabulário aproximado.
2. **MiniLM 384 dim** é fraco frente ao e5-large. A ablação decide, mas se
   alguém já tem experiência com esses dois em português, o palpite informado
   economiza um ciclo de medição.
3. **Onde roda a indexação definitiva.** 39 h em segundo plano no notebook é
   aceitável pela retomabilidade, mas uma máquina com GPU faria em minutos e o
   índice é um arquivo — vale mover?
4. **A política de digesto de planilha** trata coluna de chave única com teto de
   8.000 valores. Alguém vê caso de uso em que isso quebra?
5. **A porta 3 do critério de saída** (armadilhas ≥ 0,85) é a mais exigente. Ela
   é a métrica certa para decidir se indexar conteúdo se pagou?

---

## 9. Como reproduzir os números

```bash
pip install -r requirements.txt
cp census.example.toml census.toml        # preencher as raízes

py -m segundocerebro.census --config census.toml --out docs/censo.md
py -m segundocerebro.ingest.report --amostra 220 --out docs/ingestao-f1.md
py -m eval.rodar --out docs/metricas-f0.md
py -m pytest tests/ eval/ -q              # 89 testes
```

Documentos relacionados: `ARCHITECTURE.md` (registro de decisões, com as
correções datadas), `ROADMAP.md` (fases e critérios de saída),
`docs/escala-f0.md` (experimento de escala), `eval/golden/README.md` (formato do
conjunto dourado).
