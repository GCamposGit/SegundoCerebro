# CLAUDE.md — Segundo Cérebro RAG

Guia de desenvolvimento para o Claude Code neste projeto.

---

## O que é este projeto

Servidor **MCP** de recuperação sobre base de conhecimento pessoal/corporativa.
Não gera texto, não tem UI. Ver [ARCHITECTURE.md](ARCHITECTURE.md) para as
decisões e [ROADMAP.md](ROADMAP.md) para as fases.

## Estado atual

**F1 medida, F3 iniciada.** Ler `docs/estado-f1.md` primeiro — é o retomador de
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

**F1 medida na condição C em 16/08/2026 — a fase NÃO fecha.** Ler
`docs/portas-f1-condicao-c.md`. Portas 1, 2 e 5 passam com folga (recall@1 0,600
contra 0,467 do baseline; MRR 0,736 contra 0,592); portas 3 e 4 reprovam (4 de 6
armadilhas, exige 5; 1 de 5 multi-hop, exige 3). As duas armadilhas que falham
falham **também no baseline** e são F2 por descrição — família de versão e
discriminação entre documentos irmãos. **O gargalo é precisão**, que era
exatamente a pergunta que a inversão F2/F3 deixou em aberto.

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

Falta da F3.5-D: **retomada automática depois de reinício** (marcador + tarefa
agendada no logon). A base já está pronta — commit por documento, WAL, e trava
que sobrevive a reuso de PID.

```bash
py -m segundocerebro.index.indexer --perfil leve   # cede a vez, recusa bateria
```

**F2 em curso desde 16/08/2026 — três entregas medidas.** recall@1 saiu de 0,600
para **0,678** e MRR de 0,736 para **0,785** na condição C:

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

**A lição que se repetiu duas vezes:** neste acervo o consenso de ranqueadores
independentes vale mais que qualquer juiz isolado. Aconteceu com o bm25 (13/08) e
com o cross-encoder (16/08). Desconfiar de mecanismo que proponha reordenar
sozinho.

Armadilha do catálogo, repetida: o `bge-reranker-v2-m3` que o ROADMAP nomeava
**não existe no `fastembed`**, igual ao BGE-M3 denso. Conferir catálogo antes de
escrever o nome de um modelo no plano.

**Painel com tela** desde 16/08 — `painel/index.html`, servido pelo próprio
Starlette, sem npm e sem nada vindo de fora. Perfis com o custo de cada um à
mostra, diagnóstico de consulta e conjunto dourado crescendo do uso real.

378 testes.

**Próximo passo:** medir a F1 na condição C, agora que o índice está completo. Em
paralelo, a tela do painel — perfis medidos, diagnóstico de consulta e o conjunto
dourado crescendo do uso real.

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
