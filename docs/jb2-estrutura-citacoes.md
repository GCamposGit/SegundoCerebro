# J.b2 — contrato de estrutura para citações

Desktop, 02/09/2026. Corpus de validação sintético; sem mudança de ranking,
chunking, modelos, algoritmos dos parsers ou Markdown canônico.

## Escopo e aceite

Defeito: a leitura integral já expunha posições, mas não declarava a convenção
completa nem entregava a trilha de seções e o ordinal global. Consumidores
poderiam confundir uma fatia de transporte com uma página do original.

Aceite binário: cada intervalo seleciona exatamente o texto do bloco; metadados
mantêm-se iguais em todas as fatias; posições inválidas são recusadas na gravação
e leitura; cache legado válido permanece legível. Qualquer falha bloqueia entrega.
Não há hipótese de ganho de retrieval neste pacote.

Escopo fechado: `ingest/estrutura.py`, `ingest/parse_store.py`,
`acesso/pagina_documento.py`, testes de estrutura, leitura integral e protocolo,
este documento, guia MCP, `CLAUDE.md` e `ROADMAP.md`.

## Contrato v1

- `estrutura.versao = blocos:1`. O sidecar continua no mesmo arquivo atômico do
  Parse Store; não existe uma segunda representação ou banco de citações.
- `inicio` inclusivo e `fim` exclusivo, base zero, em code points Unicode do
  Markdown canônico completo. Não são bytes, tokens, unidades UTF-16 nem offsets
  do arquivo original. Clientes JavaScript devem contar code points, não `.length`.
- `ordinal` identifica o bloco, base zero, na ordem do documento, dentro de
  `versao` da resposta. Não permanece válido depois de reparse ou alteração.
- `trilha` é a hierarquia completa de seções fornecida pelo parser, inclusive
  além dos seis níveis visuais do Markdown; vazia significa não disponível.
- `onde` preserva o localizador original. `pagina` e `slide`, base um, só são
  preenchidos para as convenções exatas `p. N`, `slide N` e `slide N (notas)`.
  Nos demais casos são `null`: tabela de Word, aba de planilha e timestamp não
  são páginas. Não inferimos paginação pelo título de seção.
- Os intervalos podem conter lacunas: títulos e separadores gerados ficam fora
  dos blocos. Blocos vazios são preservados no store, mas não ancoram citações.
  Não há sobreposição de blocos; uma fatia pode mostrar parte de um bloco, mas
  seus offsets e ordinal continuam globais, sem recortar a identidade.
- Uma citação usa identidade (`documento.sha256`, arquivo/raiz), `versao`, ordinal
  e intervalo. Recorte a fatia com a interseção dos intervalos e subtraia
  `resposta.inicio`; não aplique offsets globais diretamente no texto da fatia.
  A versão vincula base, identidade de parse, conteúdo, sidecar e contrato.

Não se promete reprodução visual, posição em pixels, texto oculto, normalização
de grafemas ou precisão maior que a extração original. Paginação por code points
pode separar um grafema composto entre respostas; concatená-las preserva-o.
`outline` continua um mapa baseado no índice, não uma fonte de offsets canônicos.

## Compatibilidade e pesquisa

A renderização segue `canonico:1`. Entradas anteriores sem `estrutura_versao`
são v1 implícito, após a mesma validação. Versão desconhecida é cache miss;
uma alteração futura incompatível deve também mudar a chave do cache, para
evitar escritores de versões distintas substituindo a mesma entrada.
Campos de `get_document` são aditivos. Cursores anteriores a este contrato
precisam reiniciar a leitura, pois a versão da resposta mudou.

O [W3C TextPositionSelector](https://www.w3.org/TR/annotation-model/#text-position-selector)
define posições base zero em Unicode, com fim exclusivo; adotamos essa convenção,
mas sobre nosso Markdown, sem afirmar conformidade com a normalização HTML do W3C.
O [Docling ProvenanceItem](https://docling-project.github.io/docling/reference/docling_document/#docling_core.types.doc.document.ProvenanceItem)
separa página, região visual e span. Reutilizamos a distinção, não seu pipeline:
o produto já produz blocos e localizadores, e não dispõe de regiões visuais.
Nenhuma dependência nova. Seletores de texto exato/contexto ficam para eventual
reatribuição de citações entre versões, fora deste contrato.

A especificação J chama `E4` de spans citáveis; o roadmap implementado usa `E4`
para red-team. Não há consumidor E4 de spans para homologar. Este pacote consolida
o contrato do produtor e de `get_document`; integração com consumidor futuro
exige revisão própria. Não declaramos aprovação de um componente inexistente.

## Validação

Testes cobrem Unicode multibyte e combinante, blocos vazios, lacunas, hierarquia,
paginação de um caractere, tipos de origem, cache legado/futuro, limites, ordem
e sobreposição. Complementam os property tests existentes sobre os parsers e
a leitura integral de 500 páginas sintéticas. Resultados finais constam no PR.
