# Relatório — Arquitetura de Avaliação Resiliente (Pacotes E1–E6)
**Status:** FINAL — para distribuição aos devs (notebook e desktop)
**Data:** 2026-08-24 · **Origem:** análise completa dos conjuntos de teste + pesquisa de melhores práticas (RAGAS, BEIR/MIRACL, DynaBench, literatura de test collections de IR)
**Relação:** substitui e expande **R9.1/R9.2** do dossiê e **C5** do update — onde houver conflito, este documento vence. Mesmo contrato: um pacote = uma branch = um PR.

---

## 0. Diagnóstico — o problema é real e tem nome

A preocupação levantada tem dois nomes na literatura de IR:

1. **Viés de pooling/coleção** (Voorhees, TREC): um conjunto de teste construído sobre *um* acervo mede aquele acervo, não a tarefa. O dourado atual (51 perguntas, 6 fora de escopo, escritas majoritariamente "a partir dos nomes de arquivo" — o próprio relatório de ablação declara o viés) foi construído quando o produto era "buscar no acervo corporativo desta consultoria". O produto agora é "buscar em qualquer acervo de 1 TB". **As decisões de arquitetura estão sendo otimizadas para um ponto no espaço de acervos.**
2. **Lei de Goodhart / overfitting de avaliação** (DynaBench, Kiela et al. 2021): métrica estática que vira alvo deixa de medir. 45 perguntas no escopo → uma mudança que move 2 perguntas move recall@1 em 4,4 p.p. — o ruído estatístico é maior que muitos "ganhos" já celebrados em ablações.

Evidências concretas do risco no repo:
- pesos da fusão (denso 1.0 / lexical 0.25 / **nome 0.5**) varridos num acervo onde nome de arquivo é sinal excepcional — a dupla contagem do nome (C3.a) passou despercebida exatamente por isso;
- multi-hop: n=5 perguntas → recall@1 de 0.200 significa **1 acerto**; nenhuma decisão é defensável com n=5;
- zero perguntas cross-lingual, zero sobre planilhas-modelo, zero sobre versões conflitantes — as três classes de bug que os dossiês R/C atacam **não têm como ser medidas hoje**.

**Porém: o dourado atual não é descartável — é um ativo raro** (perguntas reais, de usuário real, com armadilhas reais). O erro seria substituí-lo; o acerto é rebaixá-lo de "juiz único" para "uma fatia de um sistema de três camadas".

---

## 1. Arquitetura recomendada: três camadas + um loop

```
Camada 1 — DOURADO REAL (o que existe)          → regressão; nunca decide arquitetura sozinho
Camada 2 — SINTÉTICO PARRUDO GERADO POR CÓDIGO  → decide arquitetura; cobre a matriz de armadilhas
Camada 3 — BENCHMARK EXTERNO AMOSTRADO          → sanity check anti-endogamia (C5 já define: MIRACL-PT, porta de custo)
Loop     — RED-TEAM POR FASE                    → cada fase adiciona casos derivados de falhas reais; sets versionados e congelados
```

Princípio de decisão (registrar em `ARCHITECTURE.md`): **feature entra se ganha na Camada 2 na fatia que ela mira, sem regredir nenhuma outra fatia além do ruído, e sem regredir a Camada 1.** A Camada 3 nunca decide — só alarma.

---

## E1 — Gerador de corpus sintético como código versionado — **P0** · Dono: desktop (geração) + notebook (perguntas/gabarito)

**O insight central: ground truth por construção.** A melhor prática de 2025-26 (RAGAS testset generation e sucessores multi-agente) usa LLM para gerar perguntas de docs existentes — bom para conteúdo, mas o gabarito herda a incerteza do LLM. Para um sistema de *retrieval* (não de geração), existe opção melhor: **gerar o documento e a pergunta juntos, por código**. Se o gerador planta o fato "o valor do contrato NN-X-450 é R$ 2,3 mi" no doc 47 e em nenhum outro, o gabarito é perfeito por construção — sem juiz LLM, sem anotação manual, sem contaminação.

