# F4 — email: MSG e EML, e o documento que não tinha chunk

> Medido em 21/08/2026 no acervo corporativo. As métricas por pergunta estão em
> `docs/metricas-f4-email-*.md` (gitignorado — relatório por pergunta cita nome de
> arquivo do acervo).
>
> Este arquivo é escrito à mão e é onde mora o raciocínio, separado da evidência
> pelo mesmo motivo de `ablacao-f2.md` e `ablacao-f4-grafo.md`: uma regeneração
> não pode apagar em silêncio a conclusão.

## O problema, em uma frase

O registro tinha **48 arquivos `.msg`** e **um arquivo `.pdf` cujo conteúdo é MIME
de email** com status `sem_parser`. Zero chunk cada um — e um documento sem chunk
não é "um documento que a busca acha mal": é um documento que **nenhum ranqueador
da pilha pode devolver**, nem o de nome de arquivo, que é construído sobre
`paths_com_chunks()`. Três perguntas do conjunto dourado corporativo mediam zero
por construção e estavam anotadas `fora_de_escopo: email` desde a F0.

É a mesma geometria que a F4 já encontrou no grafo: o problema não era precisão,
era **existência**. Só que aqui a resposta é mais barata que uma aresta — é um
parser.

## O que a leitura encontrou, antes de qualquer métrica

