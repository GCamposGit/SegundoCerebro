# Update ao Dossiê de Melhorias — Segundo Cérebro (Pacotes C1–C7)
**Status:** FINAL — pronto para distribuição aos devs (notebook e desktop)
**Data:** 2026-08-24 · **Origem:** discussão de arquitetura pós-dossiê
**Relação:** complementa `dossie-melhorias.md` (2026-08-24). Não altera os pacotes R1–R10; adiciona os pacotes `C<n>` e registra onde eles **alteram ou subordinam** pacotes R (tabela ao final).

## Como usar (instrução para Claude Code / Grok Build)

- Mesmas regras do dossiê: **um pacote = uma branch = um PR**, número antes/depois quando tocar ranking, donos conforme `docs/colaboracao.md` §1; pacote que cruza a fronteira divide em dois PRs.
- Três pacotes C **modificam pacotes R**: leia a tabela "Interações com o dossiê" antes de pegar R1.3, R3.1, R6.2, R9.1 ou R9.2.
- Nenhum pacote C muda `model_id`, chunking padrão ou `[padrao]` sem acordo entre setups (invariante existente).

---

## C1 — Política de particionamento de bases — **P0** · Dono: acordo entre setups (toca ARCHITECTURE.md e wizard)

**Pergunta de produto.** Base única ou múltiplas bases por assunto ("Pessoal", "Empresa X", "Família")? Quem roteia a consulta?

**Decisão recomendada.**
> **Base separada = fronteira de privacidade, confiança ou ciclo de vida. Assunto = trabalho do retrieval, não do particionamento.**

**Justificativa (resumo da análise).**
1. Erro de roteamento entre bases é **binário e silencioso** (recall 0 sem ninguém saber que a resposta existia na base vizinha); erro de retrieval em base única é **suave** (cai do top-3 ao top-8). Nunca trocar degradação graciosa por modo de falha silencioso.
2. A vida real cruza assuntos; perguntas multi-hop (já o tipo mais fraco no dourado: recall@1 0.200) pioram com fragmentação.
3. Diagnóstico automático de assuntos em acervo desconhecido = classificador sem exemplos = overfitting institucionalizado.
4. O assunto já está no índice: a árvore de pastas é taxonomia curada pelo usuário por décadas — filtro de pasta (R6.3) + contexto de pasta no embedding (R2.1) entregam escopo temático dentro da base.
5. Trade-off quantitativo: com ANN (R4.1), 1M→10M vetores custa marginalmente em latência; roteamento errado custa tudo em recall. Fan-out em N bases = N processos × modelo carregado (RAM proibitiva em 8 GB) + fusão de rankings BM25 com IDFs incomparáveis entre bases.

**Quando separar fisicamente é correto (mantém o invariante atual de isolamento físico):**
- privacidade/confiança: pessoal vs corporativo; Empresa X vs Y; clientes MCP distintos veem bases distintas;
- ciclo de vida: HD externo às vezes desconectado;
- escala extrema: sub-acervo >~5–10M chunks ⇒ sharding interno (R4.3), mecânica invisível, nunca conceito de usuário.
- Alvo prático para o leigo: **1 a 3 bases**, mapeadas em raízes físicas que ele entende.

**Roteamento: 100% no LLM cliente. Nenhum roteador no servidor.**
1. Description de cada servidor MCP **gerada automaticamente do censo** ("Acervo corporativo: 240 mil docs de 2005–2026, contratos, atas, planilhas..."). É ela que faz o LLM rotear certo — reforça R7.2.
2. `overview()` (R7.1) como segunda linha: na dúvida, o agente pergunta às bases o que elas têm.
3. Pergunta que cruza bases: o loop de agente busca nas duas e funde — multi-hop nativo, argumento central do README.
4. **Anti-recomendação registrada:** roteador semântico dentro do servidor (classificar pergunta → escolher base). Redundante com o LLM, ponto de falha não-inspecionável, viola "o servidor só recupera".

**UX do leigo (integra com wizard R8.2).**
1. Pergunta única e física: "Quais pastas você quer que eu conheça?"
2. Heurística pós-censo: raízes distintas viram bases distintas **somente se** houver sinal de fronteira de contexto (OneDrive corporativo vs pasta pessoal). Confirmação binária em linguagem leiga: "Quer manter Trabalho e Pessoal separados, para conectar cada um a um assistente diferente?"
3. Divisão temática: **nunca oferecida**.

**Critérios de aceite.**
- `ARCHITECTURE.md` ganha seção "Política de particionamento" com a regra e as anti-recomendações;
- gerador de description-por-censo implementado e testado (sem vazar caminho absoluto/nome real);
- teste de agente: em setup com 2 bases (sintética corporativa + sintética pessoal), Claude Desktop roteia ≥90% de 20 perguntas rotuladas para a base certa **só pelas descriptions**;
- wizard nunca apresenta a palavra "base" nem oferece divisão por assunto.