**Desenho.**
1. `eval/gerador/` — pacote Python **determinístico com seed**: mesma seed ⇒ mesmo corpus byte a byte. O corpus **não é versionado no Git; o gerador é** (C5 já exige manifesto+seed — este pacote é a implementação).
2. Vocabulário 100% VCE (empresas fictícias) — zero risco de vazamento; LLM (Claude Code, offline, nunca no caminho de consulta) pode ser usado para redigir *templates* de texto realista, mas fatos, entidades e respostas são injetados por código.
3. Escala-alvo: **≥2.000 docs, ≥500 perguntas** (vs 434/51 atuais) — n por fatia ≥30 para significância (E5).
4. Cada pergunta nasce com metadados: `fatia`, `armadilha`, `formato_fonte`, `idioma`, `dificuldade`, `feature_alvo` (qual pacote R/C ela existe para medir).
5. Renderização multi-formato do mesmo conteúdo: python-docx/openpyxl/pptx + LibreOffice headless para gerar `.doc/.xls/.ppt` legados e PDFs (inclusive digitalizado-sintético: renderizar página como imagem para testar OCR/R1.2).

**Aceite.** `py -m eval.gerador --seed 42 --out <dir>` reproduz o corpus; CI gera e roda o harness nele; manifesto com hash do corpus por versão.

---

## E2 — Matriz de armadilhas: o conteúdo do sintético mapeado ao roadmap — **P0** · Dono: notebook (é o dono do eval)

Cada linha é uma fatia com ≥30 perguntas, criada para medir features específicas. A matriz É o requisito do gerador:

| Fatia | Armadilhas plantadas | Mede (pacotes) |
|---|---|---|
| Nomes ruins | `IMG_2034.pdf`, `Doc1.docx`, `scan_final2.pdf` com conteúdo importante | peso do nome, C3.a, R6.1 |
| Versões | famílias `_v1.._v9_final_FINAL(2)`, conteúdo 5/15/40% divergente, resposta só na versão certa | C6, R1.3 |
| Duplicatas exatas | mesmo arquivo em 3-8 pastas (backup, cópia) | R1.3, métrica duplicatas@10 |
| Cross-lingual | doc EN + pergunta PT e vice-versa; misto no mesmo doc | C4, R3.1, R6.2 |
| Siglas | definidas 1×/2×, ambíguas por pasta, nunca definidas | C2 |
| Planilha-despejo | 100k+ linhas, resposta = "existe fornecedor X?" | C7 digesto |
| Planilha-modelo | valuation com rótulo esparso, fórmula sem cache, named range | C7.a/b/c — pergunta-guarda do valuation |
| CSV grande | 50-100 MB, delimitadores variados | C7.d |
| Legado OLE | `.doc/.ppt/.xls` reais gerados via LibreOffice | R1.1 |
| OCR | PDF-imagem sintético com texto conhecido | R1.2 |
| Multi-hop | resposta exige 2-3 docs encadeados por identificador | neighbors, grafo, n≥30 (hoje n=5!) |
| Temporal | "versão vigente", "em 2019", datas conflitantes | R6.3, C6 |
| Distratores | docs quase-relevantes que NÃO respondem (hard negatives plantados) | rerank R6.2, precisão do top-k |
| Estrutura de pastas | mesma pergunta com taxonomia rica vs pastas planas | R2.1 (contexto de pasta) |
| Venenosos | PDFs truncados, ZIP renomeado, 0 bytes | R1.4 quarentena (mede robustez, não ranking) |
| Escala | perfil 100k docs por amostragem/inflação | R4.x, portas de latência |

**Aceite.** Toda feature P0/P1 dos dossiês R/C tem ≥1 fatia que a mede; harness reporta por fatia; `docs/matriz-de-armadilhas.md` mantém o mapeamento feature↔fatia.

---

## E3 — Protocolo de três camadas + disciplina de set selado — **P0** · Dono: acordo entre setups (muda a regra de decisão do projeto)

