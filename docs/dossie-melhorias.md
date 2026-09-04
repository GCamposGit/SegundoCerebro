# Dossiê de Melhorias — Segundo Cérebro
**Data:** 2026-08-24 · **Origem:** avaliação externa completa do repositório + pesquisa de melhores práticas por componente
**Alvo de produto:** indexar acervos genéricos de ~1 TB / centenas de milhares de arquivos / décadas de formatos, 100% local, instalação por usuário leigo, produto = servidores MCP que abastecem o LLM do cliente.

> **Conferido contra o índice real em 24/08/2026** (2.156 documentos, 98.326
> trechos). Sete premissas foram medidas: quatro batem, **três não** — a escala
> do corpus dev está 8× desatualizada, `.pytest_cache/` **não** está versionado,
> e os dois subconjuntos que o dossiê aponta como fracos (perguntas do usuário e
> temporais) são na verdade os **mais fortes**. A tabela com os números, a
> dependência que faltava (`F4-D`: o dourado alcança de 3,3% a 38,5% do índice,
> piso exato e teto por pasta, e destrava cinco
> destes pacotes) e a ordem revisada estão em `ROADMAP.md`, seção "O dossiê de
> melhorias, conferido contra o índice real". **Ler as duas coisas juntas.**
>
> O texto abaixo fica como está: é a avaliação externa, e reescrevê-la apagaria a
> diferença entre o que foi recomendado e o que a medição respondeu.

---

## Como usar este documento (instrução para Claude Code / Grok Build)

- Cada recomendação é um **pacote** autocontido no formato `R<seção>.<n>`, análogo aos pacotes F4-L/F4-M do ROADMAP: **um pacote = uma branch = um PR**, com número antes/depois quando tocar ranking.
- O campo **Dono sugerido** respeita a tabela de donos vigente (`docs/colaboracao.md` §1): `desktop` = hardware/CUDA/indexer/parsers legados; `notebook` = retrieve/pesos/eval no dourado real; `qualquer` = neutro. Se um pacote cruzar a fronteira, dividir em dois PRs.
- **Nenhum pacote muda `model_id`, chunking padrão ou `[padrao]` sem acordo entre os dois setups** (rebuilda índice — invariante existente).
- Prioridades: **P0** = bloqueia o alvo de produto; **P1** = grande alavanca; **P2** = melhoria; **P3** = registrar e não fazer agora.
- Ordem de ataque sugerida ao final (§12).

---

## 0. Diagnóstico-síntese (contexto para qualquer sessão)

O que já está certo e **não deve ser mexido sem número**: arquitetura MCP-não-aplicação; RRF por posição; SQLite FTS5 + LanceDB embedded; fingerprint `model_id` com versão do fastembed; orçamento de chunk pelo tokenizer real; disciplina de ablação.

Os quatro riscos estruturais que este dossiê ataca:

1. **Escala não testada** — corpus dev: 434 docs / 11.208 chunks / ~13k vetores. Alvo: ~1000×. LanceDB hoje busca flat (exato, mas O(n)); FTS5 sem `optimize` fragmenta; nenhuma porta de latência existe.
2. **Overfitting ao acervo dev** — pesos (denso 1.0 / lexical 0.25 / nome 0.5) varridos num acervo onde nome de arquivo é sinal excepcional. Base genérica (`IMG_2034.pdf`) quebra essa premissa.
3. **Produto para leigo inexistente** — hoje exige Python 3.12, PYTHONPATH, TOML. `pyproject.toml` declara `dependencies = []` enquanto o CI usa `requirements.txt`.
4. **Décadas de arquivos = legado + OCR + versões duplicadas** — `.ppt/.doc/.xls`, PDF escaneado (g015/g025/g048 já falham por isso) e `_v3_final_FINAL(2)` em 8 cópias afogando o top-k.

---

## 1. Ingestão e Parsing

### R1.1 — Conversor universal de legado via LibreOffice headless — **P0** · Dono: desktop
**Problema.** `ole_texto.py` extrai texto cru de OLE mas perde estrutura (slides, tabelas, cabeçalhos). Décadas de acervo = `.ppt`, `.doc`, `.xls` em volume; texto sem estrutura degrada chunking e rerank.

**Solução.**
1. Novo módulo `ingest/converters/libreoffice.py`:
   - Detecção do binário: `shutil.which("soffice")` + caminhos padrão Windows (`C:\Program Files\LibreOffice\program\soffice.exe`) e macOS/Linux. Cachear resultado no censo.
   - Conversão em lote por diretório temporário: `soffice --headless --norestore --convert-to pptx --outdir <tmp> <arquivos...>` (idem `docx`, `xlsx`). Lotes de ~50 arquivos por processo; LibreOffice tem vazamentos em lotes longos — reiniciar o processo por lote.
   - Timeout por lote (ex.: 120 s + 10 s/arquivo); arquivo que estourar vai para quarentena (R1.4) e cai no fallback.
2. No despachante (`parsers/__init__.py` — **combinar antes, é "um de cada vez"**): rota `.ppt/.doc/.xls` → converter → parser moderno correspondente; fallback = `ole_texto.py` atual quando LibreOffice ausente ou conversão falhar.
3. O documento indexado referencia o **arquivo original** (path, mtime, hash); o convertido é efêmero. `parser_version` do doc muda quando a rota muda (o mecanismo de re-parse existente cuida do resto).
4. Wizard/instalador (R8.2) oferece instalar LibreOffice ou seguir sem (modo degradado explícito no relatório do censo).

