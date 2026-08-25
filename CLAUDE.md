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

**F0–F3.6 fechadas. F4 em curso. A F6 — primeiro uso em máquina desconhecida —
passou a ser porta de fase, não trilha paralela.** Os números vivos ficam na §6 de
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
  custo, grafo derivado servindo `neighbors`.
- **Linha de base do acervo corporativo** (n=59, sem rerank, glossário de teste):
  recall@1 **0,551**, MRR **0,680**. Com intervalo:
  [`docs/rigor-estatistico.md`](docs/rigor-estatistico.md). É **piso de
  regressão**, não autoridade de arquitetura.
- **Superfície MCP**: `search`, `read_note`, `neighbors` — dois clientes
  instalados por comando (Claude Code e Claude Desktop).
- **Painel** em `127.0.0.1`: criar base, indexar com barra, pesos, glossário,
  diagnóstico de consulta, ensinar quando erra. Fora do caminho de consulta
  (invariante 6).

**Onde o produto não está pronto**, e é o que a régua de ouro manda olhar
primeiro: OCR de PDF digitalizado, watcher, e o teste da F6 — instalar frio numa
máquina que não é nossa, que segue sendo a porta de fase. O Office legado
(`.doc` `.xls` `.ppt` `.rtf`) **é lido** desde a F4; o que falta ali é o `F4-L`,
o container OLE que mente sobre o próprio conteúdo.

## Próximo passo

1. **`E1` endurecido** — gerador sintético como código versionado, as sete
   condições do laudo ([`docs/avaliacao-pacote-e1.md`](docs/avaliacao-pacote-e1.md)).
   É o instrumento de base desconhecida, e por isso passou **à frente** da `F4-P`
   em 25/08/2026 (a ordem anterior era `E5` → `F4-P` → `E1`).
2. **`F4-P`, encolhida ao defeito** — reconciliar os dois caminhos de
   recuperação, com aceite binário: o caminho que o cliente executa
   (`buscar_chunks`) tem de alcançar o que `search` alcança — cross-lingual
   recall@20 de 0,750 para **1,000** — sem derrubar o piso. **A varredura de peso
   por tipo de fonte sai do escopo**: no melhor caso teórico ela vale +0,032 de
   MRR agregado, com efeito concentrado em 11 perguntas, que é a forma que o `E5`
   provou indetectável.
3. **`F6`** — restam `F6-A`/`F6-C` (desktop) e `F6-B` (estágio 0 do painel). A
   `F6-D` (`docs/comecar.md`) e a `F6-E` (pasta hostil) fecharam em 25/08/2026, e
   o `Q5` P0 — e2e do protocolo MCP — também. Do `Q2` sobram lockfile e extras,
   que são do desktop.

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
- **Recorte derivável não se anota; anotação que o índice não dá se confere a
  cada rodada.** Regra derivada errou por prefixo de pasta e deu número menor e
  plausível — que passaria.
- **Passada separada do indexador vale mais que a economia óbvia.** Grafo: 30 s
  contra 39 h, e foram cinco iterações de regra até a extração ficar certa.
- **Documento sem chunk é invisível até para o ranqueador de nome.** A fronteira
  do índice é de conteúdo, não de nome — formato novo é um conjunto de documentos
  saindo do zero absoluto.
- **Número sem corpus, sem máquina e sem data é mentira** (`colaboracao.md` §4,
  regra 7).

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
- **Nenhuma varredura sem efeito mínimo e fatia declarados antes**; empate
  encerra o pacote.
- **Nenhum defeito consertado sem a classe generalizada** — qual teste ou método
  passa a pegá-la sozinho.

## Contexto do usuário

Ambiente Windows 11, PowerShell. Projeto irmão em `C:\Pytondev\TotalAudioRelator`
(app desktop de gravação de reuniões) — de onde vêm os padrões de LGPD,
`audit_trail.py` e `encryption.py` para reaproveitar na fase F5.