1. **Dourado real = regressão.** Congelado como `dourado-v1` (51 perguntas, números históricos preservados — a série F1→F2 continua comparável para sempre). Cresce por acréscimo (`v2`, `v3`...), nunca por edição. Continua rodando em toda ablação; regressão nele bloqueia merge. **Deixa de ser critério de adoção de arquitetura.**
2. **Sintético = decisão.** Dividido em **dev-set** (ajuste livre, visível aos agentes) e **test-set selado** (seed secreta do gerador, guardada fora do repo; rodado só em fecho de fase). É a defesa anti-Goodhart: os agentes otimizam contra o dev, o selado detecta overfitting. A cada fase, o selado atual vira dev da próxima e um novo selado é gerado com seed nova — rotação barata porque o gerador é código (E1).
3. **Externo = alarme.** MIRACL-PT amostrado conforme C5 (porta de custo mantida). Se o sintético melhora e o MIRACL despenca, a suspeita é endogamia do gerador.
4. **Regra de leitura por fatia:** média agregada não decide nada; toda ablação reporta a tabela completa de fatias e destaca as que cruzaram o limiar de ruído (E5).

**Aceite.** `ARCHITECTURE.md` ganha a seção "Protocolo de avaliação"; harness roda as 3 camadas com um comando; fecho de fase exige rodada no selado com resultado registrado.

---

## E4 — Loop adversarial por fase (red-team de agente, não GAN) — **P1** · Dono: notebook

Sobre a ideia de conjuntos adaptativos tipo adversarial networks: **a intuição está certa; o mecanismo GAN, não.** Treinar um gerador contra o retriever é caro, instável e produz perguntas patológicas sem valor de produto. O estado da arte real é o **modelo DynaBench**: humanos (aqui, agentes) tentam quebrar o sistema; as quebras viram casos permanentes do benchmark; o benchmark evolui em degraus versionados, não continuamente. Exatamente a sua última frase — "a cada fase melhorar o conjunto com os aprendizados" — institucionalizada:

1. **Rito de fecho de fase (1 sessão de agente):** o agente red-team recebe o corpus sintético + as tools MCP e a instrução "encontre 20 perguntas cujo doc-resposta existe mas não aparece no top-10". Técnicas: parafrasear até quebrar, usar vocabulário do usuário e não do documento, explorar as fatias vencedoras da fase (o que acabou de melhorar é o que se tenta quebrar).
2. Quebras confirmadas (doc existe, retrieval falha) são **destiladas em casos mínimos** e entram no dev-set da fase seguinte com metadado `origem=redteam-f<N>`.
3. Falhas do mundo real entram no mesmo funil: pergunta real que falhou → anonimizar → replantar equivalente no sintético (a versão real pode ir ao dourado-v2 se não vazar nome).
4. **Guarda anti-patologia:** caso red-team só entra se um humano (ou o outro agente) confirmar que a pergunta é *razoável* — perguntas que nenhum usuário faria não entram (é o filtro que o DynaBench aprendeu a precisar).
5. Assimetria de agentes é bônus: Grok red-teama o que Claude otimizou e vice-versa — o viés de um não é o viés do outro.

**Aceite.** `docs/redteam-f<N>.md` por fase (quebras, casos destilados, taxa de sobrevivência das quebras da fase anterior — que deve cair); ≥15 casos novos por fase; nenhum caso sem confirmação de razoabilidade.

---

## E5 — Rigor estatístico mínimo — **P1** · Dono: notebook

O harness hoje compara médias secas. Com n pequeno isso já produziu decisões no fio do ruído:
1. **IC bootstrap (1.000 reamostragens) para toda métrica**; ablação reporta `Δ ± IC95`. Barato: ~30 linhas em `metrics.py`, numpy já presente.
2. **Regra de adoção:** feature só "ganha" se o IC do Δ na fatia-alvo exclui zero; empate estatístico = decisão por simplicidade (não adotar).
3. **n mínimo por fatia = 30** (é o que dimensiona as ≥500 perguntas de E1).
4. Teste pareado (a mesma pergunta antes/depois) em vez de comparação de agregados — mais potência com o mesmo n.

