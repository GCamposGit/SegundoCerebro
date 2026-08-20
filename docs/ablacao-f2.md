# Ablação da F2 — a leitura

> A tabela de evidência está em
> [`ablacao-f2-tabela.md`](ablacao-f2-tabela.md), gerada por
> `py -m eval.ablacao_f2`. Este arquivo é escrito à mão e é onde mora a
> conclusão — separados de propósito, para uma regeneração não apagar em
> silêncio o raciocínio.
>
> Medido em 18/08/2026 na condição C: 1.601 documentos, 92.137 chunks, 45
> perguntas no escopo, `e5-large`, 200 candidatos por ranking. Todos os braços na
> mesma passada, com o encoder aberto uma única vez.

## A escada

| Recuperador | recall@1 | MRR@10 | nDCG@5 | armadilhas | usuário MRR | s/consulta |
|---|---:|---:|---:|---:|---:|---:|
| _baseline por nome (F0)_ | _0,467_ | _0,592_ | — | _3 de 6_ | _0,557_ | — |
| bm25 puro | 0,511 | 0,611 | 0,628 | 4 de 6 | 0,333 | 0,14 |
| denso puro | 0,522 | 0,670 | 0,700 | 5 de 6 | 0,556 | 0,78 |
| denso + bm25 | 0,600 | 0,712 | 0,732 | 5 de 6 | 0,413 | 0,89 |
| bm25 + nome | 0,533 | 0,638 | 0,647 | 3 de 6 | 0,375 | 0,19 |
| denso + nome | 0,600 | 0,750 | 0,769 | 3 de 6 | 0,667 | 0,70 |
| os três, sem famílias | 0,600 | 0,736 | 0,740 | 4 de 6 | 0,571 | 0,86 |
| **os três + famílias — o padrão** | **0,644** | **0,762** | **0,760** | **5 de 6** | 0,571 | **0,87** |
| denso + nome + famílias | 0,644 | 0,773 | **0,789** | 3 de 6 | 0,667 | 0,72 |
| os três + famílias + rerank 0,25 | **0,678** | **0,785** | 0,771 | 5 de 6 | 0,570 | 6,02 |
| **+ glossário de siglas** (`ablacao-glossario.md`) | **0,667** | **0,787** | **0,793** | 5 de 6 | **0,724** | **0,87** |

A última linha é o padrão mais o glossário, sem reranking, e está aqui porque é a
configuração que a fase entrega. A medição detalhada dela é `ablacao-glossario.md`,
que **não está no repositório**: cita nome de arquivo do acervo corporativo e é
gitignorado, como os relatórios por pergunta. O que sobreviveu aqui é o agregado,
e o achado que decide o produto está resumido abaixo — o formato do dicionário,
com empresa fictícia, é [`eval/glossario.example.toml`](../eval/glossario.example.toml).

## O que o critério de saída pedia

`denso-só vs. híbrido vs. híbrido+rerank`, com nDCG@5 por configuração:

| | nDCG@5 | s/consulta |
|---|---:|---:|
| denso-só | 0,700 | 0,78 |
| híbrido (os três + famílias) | 0,760 | 0,87 |
| híbrido + rerank | 0,771 | 6,02 |

Monotônico nos três. **A saída da F2 está cumprida**, e o resto da escada existe
porque só o vencedor não distingue uma superfície plana de uma com pico.

O harness não emitia nDCG@5 — só @10 — e passou a emitir os dois. Manter o @10 é
o que preserva a comparabilidade com as tabelas da F0 e da F1; ter o @5 é o que
cumpre o critério sem uma nota de rodapé explicando o desvio.

## Onde o bm25 se paga, e é só ali

O ponto mais informativo da tabela é uma célula que a primeira rodada não tinha.
`denso + nome + famílias` — os três sinais menos o bm25 — mede o **maior nDCG@5 da
tabela inteira, 0,789**, acima até do reranking, com MRR 0,773 contra 0,762 do
padrão, o melhor subconjunto do usuário (0,667) e o melhor multi-hop (2 de 5). E
custa 0,72 s contra 6,02 s.

Por qualquer média, ele ganha. E ele faz **3 de 6 armadilhas**, contra 5 do padrão.

Isso localiza com precisão o que a `ablacao-f1.md` só tinha levantado como
hipótese — "o bm25 pode estar atrapalhando os subconjuntos honestos". Ele está: custa
0,011 de MRR e 0,020 de nDCG@5 no agregado, e 0,096 no subconjunto do usuário.
O que ele compra são **duas armadilhas**, e a porta 3 é por caso, não por média.

Também mata uma explicação alternativa que parecia razoável: não era o caso de as
famílias de versão terem passado a resolver as armadilhas e tornado o bm25
redundante. Com famílias ligadas e sem bm25, as armadilhas caem de 5 para 3. As
famílias e o bm25 resolvem **casos diferentes** e não se substituem.