**Fontes.** Cormack et al., RRF (SIGIR'09): https://dl.acm.org/doi/10.1145/1571941.1572114 (fusão por posição, não por score — e por que IDFs entre corpora não se misturam); MCP spec — múltiplos servidores por cliente: https://modelcontextprotocol.io/specification; experiência de mercado em roteamento por description de tool (R7.2 do dossiê).

---

## C2 — Glossário de siglas automático, construído do corpus — **P1** · Dono: desktop (extração na indexação) + notebook (uso no ranking, ablação)

**Pergunta de produto.** Dicionário de siglas ainda é state of the art? Como construir sem input manual do usuário?

**Veredito.** Sim — com duas atualizações de framing:
1. A ablação F2 do próprio projeto já provou o consenso da área: glossário **específico do corpus** ajuda; genérico atrapalha. Siglas organizacionais são vocabulário fora de distribuição para qualquer embedding — nenhum modelo sabe o que "TAM" significa *neste* acervo.
2. Na arquitetura MCP, o glossário é também **recurso para o LLM cliente** (tool `define`), não só expansor interno. O agente faz query rewriting melhor que qualquer expansor server-side — desde que tenha acesso ao vocabulário do corpus.
3. Alternativa "moderna" (learned sparse / SPLADE) faz expansão dentro do modelo, mas é cara local e não-interpretável — **anti-recomendação por ora**; se R3.1 adotar BGE-M3, o sinal esparso dele cobre parte do problema, com o glossário como camada explícita por cima.

**Pipeline automático (roda na indexação, custo marginal ~zero).**
1. **Extração por documento** — passo barato no fluxo de parse: algoritmo **Schwartz-Hearst** (padrões "Forma Longa (SIGLA)" e "SIGLA (Forma Longa)" com alinhamento de caracteres — canônico desde 2003, precisão altíssima, O(n), sem ML) + heurística de candidatos: tokens MAIÚSCULOS 2–6 chars frequentes sem definição encontrada (ficam pendentes). Persistir em `siglas(sigla, expansao, doc_id, contexto, metodo)`.
2. **Agregação com confiança** — entra no glossário ativo apenas: definição igual (normalizada) em ≥2 docs distintos, OU 1 doc + alta frequência de uso da sigla no acervo. Regra de design herdada da ablação F2: **precisão alta, recall baixo** — expansão errada custa mais que expansão ausente.
3. **Ambiguidade** — mesma sigla, expansões diferentes: manter todas com escopo de pasta (sinergia com R2.1); na consulta, expandir só se o contexto/filtro de pasta desambiguar; senão, a tool `define` devolve as opções ao LLM decidir.
4. **Uso na consulta** — expansão **somente no ranking lexical** (FTS5: `TAM OR "termo aditivo modificativo"`, já com a sanitização de MATCH existente). O denso não recebe expansão (suja o vetor da query). Zero mudança nos vetores ⇒ zero rebuild.
5. **Tool MCP `define(termo)`** — devolve expansões conhecidas, nº de docs-fonte e um doc-exemplo. Barata (SQL puro), entra no pacote de tools R7.1.
6. **Incremental e derivado** — docs novos alimentam a extração na mesma onda; o glossário é 100% reconstruível do índice: nunca vira estado que o usuário mantém.
7. **Curadoria opcional, nunca obrigatória** — painel de dev lista/veta entradas; `glossario.toml` manual vira *override* sobre o automático; o leigo nunca vê nada disso.

**Sinergia com o existente.** `identificadores.py` já extrai padrões `PO-CORP-007`; siglas são a generalização natural. A tabela `mencoes` é o lar estrutural. O mecanismo de expansão de consulta do `glossario.py` atual é reutilizado — muda a **origem** (automática) e a **política** (confiança), não o encaixe.

**Critérios de aceite.**
- No corpus sintético com siglas plantadas (definidas 1×, 2×, ambíguas, nunca definidas): precisão do glossário ativo ≥95%, sem falsos positivos de sigla ambígua expandida sem desambiguação;
- no dourado real: MRR/recall com glossário automático ≥ glossário manual atual (a régua já existe: `metricas-f2-glossario-especifico.md`);
- tempo de indexação cresce <2% com a extração ligada;
- `define("TAM")` responde <50 ms;
- ablação registrada em `docs/ablacao-glossario-automatico.md`.

**Fontes.** Schwartz & Hearst — "A Simple Algorithm for Identifying Abbreviation Definitions in Biomedical Text" (PSB 2003): https://psb.stanford.edu/psb-online/proceedings/psb03/schwartz.pdf; implementação de referência: https://github.com/philgooch/abbreviation-extraction; SPLADE (contexto da alternativa não adotada): https://arxiv.org/abs/2107.05720; ablação interna F2 (glossário específico vs genérico): `docs/ablacao-glossario.md`.

---

## C3 — Afinação da busca lexical (FTS5): pesos de coluna, morfologia PT, frases — **P1** · Dono: notebook (ranking; toca `store.py::consulta_fts`/`buscar_lexical` — store é compartilhado, combinar antes)

**Pergunta de produto.** A busca por palavras-chave (FTS5+bm25) segue as melhores práticas? Precisa de algo diferente?

**Veredito.** O motor está certo e fica: FTS5 external-content com triggers (sincronia automática com `chunks`), tokenizer `unicode61 remove_diacritics 2`, quoting de todo termo (a armadilha `PO-ACME-007` → `PO NOT ACME NOT 007` já está resolvida em `consulta_fts`), `bm25()` nativo, fusão RRF por posição. Nenhuma troca de motor (Tantivy/SPLADE permanecem anti-recomendados — dossiê R4.2 e C2). As lacunas são de **camada de query e calibração**:

**C3.a — Pesos de coluna do bm25 + dupla contagem do nome (prioridade do pacote).**
- Hoje `bm25(chunks_fts)` roda com pesos default (1/1/1 para `texto`/`trilha`/`caminho`). A coluna `caminho` faz o nome do arquivo pontuar dentro do lexical **e** existe o `RanqueadorDeNome` separado na fusão — o mesmo sinal vota duas vezes. Neste acervo (nome informativo) isso passa; em acervo genérico (`IMG_2034.pdf`) é ruído dobrado.
- Ação: varrer pesos de coluna `bm25(chunks_fts, w_texto, w_trilha, w_caminho)` em grade pequena (caminho ∈ {0, 0.3, 1.0} × trilha ∈ {0.5, 1.0}) no dourado real, medindo a interação com `PESO_NOME` da fusão. Hipótese: `caminho` baixo/zero no FTS + nome só no ranqueador dedicado. Esses pesos entram na grade do autotune R6.1.

**C3.b — Expansão morfológica PT na query (nunca no índice).**
- `unicode61` não faz stemming; `porter` é inglês-only; tokenizer custom quebra portabilidade do arquivo de índice. Prática correta local: gerar variantes por termo na construção da MATCH — plural/singular e flexões via regras PT leves ou Snowball-PT usado só como **gerador de variantes** (`contratação OR contratações`). Zero reindex; identificadores aspeados intocados; teto de variantes por termo (ex.: 3).
- Sinergia: mesmo ponto de código da expansão do glossário (C2) — uma única camada de "reescrita lexical da query".

**C3.c — Preservação de frases e bigramas.**
- O quoting individual desmonta "termo aditivo modificativo" em 3 termos OR — perde proximidade. FTS5 tem frase e `NEAR()` nativos.
- Ação: (1) aspas vindas do usuário/LLM viram frase FTS real; (2) bigramas da query entram como termos-frase adicionais ao OR atual (aditivo puro: frase acerta → documento sobe; não acerta → nada muda); (3) expansões multi-palavra do glossário C2 entram como frase, não como termos soltos.

**C3.d — Stoplist PT mínima na query (medir antes de adotar).**
- Perguntas inteiras de LLM viram OR de todas as palavras e enchem o poço de 200 candidatos com matches de palavras funcionais. O IDF do bm25 já mitiga — pode ser não-problema. Stoplist de ~50 palavras aplicada só em `consulta_fts` (índice intocado), atrás de flag, com ablação. Se não mover número: descartar e registrar a decisão.

**Critérios de aceite.**
- Ablação única `docs/ablacao-lexical.md` cobrindo a–d, com MRR/recall no dourado real e no sintético (o perfil de nomes ruins de R9.1 é o teste da dupla contagem);
- casos-armadilha (hoje 5/6) não regridem em nenhuma variante adotada;
- `consulta_fts` mantém a garantia de sanitização — property test: nenhuma entrada gera erro de sintaxe MATCH (fuzz com hífens, aspas, operadores, unicode);
- latência lexical p95 não cresce >20% com morfologia + bigramas ligados.

**Fontes.** SQLite FTS5 — pesos de coluna no bm25, frases, NEAR, tokenizers: https://sqlite.org/fts5.html; Snowball Portuguese stemmer: https://snowballstem.org/algorithms/portuguese/stemmer.html; Cormack et al., RRF (SIGIR'09) — calibração vive nos pesos, não em normalização de score: https://dl.acm.org/doi/10.1145/1571941.1572114; anti-recomendação SPLADE registrada em C2 (arXiv:2107.05720).

---

## C4 — Corpus bilíngue PT+EN: requisitos transversais — **P1** · Dono: transversal (cada cláusula segue o dono do pacote que ela altera)

**Pergunta de produto.** Como o sistema se comporta com acervos com conteúdo relevante em português E inglês (caso das bases de teste e de muitos usuários)? Muda algo na proposta?

**Diagnóstico por camada (estado atual).**
- **Denso — já resolve cross-lingual:** `multilingual-e5-large` é alinhado entre idiomas; pergunta PT encontra doc EN e vice-versa. É a camada certa para a ponte semântica. Os candidatos de R3.1 (BGE-M3, arctic-l-v2.0) também são multilíngues.
- **Lexical — cego a idioma, preso ao termo, e correto assim:** FTS5 não casa "contrato" com "agreement"; não precisa — o denso faz a ponte, e o lexical segue dono do que não se traduz: siglas e identificadores (`SLA`, `PO-CORP-007`), iguais nos dois idiomas.
- **Reranker — elo fraco:** `bge-reranker-base` (único MIT no fastembed, decisão registrada em `rerank.py`) é treinado primariamente em CN+EN; pares PT-query/EN-doc são seu pior caso. A "rota de volta" já documentada (`bge-reranker-v2-m3`) vira necessidade.
- **Eval — lacuna:** não há fatia cross-lingual deliberada no dourado nem no sintético; regressão bilíngue hoje passaria invisível.

**Cláusulas (cada uma altera um pacote existente).**
1. **[altera R3.1]** Requisito duro do catálogo `MODELOS`: modelo denso padrão DEVE ser multilíngue com alinhamento cross-lingual comprovado (MTEB multilingual). Registrar como invariante em `ARCHITECTURE.md`. A ablação R3.1 ganha fatia cross-lingual obrigatória (pergunta PT → doc EN e o inverso), medida separadamente do agregado.
2. **[altera R6.2]** Prioridade do `bge-reranker-v2-m3` sobe por causa do bilíngue: incluir na varredura a fatia cross-lingual — é onde o `-base` atual deve perder por mais. Se v2-m3 não entrar via fastembed (limitação já registrada em `rerank.py`), rota ONNX direta via onnxruntime já presente. Guarda: em nenhuma hipótese reranker inglês-only ou não-comercial (tabela de licenças de `rerank.py` continua valendo).
3. **[altera C3.b/C3.d]** Expansão morfológica e stoplist tornam-se bilíngues: detectar idioma provável do termo (heurística barata: stopwords/dígrafos) ou, mais simples e robusto, gerar variantes PT **e** EN dentro do mesmo teto (Snowball tem os dois stemmers); stoplist = união PT+EN (~90 palavras). Identificadores/siglas seguem intocados.
4. **[altera C2]** Schwartz-Hearst é essencialmente agnóstico a idioma (padrão parentético é igual em PT e EN) — sem mudança de algoritmo. Bônus registrado: a sigla é o **elo lexical entre idiomas** ("SLA" aparece no doc PT e no EN); a expansão via glossário dá ao FTS5 um alcance cross-lingual que BM25 puro não tem. Guardar expansões nos dois idiomas quando ambas forem encontradas.
5. **[altera R9.1 e dourado]** Fatia de avaliação cross-lingual: perfil sintético bilíngue (docs EN misturados, perguntas PT apontando para eles e vice-versa) + ≥5 perguntas cross-lingual no dourado real. Harness reporta recorte `mesma-língua` vs `cross-lingual` em toda ablação de modelo/reranker. Benchmark externo (MIRACL-PT): condicionado à porta de custo de C5.a — sanity check, não critério de decisão.
6. **[altera R7.2]** Descriptions das tools ensinam o fallback agêntico: "o índice é bilíngue PT/EN; se a busca em um idioma render pouco, refaça a consulta traduzida". É a vantagem exclusiva da arquitetura MCP: o LLM cliente traduz a query de graça — nenhum tradutor server-side (anti-recomendação: não construir query translation no servidor).
7. **[metadado barato, dono: desktop]** Idioma provável por documento no censo/parse (heurística de stopwords, sem dependência nova), coluna `idioma` em `documentos`: alimenta o recorte do harness, o `overview()` ("62% PT, 35% EN") e futuro filtro opcional em `search`.

**O que NÃO muda.** Chunking (tokenizer do e5 é multilíngue — orçamento já correto nos dois idiomas); `unicode61 remove_diacritics 2` (inócuo para EN); RRF e pesos (a divisão denso-ponte/lexical-exato já é a arquitetura certa para bilíngue); C1 (idioma **não** é critério de particionamento de base — mesma lógica de assunto: o denso cruza idiomas dentro da base).

**Critérios de aceite.**
- Invariante multilíngue registrado em `ARCHITECTURE.md` e no docstring do catálogo `MODELOS`;
- fatia cross-lingual existe no harness e aparece em toda ablação de denso/reranker a partir de agora;
- no perfil sintético bilíngue: recall@5 cross-lingual ≥ 80% do recall@5 mesma-língua com o denso vencedor de R3.1 + reranker vencedor de R6.2;
- expansão morfológica bilíngue não regride latência além do teto de C3 (+20% p95);
- `overview()` reporta distribuição de idiomas sem custo de consulta perceptível.

**Fontes.** multilingual-e5 (alinhamento cross-lingual; arXiv:2402.05672): https://arxiv.org/abs/2402.05672; BGE-M3 multilíngue: https://huggingface.co/BAAI/bge-m3; bge-reranker-v2-m3: https://huggingface.co/BAAI/bge-reranker-v2-m3; MTEB multilingual (fatias cross-lingual): https://huggingface.co/spaces/mteb/leaderboard; Snowball stemmers PT/EN: https://snowballstem.org/; MIRACL (benchmark multilíngue já citado em R9.2 — cobre PT e EN): https://huggingface.co/datasets/miracl/miracl.

---

## C5 — Infra de avaliação: MIRACL com porta de custo; sintético versiona gerador, não corpus — **P1** · Dono: desktop (custo/geração) + notebook (critério de decisão)

**Origem.** Duas objeções de revisão ao uso de benchmark externo (C4/R9.2) e ao empacotamento dos perfis sintéticos (R9.1).

**C5.a — MIRACL-PT só entra amostrado, medido e fora do caminho crítico.**
- Conta com os números do repo: MIRACL-PT ≈ 1M passagens ≈ 90× o corpus dev. No notebook (0,63 chunks/s do `ModelSpec` e5-large): ~19 dias — proibitivo. No desktop, custo real depende do throughput do pool nas 980 Ti, **não medido para este caso** — e multiplica pelos 3 candidatos de R3.1.
- Domínio errado (Wikipedia ≠ acervo corporativo): responde "o modelo é bom em PT em geral", não "bom neste acervo". **Rebaixado de critério de decisão para sanity check.** O critério vinculante das ablações são as fatias bilíngues internas (C4.5: sintético bilíngue + perguntas cross-lingual do dourado).
- Se usado: (1) fatia amostrada — todas as queries dev + positivos dos qrels + ~100k distratoras com seed fixa (custo ~10× menor; métricas valem **apenas comparativamente** entre modelos — corpus amostrado infla recall, nunca citar como número absoluto); (2) desktop-only, nunca na onda 1, nunca no CI, nunca competindo com indexação do acervo real em curso; (3) índice próprio em diretório descartável (invariante de isolamento respeitado; artefato deletável, nunca `[[base]]`); (4) **porta de custo**: rodar smoke de throughput antes — custo por modelo > ~12h (uma noite) ⇒ MIRACL cai da ablação, registrando a decisão.

**C5.b — Perfis sintéticos de R9.1: versionar gerador + seed + manifesto; corpus nunca commitado.**
- Segue o contrato já estabelecido por `eval/sintetico/` (gerador versionado). Quatro perfis × ~80 docs commitados = peso morto que envelhece.
- Commitados: código do gerador, seed fixa por perfil, **manifesto** por perfil (contagem de arquivos + hash do **texto extraído** de cada um). Manifesto é o que permite aos dois setups verificar regeneração idêntica. Corpora gerados: gitignore.
- Hash em nível de conteúdo (texto extraído), não de byte: os perfis com legado binário (`.ppt/.doc/.xls` via LibreOffice, R1.1) não reproduzem byte a byte entre versões do LibreOffice. Binários: gerados sob demanda, cacheados localmente, validados pelo manifesto de conteúdo.
- CI regenera e valida apenas perfis de texto (rápido, sem LibreOffice — coerente com "CI é Windows+CPU"); perfis binários rodam localmente.
- Determinismo obrigatório no gerador: seed única, iteração ordenada, sem dependência de locale/ordem de dict.

**Critérios de aceite.**
- R9.1 e C4.5 passam a referenciar C5.b (nenhum corpus gerado entra no repo);
- `git ls-files` não contém nenhum arquivo de corpus de perfil; manifestos presentes e validados em teste;
- smoke de throughput publicado (`docs/custo-miracl.md`) antes de qualquer download do MIRACL; decisão adotar/descartar registrada com número;
- regeneração nos dois setups produz manifestos idênticos para os perfis de texto.

**Fontes.** MIRACL (corpus/qrels por língua): https://huggingface.co/datasets/miracl/miracl; prática de avaliação IR com pool amostrado — métricas comparativas, não absolutas (Craswell et al., TREC Deep Learning: https://arxiv.org/abs/2003.07820); contrato existente `eval/sintetico/README.md` (gerador versionado, corpus reproduzível).

---

## C6 — Versões e duplicatas: dois conceitos (família de versões ≠ grupo de formatos) e o fluxo de comparação — **P0** · Dono: notebook (ranking/famílias) + desktop (hash/MinHash no censo); reconcilia R1.3 com `retrieve/familias.py`

**Pergunta de produto.** Solução final para duplicados/versionados: (a) "só a última importa" vs (b) "3 orçamentos — em qual houve aumento de verba?"; e como tratar `.ppt/.doc/.txt` exportados como PDF com conteúdo idêntico?

**O que já está certo e medido (não mexer sem número).** `familias.py`: colapso na consulta (nada é apagado do índice); chave = pasta+extensão+nome sem marcadores (removidos em loop — empilham); representante = mais recente por mtime **entre os recuperados** (caso `g010`: número de versão no nome mente); `anteriores` preservadas como procedência; família não atravessa pasta (modelo vs preenchido). Ablação: recall@1 0.600→0.644, armadilhas 4→5/6, zero regressões. Caso (a) resolvido por construção.

**C6.a — Caso (b): comparação de versões é fluxo do agente, não do servidor.**
- A resposta certa a "em qual versão houve aumento de verba?" é o LLM ler as versões e comparar — nunca um "diff" server-side.
- Fio a completar: (1) o retorno MCP de `search` expõe por resultado `versoes: n` + lista `anteriores` com **id + data + caminho** utilizáveis por `read_note`/`neighbors`; (2) a description da tool ensina o fluxo (reforça R7.2): "resultados colapsam versões do mesmo documento; para comparar versões, leia os ids listados em `anteriores`"; (3) filtro de data (R6.3) cobre "qual era a versão de 2019?".
- Anti-recomendação: diff/comparação computada no servidor — viola "o servidor só recupera".

**C6.b — Colisão detectada entre R1.3 e `familias.py` (resolver antes de implementar R1.3).**
- `chave_de_familia` inclui a **extensão** por decisão medida (g045: PPTX e PDF do mesmo deck fundidos ⇒ desempate por data escolhe formato ao acaso ⇒ g045 sai do ranking; "quem pede o deck quer o deck").
- R1.3 como escrito colide duas vezes: hash exato não pega exportações (bytes diferem); MinHash 0.85 fundiria o que familias.py separou de propósito — reintroduziria o bug g045 por outra porta. R1.3 fica **subordinado a este pacote**.

**C6.c — Solução: dois conceitos com políticas distintas.**
1. **Família de versões** (conteúdo evolui; `_v6` → `_v8`): mecanismo atual mantido; MinHash (~0.85, mesma pasta) entra como **detector adicional** de membros que o nome não denuncia (`Orçamento_novo.xlsx`, cópia renomeada). Representante por mtime; anteriores expostas (C6.a).
2. **Grupo de formatos** (conteúdo idêntico; container diferente: PPTX+PDF, DOC+PDF, TXT+PDF): detecção = near-dup com limiar alto (~0.95 no texto extraído) + mesmo tronco de nome + mesma pasta. Política: **um slot no top-k**, representante = **o mais bem ranqueado** (não o mais recente — data de exportação é arbitrária), anotação `formatos: [pptx, pdf]` com ids; o LLM escolhe o container (quem pede o deck abre o pptx). g045 vira caso-guarda da ablação: regrediu ⇒ política volta.
3. Dedup exato por hash (R1.3.1) segue valendo para cópias byte-idênticas (backup, pastas espelhadas) — camada mais barata, roda no censo.
4. MinHash **só cruza pasta com ≥0.95** (proteção modelo-vs-preenchido); penalidade multiplicativa 0.3 do R1.3 descartada — redundante com o colapso já medido, que tem número.

**Critérios de aceite.**
- g010 e g045 permanecem verdes (casos-guarda nomeados da ablação);
- corpus sintético ganha grupos plantados: versões (5/15/40% de edição), exportações PPTX→PDF/DOC→PDF idênticas, cópia renomeada, modelo-vs-preenchido em pastas distintas (não pode fundir);
- métrica "duplicatas no top-10" (R1.3) medida antes/depois: grupo de formatos conta 1×;
- fluxo do caso (b) validado ponta a ponta: agente (Claude Desktop) responde "em qual versão o valor mudou?" usando só `search`+`anteriores`+`read_note`, sem tool nova de diff;
- ablação em `docs/ablacao-familias-formatos.md`.

**Fontes.** Broder — near-duplicate detection via MinHash/shingling: https://ekzhu.com/datasketch/; decisões medidas internas: docstrings de `retrieve/familias.py` (g010, g045), `docs/ablacao-familias.md`, `docs/portas-f1-condicao-c.md`; Contextual/agentic retrieval — comparação no cliente, recuperação no servidor (README do projeto; MCP spec: https://modelcontextprotocol.io/specification).

---

## C7 — Planilhas: despejo de dados vs modelo de análise; valores calculados; rota do CSV — **P0** · Dono: desktop (sheets.py é dele) + notebook (medição no dourado)

**Pergunta de produto.** Excel cai em dois tipos: (1) bases de dados enormes onde o sinal é cabeçalho de colunas/linhas e algumas colunas identificadoras — os dados brutos quase não importam; (2) modelos e análises menores onde números-resultado (valuation, premissas) vivem em células esparsas. Como o pipeline trata cada um? Como não indexar gigas de dados inúteis sem perder "qual o valor de avaliação da empresa X?"? E CSV?

**Diagnóstico — caso 1 já está resolvido acima do estado da prática (não mexer sem número).** `sheets.py` implementa exatamente a melhor prática, com limiares medidos no acervo:
- janela adaptativa: 30 linhas/bloco (aba normal), 200 (aba grande >200 linhas), cabeçalho repetido em toda janela (bloco autossuficiente);
- aba enorme (>5.000 linhas OU >20.000 células — o segundo limiar nasceu de uma aba 4.279×22 que gerou 3.277 chunks quase idênticos, 1,5h de e5-large): vira **digesto** — cartão da aba (nº linhas, colunas, cabeçalhos) + valores distintos das ≤4 primeiras colunas identificadoras, cobrindo a aba até o fim (o corte anterior descartava 3,1 milhões de linhas em silêncio);
- coluna de medida (decimal: dinheiro, %, índice) excluída do digesto — "ninguém busca 9000,0";
- cobertura parcial declarada em metadado, nunca silenciosa; célula exata sai via `read_note` na faixa — recuperação dá procedência, o cliente aprofunda.
É a resposta canônica a "não indexar gigas inúteis": indexar o **esquema + identificadores**, não os fatos; R2.2 (chunk de rota) complementa.

**Diagnóstico — caso 2 tem três lacunas, uma grave.**

**C7.a — GRAVE: o valor do valuation pode nem existir no texto extraído.** `data_only=True` lê o valor **cacheado** da última gravação pelo Excel. Arquivo gerado por ferramenta e nunca aberto/salvo no Excel ⇒ células de fórmula vêm **vazias** — hoje registrado em metadado, mas o número do Equity Value simplesmente não entra no índice. Em acervo de M&A/PE isso é o pior modo de falha possível.
- Solução: fallback de **recálculo via LibreOffice headless** (sinergia direta com R1.1 — mesmo binário): planilha detectada sem cache (`sem_valor_em_cache` já existe) entra na rota `soffice --convert-to xlsx` com recálculo na carga; re-parse do resultado. Onda de baixa prioridade, mesma filosofia do OCR (R1.2). Se LibreOffice ausente: metadado vira aviso no painel/censo ("N planilhas com fórmulas não calculadas").

**C7.b — Modelo esparso: rótulo e número se perdem na grade.** Um valuation tem "Equity Value" numa célula e "10.2" três colunas à direita, sem linha de cabeçalho real; a detecção atual (primeira linha com ≥2 células = cabeçalho) produz janelas onde rótulo e valor podem cair desalinhados ou o "cabeçalho" repetido é lixo.
- Solução: **cartão de modelo** para aba pequena que não parece tabela (heurística barata: <200 linhas, densidade <40%, sem cabeçalho consistente — invertendo `_e_despejo_de_dados` que já existe): emitir pares **rótulo→valores adjacentes** (célula de texto seguida de células numéricas à direita/abaixo, padrão dominante em modelos financeiros) como blocos `natureza="modelo"`: `"WACC: 12,3% · Equity Value: R$ 10,2 bi · TIR: 18,4%"`. É o que faz "qual o valor de avaliação da empresa X?" casar no denso (rótulo semântico junto do número) e no lexical (nome da empresa no path/aba).
- **Nomes definidos** (named ranges) do workbook: `openpyxl` expõe `defined_names` de graça; um modelo com célula nomeada `EquityValue` é sinal altíssimo — emitir `nome_definido: valor` no cartão.

**C7.c — Números importam no modelo (inversão da regra do digesto).** A exclusão de colunas de medida é correta para despejo e **errada** para modelo: no modelo, o número é o payload. A regra vira condicional por tipo de aba (despejo: excluir medidas; modelo: manter no cartão). Tipo já é detectável com o que existe.

**C7.d — CSV está na rota errada.** Hoje `.csv` registra no parser de **texto puro** (`text.py`), com teto de 2 MB: (1) cabeçalho aparece só no 1º chunk — janelas seguintes são linhas órfãs sem esquema; (2) acima do teto o arquivo é adiado inteiro — e o censo real tem 85 CSVs somando 492 MB (maior: 104 MB), invisíveis hoje.
- Solução: rota própria `.csv`/`.tsv` no pipeline de planilha (sniff de delimitador via `csv.Sniffer` + fallback), reutilizando a mesma máquina: janela com cabeçalho repetido para arquivo pequeno, **digesto de valores distintos para arquivo grande** — que dispensa o teto de bytes: 104 MB de dump viram um cartão + digestos, streaming linha a linha sem materializar (o gerador de `_blocos_de_digesto` já aceita isso por design). Teto de 2 MB deixa de significar "invisível" e passa a significar "vai para digesto". Guarda existente mantida: CSV que parece MIME continua CSV (teste de `natureza.py` já cobre).

**Critérios de aceite.**
- Sintético ganha os dois tipos plantados: dump 100k+ linhas (com e sem coluna categórica) e modelo de valuation (rótulos esparsos, fórmulas sem cache, named ranges) + CSVs equivalentes;
- pergunta-guarda "qual o valor de avaliação da empresa X?" (sintético) acerta no top-5 com o número presente no trecho devolvido;
- planilha sem cache recalculada via LibreOffice indexa o valor; sem LibreOffice, aviso visível no relatório do censo;
- CSV de 100 MB indexa como digesto em tempo linear e nunca como 800 chunks de texto órfão; nenhum CSV "adiado" silenciosamente;
- nº total de chunks do acervo cresce <3% com cartões de modelo ligados;
- ablação `docs/ablacao-planilhas-modelo.md` com antes/depois no dourado real (g-perguntas de planilha) e sintético.

**Fontes.** openpyxl `data_only` e `defined_names`: https://openpyxl.readthedocs.io/; LibreOffice recálculo na carga (`--convert-to`, opção de recálculo): https://help.libreoffice.org/; prática de table cards/schema-first para tabelas em RAG (Unstructured, link em R1.1); decisões medidas internas: docstrings de `sheets.py` (limiar 20k células, digesto, 3,1M linhas descartadas), `docs/indexacao-cortes.md`, `docs/prioridade-de-indexacao.md`.

---

## Síntese e interações com o dossiê

| Pacote | Tema | Prioridade | Interação com pacotes R |
|---|---|---|---|
| C1 | Particionamento de bases e roteamento | **P0** | reforça R7.1/R7.2; insumo do wizard R8.2 |
| C2 | Glossário de siglas automático do corpus | P1 | entra nas tools R7.1; expansão no mesmo ponto de C3 |
| C3 | Afinação lexical FTS5 (pesos de coluna, morfologia, frases) | P1 | pesos entram na grade do autotune R6.1 |
| C4 | Bilíngue PT+EN (transversal) | P1 | **altera R3.1, R6.2, R9.1**; cláusulas em C2/C3 |
| C5 | Eval: MIRACL com porta de custo; sintético versiona gerador | P1 | **condiciona R9.2; muda o empacotamento de R9.1** |
| C6 | Versões e duplicatas: família de versões ≠ grupo de formatos | **P0** | **subordina R1.3** (não implementar R1.3 sem C6) |
| C7 | Planilhas: despejo vs modelo; recálculo de fórmulas; rota CSV | **P0** | sinergia com R1.1 (LibreOffice) e R2.2 |

## Ordem de ataque sugerida

1. **C6 antes de R1.3** — a colisão com `familias.py` (casos-guarda g010/g045) precisa estar resolvida antes de qualquer dedup novo.
2. **C7.a e C7.d cedo** (fórmulas sem cache; CSV na rota de planilha) — são perda silenciosa de conteúdo hoje; C7.b/C7.c (cartão de modelo) na sequência, com ablação.
3. **C1** é decisão de política + gerador de description: barato, destrava wizard (R8.2) e docs (`ARCHITECTURE.md`).
4. **C5 antes de qualquer ablação de modelo** — a porta de custo do MIRACL e o manifesto do sintético definem a infra em que R3.1/R6.2 serão medidos.
5. **C4 junto com R3.1/R6.2** — as fatias cross-lingual têm que existir no harness antes de congelar modelo e reranker.
6. **C2 e C3 juntos** — compartilham o mesmo ponto de código (reescrita lexical da query); ablações em `docs/ablacao-lexical.md` + `docs/ablacao-glossario-automatico.md`.

## Anti-recomendações consolidadas (registrar em `ARCHITECTURE.md`)

- Roteador semântico de bases dentro do servidor (C1) — o LLM cliente roteia por description.
- Divisão de bases por assunto ou por idioma (C1, C4) — fronteira é privacidade/confiança/ciclo de vida.
- SPLADE/learned sparse como expansor local (C2) — caro e não-interpretável; sinal esparso do BGE-M3 fica como experimento futuro.
- Tradutor de queries server-side (C4) — o agente traduz.
- Diff/comparação de versões no servidor (C6) — o agente compara via `anteriores` + `read_note`.
- Penalidade multiplicativa 0.3 do R1.3 (C6) — redundante com o colapso de famílias já medido.
- MIRACL completo ou como critério de decisão (C5) — só amostrado, só sanity check, só atrás da porta de custo.
