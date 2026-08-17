# Resposta à revisão técnica de 12/08/2026

A revisão é boa e a maior parte dela está certa. Este documento registra o que
foi **incorporado**, o que ficou **registrado com gatilho** e o que foi
**recusado**, sempre com o motivo — porque uma recomendação recusada sem
justificativa volta como surpresa três meses depois.

O critério de triagem foi um só: **incorporar agora o que corrige defeito
demonstrável ou muda a próxima medição.** O resto entra quando houver evidência
de que é necessário, que é a mesma regra (I4) aplicada à própria revisão.

---

## 1. Incorporado imediatamente — corrigia defeito real

### 1.1 Orçamento por tokens, não por caracteres

**A crítica estava certa e o defeito era pior do que a revisão supôs.**

O limite era 1.800 caracteres, derivado de uma medição real (4,49 chars/token em
português ⇒ 512 tokens ≈ 2.298 caracteres). Mas a revisão apontou a tensão
correta: bloco de planilha e de tabela **nunca era cortado** pela regra de
tamanho, e a média medida era **6.655 caracteres** — muito além da janela. Esses
blocos iam inteiros para o encoder e eram **truncados em silêncio**.

Implementado:

- `ChunkConfig` recebe `max_tokens` e `contar_tokens`; o indexador injeta o
  orçamento real (`spec.max_tokens - 24` de margem) e o tokenizador do modelo
  ativo.
- A contagem é feita sobre o **texto do embedding**, incluindo o cabeçalho
  contextual — que também consome tokens, como a revisão observou.
- Tabela e planilha acima do orçamento passam a ser cortadas **por linha, com o
  cabeçalho repetido em cada pedaço**, preservando o alinhamento coluna/valor
  que motivava o "nunca cortar".
- Testes fixam a garantia: nenhum chunk sai acima do orçamento, e o cabeçalho
  aparece em todos os pedaços de uma tabela partida.

Efeito colateral: encontrei um laço infinito no cortador — com limite reduzido
dinamicamente e sobreposição fixa de 200, o recuo chegava a zero e o texto nunca
diminuía. Travou a suíte inteira. Corrigido com avanço mínimo garantido.

### 1.2 Hash de conteúdo na decisão de reindexar

**Certa.** O `sha256` já era calculado e gravado, mas a decisão usava só
`(tamanho, mtime)`. Sincronização, restauração e cópia de volta mudam `mtime`
sem mudar conteúdo, e isso forçava reembedding inútil — caro justamente no
cenário de 39 h com o e5.

Implementado como triagem em dois níveis, como a revisão sugeriu:
`(tamanho, mtime)` decide se vale abrir; o `sha256` decide se vale reembeddar.
Documento com conteúdo idêntico e `mtime` novo agora atualiza só o registro, e o
progresso reporta essa categoria à parte (`inalterados`).

### 1.3 Impedir mistura silenciosa de espaços vetoriais

**Certa, e apontou um caso que meu teste não cobria.** Eu tinha `model_id` por
documento e troca de modelo reindexando tudo — mas durante uma troca
**interrompida** a tabela de vetores contém dois espaços ao mesmo tempo, e a
busca densa compararia os dois sem avisar.

Implementado: `model_id` passou a ser coluna da tabela de vetores, e toda busca
densa filtra por ele. O filtro é aplicado antes da busca (`prefilter`), não
depois.

---

## 2. Incorporado como método — mudança de gate, custo zero

### 2.1 Porta das armadilhas: por caso, não por taxa

**Certa.** Com 6 perguntas, cada uma vale 16,7 pontos percentuais e "≥ 0,85" não
estima nada. Novo critério: **ao menos 5 de 6, e nenhuma falha em caso
crítico**, com relatório individual. Já está no ROADMAP.

### 2.2 Orçamento de regressão em vez de regressão zero

**Certa.** "Zero regressão" reprovaria uma mudança que melhora trinta perguntas
e piora uma. Novo critério: nenhuma regressão em caso crítico, no máximo 3
perguntas caindo do 1º lugar, cada uma inspecionada individualmente.

### 2.3 Fronteira do I1 explicitada

Aceito o esclarecimento, **não** a reformulação. O texto do I1 continua estrito
porque a motivação declarada do projeto é previsibilidade de custo, não apenas
independência operacional — e a versão estrita é a que protege isso.

Mas a fronteira do que é "consulta" passa a estar escrita: **reranking local,
leitura de documento e expansão de contexto fazem parte do caminho de consulta;
a geração no cliente não.**

### 2.4 I2: não gerar texto ≠ devolver só chunk cru

**Esclarecimento útil e adotado.** O servidor pode devolver estrutura derivada
deterministicamente sem violar o I2: trecho destacado, termos que causaram o
match, contexto pai, metadado normalizado, agregação exata, valor de célula,
relação entre documentos. Nada disso é geração livre. Registrar isso evita que o
I2 seja lido no futuro como proibição de enriquecer o retorno.

---

## 3. Registrado com gatilho — certo, mas não agora

Cada item tem o gatilho que o torna necessário. Não é "algum dia".