Rodar o parser nos 48 `.msg` reais, sem indexar nada, é o teste que nenhum teste
unitário substitui — a lição de 19/08 no `CLAUDE.md` ("mock de utilitário do
sistema não prova permissão") vale igual para formato de arquivo:

| Medida | Valor |
|---|---:|
| arquivos lidos | 48 |
| `ok` | **48** |
| falha de parser | **0** |
| `vazio` | **0** |
| com data de envio extraída | **48** |
| com anexo (nome no bloco de cabeçalho) | 40 |
| só envelope, sem corpo textual | 1 |
| blocos gerados | 241 (média **5,0**, máximo 18) |
| caracteres de texto novo | 308.823 |
| chunks gerados, com o tokenizador real | 370 (média 834 caracteres) |

**Média de cinco blocos por arquivo é o achado, não o total.** Um `.msg` deste
acervo quase nunca é uma mensagem: é uma thread de negociação com o histórico
citado embaixo, e o maior tem 18 mensagens. Guardado como bloco único, o
`heading_path` fica vazio e o chunker corta a thread em pedaços de mil caracteres
sem título — a decisão que importa (a última mensagem) dilui-se na negociação
inteira. Partir por mensagem devolve o assunto para a trilha de cada bloco, que é
o que `contextual_text` prefixa antes de embeddar.

**Quarenta dos 48 têm anexo, e é por isso que o nome do anexo entra no bloco de
cabeçalho.** Neste acervo a convenção põe número de contrato e de pedido no nome
do arquivo anexado. Indexar o anexo como documento próprio seria melhor e não foi
feito: o portão de leitura recebe **um** caminho e devolve **um** `ParseResult`, e
mudar isso mexe no laço do indexador, que é do outro setup
(`docs/colaboracao.md` §1).

## O defeito que só o acervo real mostrou, e ele não estava no parser

A linha "370 chunks" da tabela acima é a segunda medição. A primeira não existiu
como número: existiu como **a indexação parando de andar**. Nove núcleos ocupados
por dez minutos num email de reembolso de Uber, e um deles entrou no índice com
**343 chunks** antes de alguém notar.

A causa não é o parser de email nem o chunker isolados — é a interação dos dois.
O chunker respeita um orçamento de **token**, com o tokenizador real, decisão de
17/08 que existe para impedir truncagem silenciosa. Uma URL de rastreio com 400
caracteres opacos consome a janela de 512 tokens **inteira**. Medido nos cinco
emails de reembolso, com o tokenizador de verdade:

| | caracteres de corpo | chunks | caracteres por chunk |
|---|---:|---:|---:|
| antes | 61.862 | **2.931** | 82 |
| depois | 13.575 | **25** | 543 |

Setenta e oito por cento daquele corpo era endereço. Trocar URL por host, blob
opaco por reticência e referência `cid:` por nada devolveu a passada de 25 minutos
para **55 segundos**.

A limpeza mora no parser de email, e não no chunker, de propósito: é um fato sobre
**email** — PDF e DOCX deste acervo não carregam token de rastreio — e mexer no
chunker afetaria todos os formatos, pedindo a medição de todos (invariante 4).

Três coisas que valem guardar:

1. **O sintoma não aponta a causa.** "A indexação está lenta" parecia hardware
   (15 W, CPU) e era conteúdo. O que resolveu foi medir chunk por documento **com
   o tokenizador real** — a medição sem ele, que é a dos testes unitários, dizia
   19 chunks onde havia 1.850.
2. **Orçamento de token protege contra truncagem e expõe a outro risco.** A
   decisão de 17/08 está certa e continua; o que faltava era alguém escrever que
   um formato pode chegar cheio de token sem conteúdo.
3. **Um documento com 343 chunks de lixo passa por documento indexado.** Nenhum
   contador reclama: `status=ok`, `n_chunks=343`. Só a distribuição acha — igual
   aos cinco defeitos de extração do grafo, em 20/08.

## As três decisões de desenho

**1. O envelope é bloco, sempre.** Assunto, participantes, data e nome dos anexos
viram um bloco com locator `cabeçalho`. Isso é o que faz um email sem corpo
textual terminar em `ok` e não em `vazio` — e a diferença não é cosmética: `vazio`
não gera chunk, e sem chunk o documento volta a ser invisível. Um dos 48 é
exatamente esse caso.

**2. A data sai do stream de propriedades MAPI**, varrendo os registros de 16
bytes à procura de `PR_CLIENT_SUBMIT_TIME`. Funcionou nos 48 de 48. Data
implausível é descartada em vez de convertida: `FILETIME` zerado daria 1601, e
data inventada é pior que data ausente — sobretudo para pergunta temporal, que é
o tipo da `g011`.

**3. Extensão que mente passa a ser despacho, não recusa.** `natureza.py` já
detectava o arquivo `.pdf` com conteúdo MIME desde a F1 e escrevia o motivo no
`detalhe`; era o melhor possível sem parser de email. Agora o portão tenta o
parser do **conteúdo** — e só para família sem ambiguidade. `ole` pode ser doc, xls
ou msg e `ooxml` pode ser docx, xlsx ou pptx: adivinhar nesses dois erraria
calado, que é o oposto do que o portão único existe para fazer.

## O critério de saída, e o que ele mede aqui

A saída da F4 pede duas coisas, e a primeira é literalmente sobre este bloco:
*"métricas de F2 não regridem com o corpus ampliado"*. Por isso a medição é em
três passadas, e não em duas:

| Passada | n | recall@1 | recall@5 | recall@10 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|
| **antes** — 1.601 documentos, 92.137 chunks | 45 | **0,667** | 0,885 | 0,930 | 0,787 | 0,793 |
| **depois, as mesmas 45** — 1.608 documentos, 93.073 chunks | 45 | **0,644** | 0,863 | 0,907 | 0,770 | 0,775 |
| **depois, dourado ampliado** | 48 | 0,635 | 0,872 | 0,913 | 0,774 | 0,782 |
| **só as três que eram fora de escopo** | 3 | 0,500 | **1,000** | 1,000 | 0,833 | 0,877 |

Configuração: `hibrido`, sem reranking, com glossário — a mesma que a F2 entrega e
a mesma da tabela do grafo, para que as três linhas sejam comparáveis.

**As três perguntas que mediam zero agora medem 1,000 em recall@3.** Todas as
fontes, incluindo as duas da `g033`, entram no top 3. O `0,500` em recall@1 é a
`g033` contribuindo com metade: multi-hop pontua por `todas` as fontes, e no
primeiro lugar só uma das duas está lá.

### A regressão existe, e são duas perguntas — com causas diferentes

A média cai 0,022 em recall@1 e 0,022 em recall@5 nas mesmas 45 perguntas. A regra
do projeto (porta 5 da F1) é **orçamento** de regressão, não regressão zero: no
máximo três perguntas caindo do 1º lugar, **cada uma inspecionada**. Inspecionadas:

| Pergunta | Antes | Depois | Quem passou na frente |
|---|---|---|---|
| `g045` "caderno de aceitação da POC da IBM" | 1º | 3º | um `.msg` da **reunião diária dessa mesma POC**, em 2º |
| `g037` "quem propôs AI Literacy para líderes" | ≤5º | 11º | três transcrições de reunião em 2º, 3º e 7º — **não são email** |

A segunda é a mais importante para ler o número certo. As três transcrições que
derrubaram a `g037` são de `Meetings/`, e entraram no índice **por acidente**: a
primeira tentativa de indexação rodou sem `--prefixo`, descobriu 1.013 documentos
novos que nunca foram indexados (1.010 deles em `Meetings/`), e foi cancelada
depois de processar quatro. A `g037` não regrediu por causa de email; regrediu
porque o corpus ganhou transcrição de reunião.

Sobra **uma** pergunta cuja queda é de email — a `g045`, e o documento que passou
na frente é a reunião diária da POC que a pergunta cita. Não é resposta errada: é
outro documento sobre o mesmo assunto. Uma queda do 1º lugar, dentro do orçamento
de três, contra três perguntas saindo do zero absoluto.

**O que isto diz sobre o critério de saída da fase.** "Métricas de F2 não regridem
com o corpus ampliado" é uma exigência que, lida ao pé da letra, nenhum corpus
ampliado cumpre: documento novo e relevante compete. Lida como orçamento — que é
como a F1 já a escreveu na porta 5 — está cumprida, e a inspeção mostra por quê.
O que **não** está cumprido é a leitura literal, e isso fica registrado aqui em
vez de arredondado.

### Um salto de grafo em cima do corpus ampliado

`eval.rodar --com-grafo` sobre as 48: recall@1 0,635, recall@10 0,913 — igual à
busca sozinha no subconjunto no escopo. No conjunto completo de 51, recall@10
**0,879 contra 0,869**, que é a `g048` de novo, exatamente como em 20/08. O grafo
ganhou 8 menções e 6 documentos com identificador vindos dos emails: pouco, e é
esperado — o que os emails carregam em quantidade é prosa de negociação, não
identificador estruturado.

## O que ficou de fora, com motivo

- **RTF comprimido** (`PR_RTF_COMPRESSED`). Exigiria descompressão LZFu, e nos 48
  arquivos reais não houve um único caso: todos trazem corpo em texto ou em HTML.
  Se aparecer, o documento não se perde — o envelope ainda produz bloco.
- **Anexo como documento próprio.** Motivo acima: é o laço do indexador, dono do
  outro setup. Fica registrado como candidato, e o nome do anexo já está indexado.
- **Corpo que é imagem** (assinatura escaneada, print de tela). É OCR, o outro
  pedaço que falta da F4.
- **`.doc` / `.xls` legado** (10 arquivos no registro). Também são container OLE, e
  o `olefile` que entrou aqui é metade do caminho — mas extrair texto de `.doc`
  binário não é tabela de nomes de stream, e sem número no dourado não há
  justificativa (invariante 4).

## Lições que valem para o resto da fase

**Documento sem chunk é invisível até para o ranqueador de nome.** Vale repetir
porque contraria a intuição: "o número do contrato está no nome do arquivo, então
o baseline acha" era falso — `paths_com_chunks()` é a fronteira, e ela é de
conteúdo, não de disco. Toda vez que um formato entra, o ganho não é "mais um
formato": é um conjunto de documentos saindo do zero absoluto.

**`sem_parser` como status repescável foi a decisão que fez este bloco custar
minutos.** Ela é de 13/08/2026 e está comentada em `STATUS_PARA_REPESCAR`:
"`sem_parser`: quase sempre custo zero, porque o despachante recusa pela extensão
antes de ler byte — e é o que faz um parser novo alcançar o que ficou para trás".
Sem ela, um parser novo exigiria reindexação completa (39 h) para alcançar 48
arquivos. É o mesmo raciocínio da passada separada do grafo, escrito dois meses
antes de fazer falta.

**Fixture binária escrita da especificação é o oposto de um mock.** `.msg` de
verdade é acervo corporativo e não entra no Git, então o teste constrói um
container CFB byte a byte (`tests/cfb.py`) e quem o lê é o `olefile` —
implementação independente. Se o arquivo estiver fora da especificação, o teste
falha; um mock teria passado verde contra qualquer coisa. Foi o que a retomada da
F3.5-D ensinou com `schtasks`, aplicado a formato de arquivo.

**Parser novo não repesca documento já indexado.** `STATUS_PARA_REPESCAR` resolve
"não havia parser"; não resolve "o parser mudou". Um `.msg` entrou no índice com
343 chunks antes da limpeza de corpo, e nenhuma passada o repesca — tamanho, mtime,
`model_id` e `chunker` continuam iguais, e `CHUNKER_VERSION` não cobre versão de
parser (está escrito assim no código desde 13/08). Hoje o conserto é esquecer o
documento à mão; a correção de verdade é uma coluna de versão de parser no
registro, que é schema de `store.py` e pede um bloco próprio.

**Achado colateral, e é grande: o corpus cresceu 63% sem ninguém saber.**
`iter_files` enumera 2.617 documentos e o registro tinha 1.601. A diferença são
**1.013 documentos que nunca foram indexados**, 1.010 deles em `Meetings/` e
`09. Meetings/` — transcrição de reunião. Indexar isso é decisão do usuário e tem
custo de horas; o que não pode é continuar invisível, porque **a métrica de toda a
F1 e F2 foi medida num corpus 39% menor que o disco**. Não muda nenhuma conclusão
já registrada (todas dizem qual corpus mediram, que é a regra 7 da colaboração),
mas é o próximo número a decidir.

**Motivo de exclusão precisa poder ser apagado.** `MOTIVOS_FORA_DE_ESCOPO` perdeu
a chave `email` junto com a entrega do parser. Motivo que sobrevive à própria
correção é desculpa disponível, e agora `carregar_perguntas` **recusa** um conjunto
dourado que ainda anote uma pergunta como fora de escopo por ser email — a
anotação velha não atravessa a fase em silêncio.