**Aceite.** Harness imprime IC em toda tabela; `docs/` de ablação novos incluem IC; uma ablação antiga re-analisada como demonstração (candidata: rerank F2, onde o ganho foi de poucos pontos).

---

## E6 — Preservação e uso honesto da base real — **P2** · Dono: notebook

A base real continua insubstituível para o que o sintético não imita: sujeira orgânica (OLE de 2009 corrompido de verdade, PDF de scanner real, taxonomia de pastas que cresceu 20 anos). Papel dela no novo protocolo:
1. **Calibrador de realismo do gerador:** as distribuições do censo real (tamanhos, formatos, profundidade de pastas, % planilhas — já medidas em `censo.md`) parametrizam o gerador E1. O sintético herda a *forma* do real sem herdar o conteúdo.
2. **Fonte de casos, não de decisões** (funil E4.3).
3. **Rótulo permanente de viés:** toda tabela que citar o dourado real carrega a nota "acervo único, nomes informativos, n=51 — não usar como critério de arquitetura" (uma linha no harness).

---

## Respostas diretas às perguntas levantadas

- **Benchmark externo ou sintético próprio?** Os dois, com papéis distintos: sintético-por-código decide (gabarito perfeito, cobre exatamente as features do SEU roadmap — nenhum benchmark externo tem planilha-modelo com fórmula sem cache); externo amostrado só alarma contra endogamia (C5 mantido). BEIR/MIRACL puros não servem como juiz: são passagens de texto limpo, sem arquivos, sem versões, sem pastas — não medem 80% do que este produto faz.
- **Como introduzir sem perder o progresso?** Congelando, não substituindo (E3.1): a série histórica F1→F2 permanece válida e comparável; o dourado vira camada de regressão com a honra intacta.
- **Adaptativo/adversarial?** Sim, em degraus versionados com agente red-team e filtro de razoabilidade (E4); não como GAN contínua.

## Ordem de ataque

| Onda | Pacotes | Racional |
|---|---|---|
| 1 | **E1 + E2** (juntos: gerador + matriz) | pré-requisito de tudo; as ablações R3.1/R6.2/C3 pendentes já deveriam rodar nele |
| 2 | **E3 + E5** | protocolo e estatística antes da próxima decisão de arquitetura |
| 3 | **E4** | primeiro red-team no fecho da fase corrente |
| 4 | **E6** | contínuo, barato |

**Interações:** E1/E2 implementam e superam R9.1; E3 absorve C5 (porta MIRACL mantida); E5 altera o harness usado por TODAS as ablações R/C pendentes — **rodar E-onda-1 antes de fechar R3.1 (modelo) evita congelar o modelo errado por ruído**.

## Fontes

- RAGAS — synthetic testset generation (evolução de perguntas): https://docs.ragas.io/en/latest/concepts/test_data_generation/
- Kiela et al., **DynaBench: Rethinking Benchmarking in NLP** (NAACL 2021) — benchmark dinâmico com humano-no-loop: https://aclanthology.org/2021.naacl-main.324/
- Thakur et al., **BEIR** (NeurIPS 2021) — heterogeneidade de domínios em avaliação zero-shot: https://arxiv.org/abs/2104.08663
- Zhang et al., **MIRACL** (TACL 2023) — retrieval multilíngue, fatia PT: https://arxiv.org/abs/2210.09984
- Voorhees — test collections TREC e viés de pooling: https://trec.nist.gov/
- Framework multi-agente para QA sintético de RAG (arXiv 2508.18929, 2025): https://arxiv.org/html/2508.18929v1
- Smucker, Allan & Carterette — testes de significância em IR (CIKM 2007) — base do E5: https://dl.acm.org/doi/10.1145/1321440.1321528
- Internas: `docs/ablacao-bm25-com-nome.md` (declaração do viés de origem das perguntas), C5/C7 do update, R9.1/R9.2 do dossiê.