**Critérios de aceite.** Corpus sintético ganha ≥10 arquivos `.ppt/.doc/.xls` reais (gerados pelo próprio LibreOffice a partir dos sintéticos); parser extrai título+corpo por slide e planilha com cabeçalho; suíte padrão passa sem LibreOffice instalado (fallback testado com mock); nenhum processo `soffice` órfão após a onda (verificar em teste de integração).

**Fontes.** LibreOffice headless conversion (`--convert-to`, documentação oficial CLI); prática padrão em pipelines de ingestão enterprise (Unstructured — RAG pipeline best practices: https://unstructured.io/insights/rag-pipeline-best-practices-enterprise).

---

### R1.2 — OCR local em onda de baixa prioridade — **P0** · Dono: desktop (pipeline) + notebook (medição no dourado)
**Problema.** g015/g025/g048 falham: PDF digitalizado sem texto. Em acervos corporativos antigos, 10–30% dos PDFs são imagem. O produto não pode declarar esses documentos inexistentes.

**Solução.**
1. Detecção (barata, no parser de PDF atual): página com < N chars extraíveis e ≥1 imagem grande ⇒ marcar doc `precisa_ocr` na tabela `documentos` (nova coluna). Não OCRizar inline — apenas marcar.
2. Nova onda de prioridade mínima no `prioridade.py`: consome fila `precisa_ocr` depois de todas as ondas de texto. Encaixa na filosofia "benefício desde o dia 1": o texto fácil fica pesquisável primeiro.
3. Motor: `ingest/ocr.py` com backend plugável:
   - **RapidOCR (ONNX)** como padrão — roda no onnxruntime já presente, CPU, sem dependência de sistema;
   - Tesseract como alternativa se detectado instalado (melhor em página inteira de texto denso);
   - Interface única `ocr_pdf(path) -> list[PaginaTexto]` para trocar backend sem tocar o indexador.
4. Saída OCR entra no pipeline normal de chunking com metadado `fonte="ocr"` (permite ao rerank/painel diagnosticar qualidade) e `parser_version` própria.
5. Orçamento: OCR respeita o orçamento adaptativo de recursos (R5.2); páginas em paralelo limitadas por RAM.

**Critérios de aceite.** g015, g025 e g048 saem da lista "fora de escopo" e entram no dourado com número; recall@5 do trio ≥ 2/3; onda OCR nunca roda antes de existir onda de texto pendente; indexação com OCR desligado por config continua idêntica à atual.

**Fontes.** RapidOCR (https://github.com/RapidAI/RapidOCR); pipelines OCR+RAG locais em hardware de consumo (ResearchGate 2025: https://www.researchgate.net/publication/399889491); Docling também embute OCR se R1.5 for adotado.

---

### R1.3 — Deduplicação e famílias de versões — **P0** · Dono: notebook (ranking) + desktop (censo/hash)
**Problema.** Base real de décadas tem o mesmo documento em 5–15 variantes (`v2`, `final`, `FINAL(2)`, cópias em pastas de backup). Sem tratamento: (a) custo de indexação multiplicado; (b) top-k afogado em quase-duplicatas — o pior modo de falha possível para "confiável em trazer informação relevante".

**Solução.**
1. **Dedup exato (censo, barato):** hash de conteúdo `xxhash.xxh3_128` durante o censo. Documento = conteúdo; caminhos = lista. Indexa 1×, tabela `documentos` ganha `hash_conteudo` e tabela nova `caminhos(doc_id, path, mtime)`. `search` devolve o caminho preferido (mais recente/mais raso); `neighbors` pode listar os demais.
2. **Near-duplicate (pós-parse):** MinHash sobre shingles do texto extraído (lib `datasketch`, `MinHashLSH` com threshold ~0.85). Pares acima do limiar formam **família de versões** — conceito que `retrieve/familias.py` já iniciou; estender, não recriar.
3. **Política de ranking por família (notebook, com ablação):**
   - membro canônico = mtime mais recente (desempate: caminho mais raso);
   - na fusão, membros não-canônicos recebem penalidade multiplicativa no score RRF (sugestão inicial 0.3 — **varrer**);
   - o resultado exibe o canônico com anotação `versoes: n` e ids das demais, acessíveis via `read_note`/`neighbors`.
4. **Não** deletar nada do índice: versões antigas continuam alcançáveis por consulta explícita (filtro de data de R6.3) — "qual era a versão de 2019?" é pergunta legítima.

**Critérios de aceite.** Corpus sintético ganha grupos de versões plantados (mesmo doc com edições de 5/15/40%); métrica nova no harness: **duplicatas no top-10** (mesma família contada 1×) — meta: ≤1 membro extra por família; recall do dourado real não cai (número antes/depois); tempo de censo em 100k arquivos cresce <15% com hashing.

**Fontes.** MinHash/LSH para near-dup em escala (Broder; implementação `datasketch`: https://ekzhu.com/datasketch/); prática de dedup em ingestão enterprise (Unstructured, link acima).

---

### R1.4 — Quarentena de arquivos venenosos — **P1** · Dono: desktop
**Problema.** Em 300k arquivos de máquina desconhecida, a probabilidade de um PDF corrompido travar/derrubar o parser é ~1. Uma onda de dias não pode morrer no arquivo 180.412.

**Solução.**
1. Parsing de formatos binários (PDF, OLE, OCR, conversão) roda em **subprocesso** com timeout por arquivo (padrão: 60 s + 10 s/MB) e limite de RAM (Windows: Job Objects via `pywin32`; POSIX: `resource.setrlimit`).
2. Falha/timeout/estouro ⇒ registro na tabela nova `quarentena(path, hash, motivo, tentativas, ultima_tentativa)`; o arquivo é pulado nas ondas seguintes (máx. 2 retentativas com backoff).
3. Relatório do censo/painel expõe a quarentena ("14 arquivos não puderam ser lidos — ver lista"); usuário leigo nunca vê stack trace.
4. Crash do subprocesso não polui o log principal com mais de uma linha; detalhe vai para log dedicado.

**Critérios de aceite.** Teste com PDF truncado, ZIP renomeado para .docx e arquivo de 0 bytes: onda completa, 3 itens em quarentena, zero exceções não tratadas; indexador sobrevive a `kill -9` do subprocesso.

---

### R1.5 — Docling como caminho de qualidade para PDFs difíceis — **P2** · Dono: desktop
**Problema.** PDFs com layout complexo (tabelas, colunas duplas) perdem estrutura no parser atual.

**Solução.** Rota opcional no despachante: PDFs marcados "difíceis" (heurística: densidade de tabela, colunas detectadas) vão para **Docling** (projeto open-source, MIT license) que produz Markdown estruturado; demais seguem no parser rápido atual. Docling é dependência opcional (`pip install segundocerebro[docling]`) — pesado demais para o pacote base. Medir no dourado antes de promover a padrão.

**Fontes.** Docling (https://github.com/docling-project/docling; paper: https://arxiv.org/html/2501.17887v1); alternativa leve: MarkItDown (https://github.com/microsoft/markitdown).

---

## 2. Chunking

### R2.1 — Contexto de documento no texto embeddado — **P1** · Dono: acordo entre setups (muda vetores!)
**Problema.** Chunk embeddado hoje carrega heading trail + nome do arquivo. A versão barata do "Contextual Retrieval" (Anthropic mediu ~49% menos falhas de retrieval com contexto por chunk) pode ir além sem LLM: **o caminho da pasta é metadado semântico que décadas de organização humana criaram de graça** (`01. Inteligência Artificial/Política de IA/...`).

**Solução.**
1. `embedding_text()` passa a compor: `pasta relativa (últimos 2-3 níveis) · nome do doc · heading trail · data do doc (ano) · texto`. Orçamento: contexto ≤ 15% do budget de tokens do chunk (o tokenizer real já é enforced — reutilizar).
2. Normalizar a pasta: remover números de ordenação (`01.`, `2023_`), underscores → espaços (mesma lógica de `nome_documento()`).
3. **Atenção:** muda todos os vetores ⇒ exige rebuild ⇒ `parser_version`/`model_id` bump coordenado. Fazer junto com a ablação de modelo (R3.1) para pagar o rebuild uma vez só.
4. Ablação obrigatória: com/sem pasta, com/sem ano, no dourado real e no sintético. Registrar em `docs/ablacao-contexto-chunk.md`.

**Critérios de aceite.** MRR@10 no dourado real não cai em nenhuma origem de pergunta; casos "escritas pelo usuário" (hoje o subconjunto mais fraco: recall@1 0.500) melhoram ou empatam.

**Fontes.** Anthropic — Contextual Retrieval: https://www.anthropic.com/news/contextual-retrieval; Late chunking como alternativa futura (arXiv:2409.04701).

---

### R2.2 — Chunk de rota para planilhas grandes — **P2** · Dono: desktop (parser sheets é dele)
**Problema.** XLS de 50 MB com 30 abas vira centenas de chunks-janela; nenhum deles diz ao LLM "esta planilha existe e é sobre X".

**Solução.** `sheets.py` emite, além das janelas, **um chunk-sumário por aba**: nome do arquivo, nome da aba, cabeçalhos, nº de linhas, 2 linhas de amostra. Marcado `natureza="rota"`. O LLM encontra a rota via busca e usa `read_note`/janelas para aprofundar. Custo: +1 chunk/aba.

**Critérios de aceite.** Pergunta sintética "existe planilha com dados de X?" acerta a rota no top-5; número de chunks totais cresce <2%.

---

## 3. Embeddings

### R3.1 — Ablação BGE-M3 vs e5-large (e arctic-embed-l-v2.0) — **P0** · Dono: desktop roda, notebook mede
**Problema.** e5-large (1024d, janela 512) é sólido mas 2023. BGE-M3: janela 8192, multilíngue forte em PT, denso+esparso+ColBERT no mesmo checkpoint. A infra de `ModelSpec`+fingerprint torna o teste barato — e o modelo deve ser congelado **antes** do empacotamento do produto.

**Solução.**
1. Adicionar ao catálogo `MODELOS`: `bge-m3` (1024d) e `arctic-embed-l-v2.0` (1024d, suporta MRL). Conferir no pacote: janela real, pooling, prefixos de query/passage (bge-m3 **não** usa prefixo; arctic usa `query: ` — mesmo tipo de armadilha que o e5 já ensinou).
2. Rodar a matriz no sintético (desktop, GPU) e depois o vencedor no dourado real (notebook): MRR/recall/nDCG + **tempo de indexação + RAM**.
3. Se bge-m3 vencer: registrar decisão; o sinal esparso/ColBERT dele fica como experimento futuro (R6.4), não entra agora.
4. Publicar `docs/ablacao-modelo-2026.md` no padrão existente.

**Critérios de aceite.** Decisão com número nas duas bases; nenhum vazamento de nome real; `model_id` novo com dim+versão fastembed correta.

**Fontes.** BGE-M3: https://huggingface.co/BAAI/bge-m3; MTEB multilingual retrieval: https://huggingface.co/spaces/mteb/leaderboard; Snowflake arctic-embed-l-v2.0: https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0.

---

### R3.2 — Indexação em dois passes (rascunho → final) — **P0** · Dono: desktop
**Problema.** e5-large: ~39 h para 434 docs na GPU disponível. Extrapolando para 300k arquivos: meses. O requisito é "pode demorar dias, mas oferece benefício enquanto não termina".

**Solução.** O `model_id` por documento **já suporta** múltiplos modelos convivendo — é feature quase pronta:
1. Config nova: `[indexacao] modelo_rascunho = "minilm"` (opcional). Passe 1: tudo com MiniLM (≈20× mais rápido) — busca funcional em horas.
2. Passe 2 (background, mesmas ondas de prioridade): re-embed com o modelo final; o mecanismo de reconciliação por `model_id` divergente já faz o trabalho.
3. **Regra dura na consulta:** nunca fundir rankings densos de modelos diferentes (espaços incomparáveis). A busca densa usa **um** modelo por vez: o final onde disponível; documentos ainda só-rascunho entram por uma segunda consulta densa no espaço rascunho, fundida via RRF **por posição** (RRF não olha score — é exatamente o caso de uso). Implementar como 4º ranking temporário que desaparece quando o passe 2 termina.
4. Painel/relatório mostra: "busca completa em N% do acervo; qualidade final em M%".

**Critérios de aceite.** Com rascunho ligado: primeira resposta útil (recall@10 ≥ 70% do valor final no sintético) em <10% do tempo total; ao fim do passe 2 o índice é byte-idêntico ao de passe único (mesmos vetores finais); trava de escrita respeitada entre passes.

---

### R3.3 — Quantização de vetores (INT8 agora, binário+rescore depois) — **P0** · Dono: desktop
**Problema.** 1 TB de docs ⇒ 5–20M chunks ⇒ 20–80 GB de float32 em 1024d. Não cabe no notebook do leigo.

**Solução.**
1. **Fase A (agora):** quantização escalar INT8 no LanceDB (suportada nativamente) — 4× menor, perda <1% de recall. Ligar por padrão acima de um limiar de chunks.
2. **Fase B (quando R4.1 estiver estável):** binário + rescoring — vetor binário para o ANN (32× menor), re-score dos top-200 candidatos com os vetores INT8/float mantidos em disco frio. Recupera ~95%+ do recall.
3. Se o modelo vencedor de R3.1 suportar MRL (arctic): avaliar truncagem 1024→512d antes de quantizar (combinação MRL+binário é o estado da arte de custo).
4. `model_id` ganha sufixo de esquema de quantização — mesmo raciocínio do fingerprint atual.

**Critérios de aceite.** Recall@10 no sintético ≥ 99% (INT8) / ≥ 95% (binário+rescore) do float32; RAM de consulta medida antes/depois; documento `docs/ablacao-quantizacao.md`.

**Fontes.** Qdrant — binary quantization: https://qdrant.tech/articles/binary-quantization-openai/; CoRECT (arXiv:2510.19340); Vespa — Matryoshka+BQ: https://blog.vespa.ai/combining-matryoshka-with-binary-quantization-using-embedder/; Milvus — MRL: https://milvus.io/blog/matryoshka-embeddings-detail-at-multiple-scales.md.

---

## 4. Armazenamento e Índice

### R4.1 — Índice ANN automático no LanceDB — **P0** · Dono: desktop
**Problema.** Hoje a busca vetorial é flat (exata). Em 5–20M vetores, latência vai a segundos/minutos. O leigo não pode (e não deve) decidir "criar índice IVF-PQ".

**Solução.**
1. `store.py`: após cada onda, se `n_vetores > LIMIAR` (sugestão: 200k) e não há índice ANN válido ⇒ criar `IVF_PQ` (partições ≈ `4*sqrt(n)`, PQ subvetores = dim/8; treinar na GPU se disponível). Abaixo do limiar: flat, como hoje.
2. Recriar o índice quando o nº de vetores crescer >30% desde o último treino (senão só append — Lance suporta).
3. **Compaction** agendada pós-onda grande (`table.compact_files()` + limpeza de versões antigas) — fragmentação de versões degrada leitura.
4. Métrica de guarda: amostra de 100 consultas do harness comparando ANN vs flat — recall@20 do ANN ≥ 0.95 do flat, senão aumentar `nprobes` automaticamente.
5. Nada disso aparece em config de usuário; painel de dev pode inspecionar.

**Critérios de aceite (revistos em 04/09/2026).** Em índice sintético inflado (≥1M vetores — gerar por perturbação dos existentes): recall-vs-flat ≥0.95; rebuild automático disparado no teste de crescimento; latência entra no orçamento fim a fim de `search` em `R9.3`. A antiga meta isolada de 150 ms foi retirada: não derivava de uma necessidade do usuário e não garantia a experiência completa.

**Fontes.** LanceDB IVF-PQ / escala: https://www.lancedb.com/blog/how-lancedb-accelerates-vector-search-at-10-billion-scale; docs LanceDB ANN index.

---

### R4.2 — Higiene FTS5 e SQLite para milhões de linhas — **P1** · Dono: desktop
**Solução (checklist).**
1. Inserções de onda em transações grandes (já parcialmente feito — auditar tamanho de lote; alvo: 5–10k chunks/commit).
2. `INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')` ao fim de cada onda; `PRAGMA incremental_vacuum` periódico.
3. `PRAGMA mmap_size` e `cache_size` dimensionados pelo orçamento de RAM (R5.2).
4. Medir tamanho do `registro.db` no relatório do censo; alertar no painel acima de N GB.
5. **Registrar como decisão (não fazer):** migração para Tantivy só se o BM25 do FTS5 medir como gargalo em 5M+ chunks. Anotar em `docs/` para não re-discutir.

**Critérios de aceite (revistos em 04/09/2026).** Checklist implementado; tempo de onda não regride >10%; qualidade lexical não cai; latência entra no orçamento fim a fim de `search` em `R9.3`. A antiga meta isolada de 100 ms foi retirada: no corpus inflado adversarial exigiria outra classe de motor/algoritmo, sem evidência de que o produto precise dela. Tantivy só volta à pauta pelo gatilho já definido de 5M+ chunks ou por ruptura do orçamento fim a fim em corpus representativo.

---

### R4.3 — Sharding interno por sub-árvore — **P3** · registrar apenas
Uma `[[base]]` com 1 TB pode dividir-se internamente em shards por sub-árvore de pastas, com fusão RRF entre shards na consulta. Só atacar se R4.1+R4.2 não bastarem. Documentar a opção em `ARCHITECTURE.md` §5 (limites conhecidos) para não perder o raciocínio.

---

## 5. Indexação incremental e resiliência

### R5.1 — Watcher com hierarquia USN Journal → watchdog → reconciliação — **P1** · Dono: desktop (pacote F4-W já é dele)
**Problema.** Watchdog/`ReadDirectoryChangesW` perde eventos em árvores gigantes e estoura buffer. É como o Everything indexa 1M arquivos instantaneamente: **NTFS USN Journal**.

**Solução.**
1. `index/watcher.py` com três camadas:
   - **USN Journal** (Windows+NTFS+privilégio): ler o journal desde o último USN persistido — pega tudo que mudou mesmo com o programa fechado. `pywin32`: `DeviceIoControl(FSCTL_READ_USN_JOURNAL)`.
   - **watchdog** (fallback universal): para volumes não-NTFS/sem privilégio.
   - **Reconciliação periódica** (`reconciliar.py` já existe): rede de segurança diária — nenhum evento perdido vira permanente.
2. Eventos alimentam a fila de ondas com prioridade "modificado recentemente" (encaixa em R5.3/`prioridade.py`).
3. Debounce por arquivo (Office salva 3× em 2 s).

**Critérios de aceite.** Teste: modificar 1k arquivos com o watcher desligado ⇒ ao religar, USN recupera todos; fallback watchdog testado em tmpfs; reconciliação pega arquivo alterado com watcher morto.

**Fontes.** Microsoft — Change Journals: https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals.

---

### R5.2 — Orçamento adaptativo de recursos — **P0** · Dono: desktop
**Problema.** "Pode demorar dias" só é aceitável se o notebook do leigo continuar usável. Hoje o indexador toma o que houver. Usuário leigo com ventoinha a 100% por 3 dias = desinstalação.

**Solução.**
1. `index/orcamento.py`: no arranque, medir núcleos, RAM livre, GPU (o smoke CUDA já existe) ⇒ derivar `n_workers`, tamanho de lote de embedding, paralelismo de parsing.
2. Modo cidadão: prioridade de processo `BELOW_NORMAL` + I/O priority low (Windows: `SetPriorityClass`/`SetThreadIoPriority`; POSIX: `nice`/`ionice`).
3. Sensores em runtime (a cada N lotes): usuário ativo (input recente) ⇒ reduzir workers; em bateria ⇒ pausar embedding pesado, manter censo; RAM livre < limiar ⇒ reduzir lote.
4. Config expõe só três presets para o leigo: `automatico` (padrão) / `noturno` (tudo) / `discreto` (mínimo).

**Critérios de aceite.** Em máquina de 8 GB simulada (limitar via Job Object no teste): onda completa sem OOM; com "usuário ativo" simulado, uso de CPU do processo cai >50% em <30 s.

---

### R5.3 — Prioridade generalizada + estimativa calibrada online — **P1** · Dono: desktop
**Problema.** As heurísticas de `prioridade.py` e a calibração de `estimativa.py` nasceram no acervo/hardware dev. Máquina e acervo desconhecidos exigem generalização.

**Solução.**
1. Prioridade como função documentada e testável: `score = w_recencia*f(mtime) + w_raso*f(profundidade) + w_tipo*f(extensão) + w_tamanho*f(bytes)` — tipos de alto valor (docx/pdf/md pequenos) antes de xls de 50 MB. Pesos em constante única com docstring de justificativa (padrão da casa).
2. Estimativa: calibrar nos primeiros 500 arquivos processados da máquina real (chars/s de parse, chunks/s de embed) e reprojetar continuamente; exibir sempre intervalo ("entre 18 h e 30 h"), nunca ponto.
3. Relatório de progresso orientado a benefício: "os 20% mais recentes do acervo já estão pesquisáveis".

**Critérios de aceite.** Estimativa após 500 arquivos erra <40% do tempo real no corpus sintético; ordem de indexação num acervo de teste começa pelos docs mais recentes/rasos.

---

## 6. Retrieval

### R6.1 — Auto-tuning de pesos por acervo (a feature que mata o overfitting) — **P0** · Dono: notebook
**Problema.** Pesos globais (1.0/0.25/0.5) são o resultado de varredura **neste** acervo, onde nome de arquivo é sinal forte. Num acervo genérico o peso de nome pode ser ruído puro. Pesos fixos = a maior ameaça à generalização do produto.

**Solução.**
1. Tratar os pesos atuais como **prior de fábrica**, não constante.
2. Pipeline `eval/autotune.py`, rodado automaticamente ao fim da indexação inicial (e sob demanda):
   - `eval/sintetico/gerar.py` **já gera perguntas de corpus** — generalizar para amostrar do acervo real do usuário (N≈60 perguntas: exatas por identificador encontrado, semânticas por parágrafo, por nome de arquivo);
   - varredura leve de pesos (grade grossa 0/0.25/0.5/1.0 nos 3–4 ranqueadores — o `varredura.py` já sabe fazer);
   - persistir pesos vencedores na config da base com procedência (`ajustado_em`, `n_perguntas`, MRR obtido);
   - guarda-corpo: se o MRR da grade toda variar <5%, manter prior de fábrica (acervo não discrimina — não sobreajustar).
3. Painel mostra os pesos e o número que os justificou; leigo nunca precisa abrir.
4. **Privacidade:** perguntas geradas ficam locais, gitignoradas — mesma disciplina do `perguntas.jsonl`.

**Critérios de aceite.** Em dois acervos sintéticos com características opostas (nomes informativos vs `IMG_xxxx`), o autotune converge para pesos distintos e MRR ≥ prior em ambos; no acervo dev, autotune reencontra ±1 passo da configuração campeã da varredura de 13/08.

**Fontes.** RRF robusto sem calibração de scores (Cormack et al., SIGIR'09: https://dl.acm.org/doi/10.1145/1571941.1572114); dependência de corpus dos pesos de fusão (arXiv:2508.01405: https://arxiv.org/html/2508.01405v2).

---

### R6.2 — Reranker: bge-reranker-v2-m3 + mais candidatos — **P1** · Dono: notebook
**Problema.** `bge-reranker-base` com 10 candidatos é conservador; rerank é a maior alavanca de precisão já constatada pela própria F2.

**Solução.**
1. Adicionar `BAAI/bge-reranker-v2-m3` ao catálogo (multilíngue, sucessor direto); variante ONNX INT8 para CPU.
2. Varrer `rerank_candidatos` ∈ {10, 20, 30, 50} × latência p95. Meta de produto: rerank de 30 candidatos <500 ms em CPU de 4 núcleos.
3. Manter a decisão existente de rerankear `nome + trilha + trecho` (correta e incomum — não regredir).
4. Latência entra como coluna obrigatória na tabela de ablação (prepara R9.3).

**Critérios de aceite.** `docs/ablacao-rerank-v2.md` com MRR e p95 por (modelo × candidatos); escolha de produto justificada pelos dois eixos.

**Fontes.** bge-reranker-v2-m3: https://huggingface.co/BAAI/bge-reranker-v2-m3; referência híbrido+rerank 2026: https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026.

---

### R6.3 — Tempo e pasta como dimensões de primeira classe — **P1** · Dono: notebook
**Problema.** Décadas de acervo tornam "a mais recente" e "a de 2019" consultas centrais. Hoje o LLM cliente não tem como expressá-las.

**Solução.**
1. Tool `search` ganha parâmetros opcionais `depois de`/`antes de` (ISO date, filtra por mtime/data extraída) e `pasta` (prefixo de caminho relativo). Filtro aplicado **antes** da fusão (no SQL e no filtro do LanceDB — `where` já suportado).
2. Boost de recência **apenas dentro de famílias de versões** (R1.3) — nunca global: documento antigo ainda é a resposta certa às vezes.
3. Descrições da tool ensinam o LLM: "para 'mais recente', use depois_de com o último ano e peça ordenação por data".

**Critérios de aceite.** Perguntas temporais do dourado (hoje recall@1 0.500) melhoram; g010 ("versão vigente da Política de IA") é o caso-teste nominal.

---

### R6.4 — Sinal ColBERT/esparso do BGE-M3 como 4º ranqueador — **P3** · registrar
Se R3.1 escolher bge-m3, o checkpoint oferece multi-vector e esparso de graça. Experimento futuro com ablação; não entra antes de R4.1 (custo de armazenamento multi-vector).

---

## 7. Superfície MCP

### R7.1 — Tools de navegação e visão geral — **P1** · Dono: notebook
**Problema.** `search/read_note/neighbors` cobre busca pontual. LLMs agênticos rendem mais com ferramentas de **orientação** — reduz buscas às cegas em acervo de 300k arquivos.

**Solução.** Três tools novas, todas read-only e baratas (SQL puro):
1. `overview()` — o que há na base: nº docs/chunks, período coberto (min/max data), top formatos, top pastas de 1º nível, % indexado, % OCR pendente. É a primeira chamada que qualquer agente deveria fazer.
2. `browse(pasta, limite)` — lista sub-pastas e docs indexados sob um prefixo (nome, data, nº chunks). O LLM navega a árvore.
3. `timeline(consulta, granularidade)` — histograma temporal dos hits de uma busca ("as menções a Aurora concentram-se em 2024-T4→2025-T2"). Implementação: a própria busca híbrida + GROUP BY período.

**Critérios de aceite.** As três respondem <200 ms em índice de 1M chunks; testes de contrato no padrão de `test_mcp.py`; nenhuma expõe caminho absoluto da máquina (paths relativos à base).

---

### R7.2 — Descriptions das tools como UX do produto — **P1** · Dono: notebook
**Problema.** O usuário leigo nunca lê docs; **o LLM lê as descriptions** — elas são a homepage do produto.

**Solução.** Reescrever cada description com: quando usar / quando NÃO usar / 2 exemplos de chamada boa / formato do retorno / limites (k máx, janela máx). Testar empiricamente: sessões reais no Claude Desktop medindo se o agente escolhe a tool certa sem prompt de sistema. Tratar como ablação (registrar variantes e comportamento em `docs/ablacao-descriptions.md` — é barato e ninguém faz).

---

### R7.3 — Orçamento de resposta e progresso — **P2** · Dono: notebook
**Solução.**
1. `search` devolve por padrão snippets curtos (≤400 chars) + id + procedência; texto integral só via `read_note`. Parâmetro `detalhe: "snippet"|"completo"` com teto duro de tokens por resposta (proteger clientes de contexto pequeno).
2. Emitir `notifications/progress` do MCP durante indexação ativa; incluir no retorno de `overview` o estado ("indexação: 34%, busca já disponível — qualidade final em 61% do acervo").

**Fontes.** MCP spec: https://modelcontextprotocol.io/specification.

---

## 8. Distribuição e UX do leigo

### R8.1 — Consolidar empacotamento Python (pré-requisito de tudo) — **P0** · Dono: desktop (pacote F6-A já é dele)
**Problema.** `pyproject.toml` declara `dependencies = []`; CI instala de `requirements.txt`; execução exige PYTHONPATH. Nenhum empacotamento é possível sobre isso.

**Solução.**
1. Migrar dependências para `[project.dependencies]` com pins de compatibilidade (`fastembed>=0.8,<0.9` — a lição do pooling CLS→mean já foi paga); `requirements.txt` vira lockfile gerado (`pip-compile`) usado só no CI.
2. Extras: `[gpu]` (onnxruntime-gpu), `[ocr]` (rapidocr), `[docling]`.
3. `pip install segundocerebro` + `segundocerebro-mcp --base <nome>` funcionando sem PYTHONPATH (entry points já existem — validar em venv limpa nos 3 SOs).
4. CI ganha matriz `ubuntu-latest` + `macos-latest` (usuários de Mac são fatia grande do público Claude Desktop) e um job que instala o wheel e roda smoke.

**Critérios de aceite.** `pip install` + comando único sobe o servidor em Windows/macOS/Linux em venv limpa; CI verde na matriz 3×SO.

---

### R8.2 — MCPB one-click + wizard de primeira execução — **P0** · Dono: qualquer (depende de R8.1)
**Problema.** O gap nº 1 entre projeto e produto. O leigo precisa de: baixar → duplo clique → escolher pasta → ver progresso → usar.

**Solução.**
1. **Empacotar como MCPB** (MCP Bundle, ex-DXT — formato Anthropic de instalação one-click no Claude Desktop): manifest + servidor + Python embutido (python-build-standalone) ou binário PyInstaller. Um `.mcpb`, duplo clique, Claude Desktop instala e configura sozinho.
2. **Wizard de primeira execução** (pode ser o painel existente em modo assistente, 4 telas):
   - T1: escolher pasta(s) do acervo;
   - T2: detecção de hardware (reusar smoke CUDA + orçamento R5.2) → recomendação de modelo/preset em linguagem leiga ("seu computador indexará ~40 GB/dia");
   - T3: opcionais detectados (LibreOffice? OCR?) com um botão;
   - T4: barra de progresso orientada a benefício (R5.3) + "pode fechar, continuamos em background".
   - O wizard escreve toda a config; **o usuário nunca vê um TOML**.
3. Para clientes MCP não-Claude: publicar no **MCP Registry** oficial + `uvx segundocerebro` como caminho de usuário técnico.
4. Atualizações: verificação de versão no arranque (opcional, sem telemetria — invariante de privacidade).

**Critérios de aceite.** Teste de corredor: pessoa não-técnica instala e faz a primeira pergunta em <10 min sem ajuda; desinstalação limpa documentada.

**Fontes.** Anthropic — Desktop Extensions/MCPB: https://www.anthropic.com/engineering/desktop-extensions; distribuição de servidores MCP: https://www.speakeasy.com/mcp/distributing-mcp-servers/; MCP Registry: https://github.com/modelcontextprotocol/registry.

---

## 9. Avaliação

### R9.1 — Golden sets sintéticos multi-perfil — **P1** · Dono: qualquer
**Problema.** O dourado real mede um acervo corporativo específico. Produto genérico exige regressão em perfis diversos.

**Solução.** Estender `eval/sintetico/gerar.py` para gerar **perfis parametrizados** de corpus+perguntas: `juridico` (contratos, cláusulas, versões), `financeiro` (planilhas pesadas), `pessoal` (fotos+docs mistos, nomes ruins tipo `Scan_001.pdf`), `engenharia` (relatórios técnicos, siglas). Cada perfil: ~80 docs, ~40 perguntas, com armadilhas plantadas (near-dups de R1.3, nomes não-informativos). CI roda o perfil mais barato; a matriz completa roda pré-release.

**Critérios de aceite.** 4 perfis gerados e versionados (geradores, não os corpora); autotune (R6.1) validado contra eles.

---

### R9.2 — Regressão neutra com benchmark público — **P2** · Dono: notebook
**Solução.** Subconjunto PT do MIRACL (https://huggingface.co/datasets/miracl/miracl) como harness adicional: nenhum dos dois setups "possui" esse número, e mudanças de modelo/pesos ganham um árbitro externo. Rodar só nas portas de fase (é lento), não no CI.

---

### R9.3 — Latência como porta de fase — **P0** · Dono: notebook define a porta, desktop fornece o índice grande
**Problema.** "Rápido, para não ficar perdido em buscas enormes" é requisito do usuário — e hoje nenhuma porta o mede. Sem porta, latência regride silenciosamente (a lição da truncagem silenciosa, aplicada a tempo).

**Solução.**
1. `eval/latencia.py`: p50/p95 de `search` (com e sem rerank), `read_note`, `overview` sobre índice sintético inflado de 1M+ chunks (gerador em R4.1).
2. Portas iniciais, revistas com dados em 04/09/2026: `search` sem rerank p95 <4 s no cenário de referência (CPU de 4 núcleos, 8 GB, estresse de 1M chunks). Componentes não têm subportas; rerank e `overview` ganham orçamento quando houver caminho de produto medível.
3. Toda ablação futura reporta a coluna de latência (R6.2 inicia o padrão).

---

## 10. Higiene de engenharia (lote único, PR pequeno) — **P2** · Dono: qualquer

| # | Item | Ação |
|---|---|---|
| 1 | `.pytest_cache/` versionado | adicionar ao `.gitignore`, remover do índice git |
| 2 | CI só Windows | matriz 3×SO (junto com R8.1) |
| 3 | `dependencies = []` | resolvido por R8.1 |
| 4 | Encoding | garantir UTF-8 sem BOM nos `.md`; adicionar `.gitattributes` (`* text=auto eol=lf`) |
| 5 | Idioma misto | docstrings de API pública → EN gradualmente (quando o arquivo for tocado); docs internos PT ok |
| 6 | Segredos/caminhos | pre-commit hook simples: bloquear commit contendo caminhos absolutos `C:\` e nomes da lista VCE |
| 7 | Colaboração 2-devs | promover regras de `colaboracao.md` a ADRs curtos (`docs/adr/`) para suportar um 3º contribuidor |

---

## 11. O que **não** fazer (anti-recomendações registradas)

1. **Não** adicionar geração/sumarização no servidor — a arquitetura "só recupera" é a vantagem competitiva.
2. **Não** trocar SQLite/LanceDB por servidor externo (Qdrant/Elastic/Postgres) — mata o "instala e funciona" local. Revisitar apenas no caminho empresarial (ARCHITECTURE §6).
3. **Não** adotar GraphRAG/knowledge-graph pesado agora — o grafo leve por identificadores + `neighbors` já cobre o caso; custo de construção em 1 TB é proibitivo local.
4. **Não** calibrar fusão por score normalizado (min-max/z-score) em vez de RRF — scores não são estáveis entre corpora; a literatura e a própria varredura de vocês confirmam.
5. **Não** fazer OCR inline na onda principal — sempre onda separada de baixa prioridade.

---

## 12. Ordem de ataque sugerida (impacto ÷ esforço, respeitando dependências)

| Onda | Pacotes | Racional |
|---|---|---|
| 1 | **R1.3** (dedup/famílias) + **R8.1** (empacotamento) | destrava qualidade em base real e todo o caminho de produto; paralelizável entre notebook/desktop |
| 2 | **R3.2** (dois passes) + **R5.2** (orçamento) + **R1.4** (quarentena) | "útil no dia 1" numa máquina desconhecida sem fritar |
| 3 | **R3.1** (ablação modelo) + **R2.1** (contexto no chunk) | um único rebuild coordenado paga os dois |
| 4 | **R4.1** (ANN) + **R3.3** (quantização) + **R9.3** (porta de latência) | destrava a escala com número de guarda |
| 5 | **R1.1** (legado) + **R1.2** (OCR) | cobre as décadas de acervo; g015/g025/g048 entram no jogo |
| 6 | **R6.1** (autotune) + **R9.1** (multi-perfil) | mata o overfitting com a infraestrutura de eval já madura |
| 7 | **R6.2/R6.3** (rerank v2, tempo/pasta) + **R7.x** (tools MCP) | precisão e agência |
| 8 | **R8.2** (MCPB + wizard) + **R5.1** (USN watcher) | o produto, de fato |

---

## Fontes consolidadas

- Anthropic — Contextual Retrieval: https://www.anthropic.com/news/contextual-retrieval
- Anthropic — Desktop Extensions (MCPB/DXT): https://www.anthropic.com/engineering/desktop-extensions
- MCP Specification: https://modelcontextprotocol.io/specification · Registry: https://github.com/modelcontextprotocol/registry
- MTEB Leaderboard: https://huggingface.co/spaces/mteb/leaderboard
- BGE-M3: https://huggingface.co/BAAI/bge-m3 · bge-reranker-v2-m3: https://huggingface.co/BAAI/bge-reranker-v2-m3
- Snowflake arctic-embed-l-v2.0: https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0
- Docling: https://github.com/docling-project/docling (arXiv:2501.17887) · MarkItDown: https://github.com/microsoft/markitdown
- RapidOCR: https://github.com/RapidAI/RapidOCR
- LanceDB em escala: https://www.lancedb.com/blog/how-lancedb-accelerates-vector-search-at-10-billion-scale
- Qdrant — Binary Quantization: https://qdrant.tech/articles/binary-quantization-openai/
- Vespa — Matryoshka + BQ: https://blog.vespa.ai/combining-matryoshka-with-binary-quantization-using-embedder/
- Milvus — Matryoshka embeddings: https://milvus.io/blog/matryoshka-embeddings-detail-at-multiple-scales.md
- Cormack, Clarke, Buettcher — RRF (SIGIR'09): https://dl.acm.org/doi/10.1145/1571941.1572114
- Hybrid search trade-offs (2025): https://arxiv.org/html/2508.01405v2
- Late chunking: https://arxiv.org/abs/2409.04701
- Unstructured — enterprise RAG pipelines: https://unstructured.io/insights/rag-pipeline-best-practices-enterprise
- Microsoft — USN Change Journals: https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals
- datasketch (MinHash/LSH): https://ekzhu.com/datasketch/
- Speakeasy — distribuição MCP: https://www.speakeasy.com/mcp/distributing-mcp-servers/
- Comparativo embedded vector DBs: https://kanopylabs.com/blog/lancedb-vs-chroma-vs-sqlite-vec
- MIRACL (benchmark multilíngue): https://huggingface.co/datasets/miracl/miracl
