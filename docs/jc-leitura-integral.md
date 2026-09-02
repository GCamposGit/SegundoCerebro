# J.c-conteúdo — leitura integral no Desktop

02/09/2026. Implementação de `get_document`; não inclui `pack_folder`, exportação
nem novo motor de OCR. O notebook original está desativado.

## Pesquisa e decisão

Pesquisa dividida entre dois subagentes `gpt-5.6-luna`, com escopos pequenos:
contrato MCP/segurança e stores/serialização. Fontes primárias conferidas pelo
agente principal. Não foram instaladas bibliotecas ou executados repositórios
externos. A comparação abaixo é de adequação arquitetural, não benchmark dos
produtos concorrentes.

- [MCP: paginação](https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination)
  especifica cursores opacos nas operações de **listagem**. Não é um protocolo
  pronto de paginação de conteúdo de PDF; `get_document` declara seu contrato
  próprio, sem fingir que `resources/read` tem cursor padronizado.
- [MCP: tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
  orienta retorno estruturado e texto JSON compatível com clientes antigos,
  indicação `isError` para falhas de execução e validação de entradas. Usamos o
  SDK MCP já instalado; não criamos servidor ou transporte paralelos.
- [Servidor filesystem oficial](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/lib.ts)
  fornece referência concreta de contenção de caminhos e tratamento de links.
  Reusamos a configuração e as exclusões do censo local. O servidor de referência
  lê arquivos, mas não substitui nosso parse canônico de PDF/Office.
- [Docling: serialização](https://docling-project.github.io/docling/concepts/serialization/)
  separa representação estruturada de renderização Markdown. Mantemos os blocos
  e offsets existentes; Markdown não é reprodução visual fiel de toda tabela
  ou imagem. Adotar Docling só para paginar duplicaria nosso pipeline de parse.
- [LlamaIndex: refresh por hash](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/indices/base.py)
  é referência de identidade/versionamento de documentos. Já temos SHA-256,
  parser, rota e assinatura do motor no Parse Store; não precisamos de um novo
  docstore ou índice para esta função.
- [Tika: modelo de segurança](https://tika.apache.org/security-model.html)
  reforça isolamento e limites ao tratar arquivos. Reutilizamos `parse_isolado`
  e o portão de bytes do reader, em vez de chamar parsers diretamente no MCP.

**Decisão:** implementar apenas a camada de resolução, paginação e adaptação
MCP. Zero dependências novas; nenhuma alteração em ranking, chunking ou modelos.

## Contrato e limites deliberados

`get_document(documento, cursor=null, max_chars=8000)` aceita caminho relativo,
id ou URI da base do processo. Resolve apenas documentos registrados com hash;
arquivos `so_censo` devem ser indexados primeiro. Referências não selecionam outra
base. `read_note` segue atendendo trechos de busca.
Se houver o mesmo caminho relativo em outra raiz configurada, exige id ou URI;
um arquivo só no censo não pode ser confundido com seu homônimo já indexado.

A concatenação de `markdown` até `completo=true` é exatamente o canônico. Cada
resposta inclui total, restante, `restante_chars`, offsets globais e procedência.
O orçamento conta code points Unicode: não tokens, bytes ou o envelope JSON.
Combinações de caracteres podem atravessar a fronteira, sem perda na concatenação.
O teto é 32.000 caracteres de Markdown e 200 blocos por página; quando os blocos
limitam antes dos caracteres, o cursor continua o texto restante normalmente.

Metadados incluem título derivado do nome (não inventado), original, raiz,
caminho preferido entre duplicatas idênticas, hash, datas, tamanho, páginas,
blocos, parser, rota e chave de família pela regra existente. A família não
seleciona outra versão para substituir o documento solicitado.

Cursores vinculam base, índice físico, original, hash, chave de parse,
conteúdo e sidecar. São opacos, versionados, limitados a 256 caracteres e não
conferem autorização. Não precisam de assinatura: alterar uma posição não
permite sair do documento que foi novamente resolvido e autorizado. Reiniciar o
processo mantém o cursor válido se todos esses dados continuarem iguais.

Em cache quente não se reabre o conteúdo do original. Com raízes configuradas,
tamanho e datas são conferidos; alterações comuns interrompem a leitura.
**Não é detecção criptográfica de toda alteração ao vivo**: quem preservar os
metadados pode deixar o cache da versão indexada válido. O conteúdo entregue
continua sendo a versão identificada pelo hash registrado. Sem raízes, somente
cache quente é servido, com a ausência de conferência declarada.

Miss/corrupção reconstrói via `parse_isolado`, sem escrever no registro ou criar
vetores. O hash do original precisa coincidir antes de persistir o resultado.
Mantém a mesma seleção de cache/rota e invalidação LibreOffice da indexação.
Não aciona OCR novo; quando o registro exige OCR, não regride silenciosamente
para a extração nativa. Um documento pode ter todo o **canônico** entregue e
ainda conter páginas ou células não extraídas: os avisos tornam isso explícito.

Extração interativa: 50 MB no máximo (ou limite menor da base), teto de 60 s
para formatos isolados, RAM derivada do orçamento existente e uma extração por
servidor. Texto simples segue a rota leve do parser existente, com teto de bytes.
Arquivos mais custosos devem ser preparados pelo indexador antes da leitura.
Nenhum placeholder é hidratado; nenhum artefato derivado fica no acervo.

Validação de caminho recusa absolutos, traversal, ADS, links e junctions abaixo
da raiz, inclusive atalhos do cache para fora do índice. Isso **não é uma
sandbox contra um processo local malicioso** trocando caminhos durante a
operação. Raízes e diretório do índice devem ter permissões confiáveis.
Respostas de erro não repassam os detalhes internos de exceções de disco/parser.

O cache valida tipos, identidade e offsets, além do zlib/JSON. Escritas usam
temporários exclusivos, substituição atômica e até três esperas curtas
(140 ms no total) para disputas transitórias de handles no Windows. Erros
persistentes continuam visíveis; não há retry infinito.
Uma prova concorrente também revelou que o Windows pode devolver o mesmo caminho
com e sem prefixo longo enquanto a pasta nasce. A comparação agora reutiliza a
normalização do censo; há teste determinístico dessa equivalência e cinco rodadas
de 40 escritas concorrentes com oito threads.

## Plano de testes e critério de encerramento

1. Testes rápidos e determinísticos de Unicode, orçamento variável, vazio,
   tetos, sidecar e cursor inválido/desatualizado; catálogo de paginação deriva
   todas as tools registradas para não esquecer a nova ferramenta.
2. Cache frio/quente/corrompido, hash divergente, mudanças entre páginas,
   recusa de regressão OCR, limites, placeholders, exclusões, bases e junctions.
3. Concorrência real de escrita e falhas de substituição no Windows; limites de
   retry, ausência de temporários órfãos e preservação da entrada anterior.
4. PDF sintético **real**, com 500 páginas, percorrendo extração isolada + store
   + paginação. A concatenação deve coincidir com o canônico do parser e os
   localizadores devem alcançar as 500 páginas.
5. Transporte MCP real por stdio: esquemas publicados, página + continuação,
   Unicode, erros com `isError` e equivalência JSON/structuredContent.
6. Ausência de carregamento do encoder na leitura e reaproveitamento do Store
   ao iniciar a busca. Registro e original permanecem iguais após cache miss.
7. Suíte padrão completa, Ruff, Pyright e tetos de tamanho dos módulos/funções.

**Efeito mínimo:** igualdade byte a byte da concatenação com o canônico, ausência
de escrita no acervo/registro e isolamento de referências. Qualquer violação
mantém o pacote aberto. Aceite binário; nenhuma varredura de hiperparâmetros.

O dourado/corpus privados não estão no Desktop; a ablação de retrieval real
não foi executada e nenhum Δ real é declarado. A meta de ganho ≥80% de rebuild
também permanece não medida. O novo OCR segue no roadmap futuro; o freeze do
schema do sidecar com E4 e `pack_folder` são outros pacotes.

## Resultado da validação local

- Suíte completa: **1.619 aprovados, 16 pulados, 55 desmarcados**, em 167,72 s.
- Após a última guarda de homônimos entre raízes: **256 testes focados aprovados**
  em 28,72 s, abrangendo leitura, cache, MCP/stdio, documentação e tetos de tamanho.
  A suíte completa não foi repetida após esse ajuste pequeno; a revalidação foi
  dirigida aos módulos e contratos afetados.
- Ruff e Pyright aprovados; `git diff --check` sem problemas.
- Cinco rodadas de 40 escritas concorrentes; PDF sintético de 500 páginas
  recomposto sem perda nem duplicação. Nenhum dado privado usado nestas provas.
