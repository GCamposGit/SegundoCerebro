# J.d — `pack_folder` no Desktop

02/09/2026. Empacotamento de pasta sob orçamento; não inclui exportação de vault
nem novo motor de OCR. O notebook original está desativado.

## Contrato e aceite

Defeito para base desconhecida: o agente que precisa cobrir uma pasta ou corta
no meio de um documento, ou relê, ou mistura versões da mesma família, e não tem
como auditar o que ficou de fora.

Aceite binário:

- pasta sintética VCE com 30+ documentos e famílias plantadas: um agente com
  orçamento limitado cobre 100% dos canônicos em N passadas, sem repetição e
  sem corte intra-documento;
- `politica=canonicos` nunca omite família inteira — o vigente sempre entra;
- todo separador carrega `id` e caminho original.

Qualquer falha bloqueia o pacote. Não há hipótese de ganho de retrieval.

## O que a tool faz

`pack_folder(pasta="", budget_chars=8000, cursor=null, politica="canonicos", ids=null, recursivo=false)`
devolve um bundle Markdown **manifesto primeiro**, depois os canônicos inteiros.
Orçamento estourado corta na fronteira de documento: se o próximo não cabe no
que resta, vai para a página seguinte; se é o primeiro da página, entra inteiro
mesmo acima do orçamento. Nunca fatia o Markdown de um arquivo.

Políticas:

- `canonicos` — um membro por família, a vigente de `retrieve/familias.py`
  (número declarado vence; data desempata). É a mesma regra do manifesto.
- `todos` — cada arquivo com identidade.
- `apenas_listados` — só os `ids` (ou caminhos) pedidos, na ordem pedida.

Arquivo `so_censo`, sem hash ou sem canônico não entra no bundle: aparece em
`omitidos` com motivo. A família não some.

O cursor é opaco (`pf:1`), ligado à pasta, política, seleção e chaves de parse.
Se a pasta mudar, pede reinício. `total` e `restante` contam documentos
packáveis, não caracteres.

## O que não faz

Não resume, não interpreta, não ranqueia, não escreve no acervo, não inicia OCR
novo, não substitui `get_document` para um arquivo grande que o agente quer
paginar por seção. MinHash/`R1.3` continua absorvido por `C6` e **não** entra.

## Reuso

`list_folder` (enumeração + censo), `familias.py` (canônico), Parse Store e os
portões de `get_document` (cache, original, isolamento). Zero dependências
novas. Fontes da especificação: o próprio pacote J e o padrão manifest-first de
[Repomix](https://github.com/yamadashy/repomix).

## Validação

Testes sintéticos VCE cobrem famílias, as três políticas, paginação por
orçamento, cursor inválido, `so_censo` omitido, ordem estável e a tool MCP.
A guarda derivada de `tests/test_leitura.py` passou a incluir `pack_folder`:
tool de leitura nova sem caso de cursor reprova. Protocolo stdio empacota a
pasta da política fictícia sem carregar encoder.

O dourado privado segue indisponível neste Desktop; não há Δ de ranking — e
não pode haver: nenhuma linha de `retrieve/hybrid.py` mudou.