**A configuração padrão não muda.** A regra de elegibilidade foi declarada antes
(≥ 4 de 6 armadilhas, `eval/varredura.py`) e a porta do ROADMAP pede 5 — e trocar
o padrão agora por um ponto que faz 3 seria escolha post-hoc contra a regra que já
decidiu duas vezes nesta fase. Fica registrado como o candidato a reabrir se a
porta 3 for renegociada.

## Genérico não paga. Específico paga tudo.

O achado da fase que mais mexe no produto, e ele não precisa de nenhum dado real
para ser reproduzido — só da forma do experimento.

O dicionário de teste nasceu dividido em dois grupos e cada um foi medido isolado:
**genérico** (mês abreviado no nome de arquivo — `Dec-2025` contra "dezembro";
serviria a qualquer acervo de qualquer pessoa) e **específico** (as siglas
internas de uma empresa só).

| Dicionário | recall@1 | recall@5 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|
| nenhum | 0,644 | 0,841 | 0,762 | 0,760 |
| **só o genérico** | 0,644 | 0,841 | 0,762 | 0,760 |
| **só o específico** | **0,667** | **0,885** | **0,787** | **0,793** |
| os dois juntos | 0,667 | 0,885 | 0,787 | 0,793 |

**O grupo genérico não move nada — dígito por dígito igual a não ter glossário.**
O específico produz o ganho inteiro, e somar o genérico não acrescenta.

A hipótese era o contrário, e vale registrar por que era plausível: `Dec-2025` de
fato não casa com "dezembro" em ranqueador léxico nenhum. Só que a pergunta que
sofria disso já era encontrada pelos outros sinais. **Achar o descasamento não é
achar o gargalo.**

Duas consequências de desenho:

1. **Dicionário embutido no produto seria peso morto.** A metade que serviria a
   todos foi medida em zero.
2. **O mecanismo de o usuário construir o dele não é acessório da feature — é a
   feature.** Um glossário que exija editar TOML entrega zero justamente para o
   usuário não-técnico que tem as siglas que importam. Daí `/api/glossario`, a
   tela "Siglas da sua casa" e o arquivo por base.

O formato está em [`eval/glossario.example.toml`](../eval/glossario.example.toml),
com a empresa fictícia do corpus sintético — inclusive o grupo genérico, mantido
lá como o resultado negativo que ele é.

## As três lições que se repetiram

**Consenso de ranqueadores independentes vence juiz isolado.** Terceira vez: com
o bm25 em 13/08, com o cross-encoder em 16/08, e aqui de novo — nenhum ranqueador
sozinho chega perto da fusão. O melhor isolado é o denso com nDCG@5 0,700; qualquer
par que inclua o denso passa de 0,730. O pior par é `bm25 + nome` (0,647), e ele é
o par de dois sinais que leem **forma de superfície** — a lição inversa, e a mais
útil: o que soma é sinal de natureza diferente, não sinal a mais.

**Metadado antes de modelo.** As famílias de versão custam zero por consulta e
valem +0,044 de recall@1 e a porta 3. O reranking custa 6,9× e vale +0,011 de
nDCG@5. O glossário custa zero e vale +0,033 — o triplo do reranking nessa métrica.
Dois dos três maiores ganhos da fase não vieram de modelo nenhum.

**O que a média esconde é sempre o subconjunto que importa.** Três vezes nesta
tabela: o bm25 comprando armadilha e vendendo o usuário; o `denso + nome` ganhando
em tudo menos na porta; e o glossário, cujo ganho médio de 0,024 de MRR é 0,153 nas
seis perguntas escritas de memória.

## Sobre a coluna de tempo, e um número que quase saiu errado

A coluna corrobora uma medição independente, e isso vale mais que a coluna. O
reranking mede **6,02 s contra 0,87 s do padrão — 6,9×**, e o valor registrado em
`config.Busca.rerank`, tirado em 16/08 por outro caminho e sem nada concorrendo,
é **6,8×**. Duas medições independentes com metodologias diferentes chegando ao
mesmo fator é o que autoriza tratar o número como propriedade do sistema e não
como circunstância daquela máquina.

O resto da coluna é coerente e diz o esperado: o bm25 quase não custa (0,14 s),
o denso domina o custo de qualquer braço que o inclua (0,70 a 0,89 s), e as
famílias de versão custam **nada mensurável** — 0,86 s sem elas contra 0,87 s com
elas, enquanto entregam +0,044 de recall@1.

**A primeira versão desta coluna estava errada em 13%**, e o modo como o erro
apareceu é a parte que vale guardar. O tempo era dividido pelas 45 perguntas no
escopo, mas o laço roda as 51 do conjunto — o divisor tem que ser o que foi
executado, não o que entra na média. Com isso o reranking aparecia como 11,42 s e
8,9×, contra os 6,8× já registrados.

O que denunciou não foi a discrepância: foi que, ao regerar a tabela depois da
correção, os nove tempos saíram **idênticos aos anteriores até o centésimo**.
Medição de tempo que se repete exata não é medição — e de fato a regeneração
havia falhado com um `NameError`, invisível porque a saída passava por um `grep`
que só deixava passar linhas de sucesso. **Filtro em cima de saída de comando
esconde a falha e deixa o arquivo velho no lugar parecendo novo.**