| Recomendação | Por que não agora | Gatilho |
|---|---|---|
| **Gerações de índice + troca atômica** | O modo de falha atual é limitado: uma interrupção no meio de um documento deixa **esse** documento indisponível, e reindexar corrige. Não há usuário dependendo do índice | Antes de qualquer uso não-interativo ou compartilhado |
| **Lookup estruturado de planilha (SQLite/DuckDB)** | É a resposta certa e a revisão está certa que embedding não faz igualdade exata. Mas é subsistema novo, e o digesto atual ainda não foi medido pelo eval | F3, ou antes se `g021`/`g030`/`g045` falharem por não achar o valor |
| **Representação canônica persistida** | Reparsear o corpus custa ~37 min hoje, o que é tolerável. O valor aparece quando o parsing fica caro | Quando OCR entrar, ou quando o corpus passar de ~10 mil documentos |
| **Parent-child e busca hierárquica** | São otimizações de ranking e precisam de ablação. Adotar sem medir viola o I4 | F2, junto com o reranker |
| **RRF ponderado, boost por campo, classificação de consulta** | Mesmo motivo. O índice lexical por campos já entrou parcialmente (nome de arquivo virou campo indexado) | F2 |
| **Roteamento adaptativo de PDF** | Os dois motores já convivem no código; falta a ablação `fonte` vs `layout` com nDCG | F2 |
| **Fila de OCR assíncrona** | ~45 PDFs digitalizados projetados, hoje marcados e não indexados. O buraco é conhecido e pequeno | F3, ou se uma pergunta real cair num deles |
| **Cabeçalho/rodapé repetido em PDF** | Contamina embedding e BM25, a revisão está certa. Barato de fazer | F2, junto com a ablação de parser |
| **Marcar conteúdo recuperado como dado não confiável (prompt injection)** | Só faz sentido quando existir superfície MCP | F3, obrigatório antes de expor as ferramentas |
| **Primitivas extras** (`search_within_document`, `get_outline`, `list_versions`, `fetch_parent_context`) | Boa entrada de projeto para a superfície | F3 |
| **Evidence-set recall** (evidência no trecho, não só documento certo) | **A lacuna mais importante da lista.** Exige anotar o conjunto dourado com o trecho mínimo esperado, o que é trabalho humano | Assim que houver um segundo lote de perguntas; a métrica já cabe no harness |
| **Ampliar conjunto dourado para centenas** | Cada pergunta custa conferência manual de fonte. 51 já expõem os defeitos que estamos corrigindo | Contínuo, com perguntas de uso real |
| **Observabilidade completa** | Ingestão já reporta status, tempo e contagem por formato. Latência por etapa só importa quando houver consulta em uso | F3 |
| **ACL, identidade, auditoria, threat model** | Já é invariante: o índice herda o acesso de quem indexou e **não pode ser compartilhado** antes disso. A revisão concorda que precede multiusuário | F5, e é bloqueante — não acabamento |

---

## 4. Recusado, com motivo

**Reestruturar o repositório em camadas (`domain/`, `ranking/`, `security/`…).**
A estrutura atual (`ingest/`, `index/`, `retrieve/`, `mcp/`, `eval/`) mapeia as
fases do roadmap e tem 123 testes em cima. Reorganizar agora é churn sem
mudança de comportamento, e o desacoplamento que a proposta busca — domínio
independente de LanceDB e SQLite — já existe onde importa: os parsers recebem
bytes e não conhecem o índice; o `Retriever` é um protocolo.

**Reformular o I1.** Ver §2.3: aceito o esclarecimento da fronteira, mantida a
redação estrita.

---

## 5. Correções à própria revisão

**O mojibake não existe nos arquivos.** A revisão aponta "o texto fornecido
contém mojibake UTF-8/Windows-1252". Os documentos do repositório são UTF-8
íntegros — o que apareceu foi renderização do console do Windows (codepage 850)
em saídas de terminal que eu colei durante o trabalho. Vale conferir abrindo os
`.md` direto, porque a conclusão oposta colocaria em dúvida os artefatos.

**Não existe e5 pequeno no `fastembed`.** A recomendação de "avaliar família
multilingual E5 e BGE-M3" pressupõe disponibilidade que o catálogo não tem: na
versão 0.8.0 o único e5 é o `multilingual-e5-large` (2,24 GB, 0,63 chunks/s
nesta máquina) e **BGE-M3 não está no catálogo, nem denso nem esparso**. Uma
ablação ampla exige sair do `fastembed` — `FlagEmbedding` ou ONNX exportado à
mão — o que é trabalho de infraestrutura, não troca de string de configuração.

**"384 dimensões não significam baixa qualidade" — concordo, e o problema é
outro.** Achei a causa provável enquanto respondia a revisão: o modelo escolhido
é `paraphrase-multilingual-MiniLM`, treinado para **similaridade simétrica entre
frases**, não para recuperação assimétrica pergunta→passagem. Não é questão de
dimensão, é família errada. A primeira medição do denso deu recall@1 = 0,137, o
que é consistente com isso. A ablação precisa incluir modelo treinado para
retrieval, e no `fastembed` isso só existe no e5-large.

---

## 6. O que a revisão não viu e que já mudou

Dois defeitos foram encontrados por medição própria enquanto a revisão era
escrita, e ambos são do tipo que ela se preocupa:

**O nome do arquivo não estava no índice.** O baseline da F0 tira recall@1 =
0,55 lendo **só** nome de arquivo e caminho. A primeira versão do índice de
conteúdo ignorava esse sinal por completo e ficou em 0,26 — pior que o baseline
burro. Corrigido: `caminho` virou coluna indexada no FTS5, e o nome do documento
entrou no texto do embedding (chunker v2). É a recomendação de "busca por
campos" da revisão, chegando por outro caminho.

**`--prefixo` re-enraizava em vez de filtrar**, encurtando todo caminho gravado
em uma pasta e tornando toda fonte esperada impossível de casar. O eval reportaria
recall zero e a culpa cairia no ranqueador.

Os dois ilustram o ponto central da revisão melhor que qualquer recomendação: a
unidade de versionamento e identidade tem que ser explícita, senão o erro aparece
como "qualidade ruim" em vez de "defeito".
