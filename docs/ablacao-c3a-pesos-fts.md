# Pesos de coluna do bm25 — `C3.a` fechado em 24/08/2026

Primeiro pacote da onda 2. **A hipótese foi refutada e a varredura achou coisa
melhor:** a dupla contagem do nome do arquivo existe no mecanismo, mas não é ela
que produz o efeito de que era acusada — e o peso do ranqueador de nome na fusão,
escolhido em 13/08, está alto porque foi escolhido antes de existir na régua o
grupo que ele prejudica.

Evidência regenerável em `docs/metricas-c3a-pesos-fts.md` (fora do Git, pelo
padrão `docs/metricas-*.md`). Instrumento em `eval/varredura_fts.py`, grade e
regra declaradas lá **antes** de rodar, com a conclusão negativa junto.

```bash
py -m eval.varredura_fts --base padrao --glossario eval/glossario-teste.toml --out docs/metricas-c3a-pesos-fts.md
```

Condição: 59 perguntas no escopo, 2.156 documentos, 98.326 chunks, `e5-large`,
200 candidatos por ranqueador, **reranking desligado nos 18 braços**. Corpus da
medição: corporativo.

## A pergunta

O nome do arquivo pontua duas vezes. Dentro do bm25, pela coluna `caminho` do
FTS5 — que é o path com separadores virados em espaço, e pesa 1,0 porque é o
padrão do SQLite. E de novo na fusão, pelo `RanqueadorDeNome` com peso 0,5. Dois
votos do mesmo sinal, numa arquitetura cuja lição mais repetida é que o que soma é
**consenso de sinais de natureza diferente** (`ablacao-f2.md`).

O complemento descreveu esse mecanismo em `C3.a`. Em
[`dourado-cobertura.md`](dourado-cobertura.md) o notebook mediu o **efeito**:
desligar o ranqueador de nome sobe o MRR das perguntas de reunião 60% e piora o
resto. Os dois textos foram escritos sem saber um do outro, e o `ROADMAP.md`
tirou daí a ordem da onda 2: *se a dupla contagem explica o efeito, a correção é
mais barata e mais geral que um peso por tipo de fonte.*

Ela não explica.

## O que a grade mostrou

18 braços: `caminho` ∈ {0; 0,3; 1,0} × `trilha` ∈ {0,5; 1,0} × `nome` ∈ {0; 0,25;
0,5}. A coluna `texto` fica em 1,0 e isso não perde ponto — `bm25()` é linear nos
pesos e a fusão RRF ordena por posição, então escalar os três dá a mesma ordem.

| trilha | caminho | nome | recall@1 | recall@10 | MRR@10 | nDCG@5 | MRR reunião (n=11) | MRR escritório (n=46) | armadilhas |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0,5 | 0 | 0 | 0,449 | 0,873 | 0,593 | 0,618 | 0,464 | 0,617 | 5 de 6 |
| 1 | 0 | 0 | 0,466 | 0,890 | 0,606 | 0,625 | 0,464 | 0,633 | 5 de 6 |
| 0,5 | 0,3 | 0 | 0,534 | 0,890 | 0,658 | 0,676 | 0,464 | 0,700 | 5 de 6 |
| 1 | 0,3 | 0 | 0,534 | 0,890 | 0,657 | 0,675 | 0,464 | 0,699 | 5 de 6 |
| 1 | 1 | 0 | 0,534 | 0,898 | 0,668 | 0,693 | 0,459 | 0,714 | 5 de 6 |
| 0,5 | 1 | 0 | 0,534 | 0,898 | 0,668 | 0,692 | 0,455 | 0,715 | 5 de 6 |
| 0,5 | 0 | 0,25 | 0,525 | 0,881 | 0,661 | 0,680 | 0,414 | 0,717 | 5 de 6 |
| 1 | 0 | 0,25 | 0,525 | 0,881 | 0,661 | 0,680 | 0,414 | 0,717 | 5 de 6 |
| 0,5 | 0,3 | 0,25 | 0,534 | 0,898 | 0,677 | 0,694 | 0,414 | 0,737 | 5 de 6 |
| 1 | 0,3 | 0,25 | 0,534 | 0,898 | 0,677 | 0,694 | 0,414 | 0,737 | 5 de 6 |
| 0,5 | 1 | 0,25 | 0,551 | 0,898 | 0,684 | **0,700** | 0,409 | 0,747 | 5 de 6 |
| **1** | **1** | **0,25** | **0,551** | **0,898** | **0,684** | 0,696 | **0,409** | **0,747** | **5 de 6** ← |
| 0,5 | 0 | 0,5 | 0,483 | 0,907 | 0,650 | 0,668 | 0,299 | 0,730 | 5 de 6 |
| 1 | 0 | 0,5 | 0,483 | 0,907 | 0,647 | 0,666 | 0,299 | 0,726 | 5 de 6 |
| 0,5 | 0,3 | 0,5 | 0,517 | 0,907 | 0,670 | 0,685 | 0,293 | 0,757 | 5 de 6 |
| 1 | 0,3 | 0,5 | 0,517 | 0,907 | 0,671 | 0,692 | 0,293 | 0,758 | 5 de 6 |
| 0,5 | 1 | 0,5 | 0,534 | 0,907 | 0,672 | 0,676 | 0,287 | 0,761 | 5 de 6 |
| 1 | 1 | 0,5 | 0,551 | 0,907 | 0,680 | 0,682 | 0,287 | 0,761 | 5 de 6 · **referência** |

Email (n=2) e `misto` (n=0) ficam fora das colunas de grupo porque duas perguntas
não medem nada; as duas entram no agregado de 59.

## Quatro leituras, na ordem em que importam

### 1. A coluna `caminho` se paga, e é monotônica

Mais é melhor, em todos os níveis de `nome`. Zerá-la custa MRR agregado:

| nível de `nome` | caminho 0 | 0,3 | 1,0 | o que zerar custa |
|---|---:|---:|---:|---:|
| 0 | 0,606 | 0,657 | 0,668 | **−0,062** |
| 0,25 | 0,661 | 0,677 | 0,684 | −0,023 |
| 0,5 | 0,647 | 0,671 | 0,680 | −0,033 |

E em recall@1 o preço é maior ainda: 0,551 → 0,483 com `nome` em 0,5. **A
hipótese de que a coluna `caminho` seja ruído dobrado está refutada neste
acervo.** Ela fica em 1,0, e `C3.a` não muda nada no FTS.

### 2. Os dois votos não são o mesmo sinal — e é isso que mata a atribuição

O grupo de reunião é praticamente **cego** ao peso da coluna `caminho` e muito
sensível ao peso do ranqueador de nome:

| eixo | amplitude do MRR de reunião |
|---|---:|
| mexer `caminho` de 0 a 1,0 (em cada nível de `nome`) | 0,005 a 0,012 |
| mexer `nome` de 0 a 0,5 (com `caminho` em 1,0) | **0,172** |

**14 vezes mais sensível ao ranqueador da fusão que à coluna do bm25.** O
mecanismo que `C3.a` descreve é real — o nome está nos dois lugares — mas as duas
contagens não são intercambiáveis, e o efeito medido em `dourado-cobertura.md`
pertence quase inteiro ao ranqueador dedicado.

A explicação plausível, registrada como hipótese e não como achado: dentro do
bm25 o `caminho` só pontua quando os termos da consulta **aparecem** nele, e
disputa o mesmo score com o conteúdo; o `RanqueadorDeNome` produz uma ordenação
**completa** e independente por semelhança de nome, e transcrição tem nome feito
de assunto e data — casa com qualquer pergunta que repita a palavra do assunto.
Um vota quando tem o que dizer; o outro vota sempre.

### 3. O que paga é `nome = 0,25`, e ele domina o que está no ar

| | referência (`nome` 0,5) | `nome` 0,25 | Δ |
|---|---:|---:|---:|
| recall@1 | 0,551 | 0,551 | ±0 |
| recall@10 | 0,907 | 0,898 | −0,009 |
| MRR@10 | 0,680 | 0,684 | **+0,004** |
| nDCG@5 | 0,682 | 0,696 | **+0,013** |
| MRR reunião | 0,287 | 0,409 | **+0,122** (+43%) |
| MRR escritório | 0,761 | 0,747 | −0,014 |
| armadilhas | 5 de 6 | 5 de 6 | ±0 |

Um único recuo: recall@10 cai 0,009 — uma pergunta que estava entre a 6ª e a 10ª
posição sai do top-10. Contra isso, o grupo de reunião ganha 43% de MRR e a porta
3 não se move.

### 4. Por que 0,5 estava alto: foi escolhido antes de a régua ter o grupo

O peso 0,5 saiu da varredura de 13/08/2026 (`varredura-pesos-f1.md`), e naquele
conjunto dourado **não havia nenhuma pergunta de reunião** — as 11 entraram com a
`F4-M`, e os documentos de `Meetings/` só foram indexados depois (eram parte dos
1.010 que nunca tinham sido indexados). O ótimo de 13/08 estava certo para a régua
de 13/08.

É a lição desta ablação, e ela não é sobre nome de arquivo: **quando a régua
cresce, o ótimo anterior tem de ser rederivado, não herdado.** Nenhum alarme
dispara sozinho — a configuração continua medindo bem no agregado, porque o grupo
novo é minoria. Foi o recorte que a mostrou, do mesmo jeito que o recorte
cross-lingual mostrou a queda de 47% que a média escondia (`C4.5`).

## O teto de `F4-P`, medido antes de `F4-P` começar

A grade dá de graça o quanto ainda sobra para o peso por tipo de fonte. O melhor
que ele pode fazer é dar a cada grupo o seu ótimo — reunião com `nome` 0
(**0,459**) e escritório com `nome` 0,5 (**0,761**):

| configuração | MRR agregado |
|---|---:|
| referência, `nome` 0,5 | 0,680 |
| melhor global, `nome` 0,25 | 0,684 |
| **teto do peso por tipo de fonte** | **0,704** |

São **+0,020 sobre o melhor global** e +0,024 sobre a referência. Para comparar:
o reranking vale +0,011 de nDCG@5 e custa 6,9× no tempo de consulta. Então `F4-P`
vale a pena — e agora tem um teto contra o qual se conferir, em vez de descobrir
depois de implementado que o ganho era de 0,004.

Duas ressalvas que fazem parte do número:

- **É um teto de oráculo.** Ele supõe rotear pelo grupo da **fonte esperada**, que
  o recuperador não sabe. O que ele pode ponderar é o grupo do **documento
  candidato**, que é coisa diferente e mais fraca. O teto é otimista de
  propósito: serve para decidir se vale construir, não para prometer resultado.
- O global 0,25 já captura **71%** do ganho disponível no grupo de reunião, a
  custo zero e sem código novo no caminho de ranking.

## O que entrou no código

- `Store.buscar_lexical` aceita pesos de coluna: `bm25(chunks_fts, ?, ?, ?)`.
  `None` mantém o `bm25(chunks_fts)` **sem argumento**, que é o SQL que produziu
  todos os números de F1 a F4 — passar `(1,1,1)` daria o mesmo número por um
  caminho de código não medido, e essa troca já custou caro aqui.
- `config.Pesos` ganhou `fts_texto`, `fts_trilha` e `fts_caminho`, em 1,0. Peso de
  **consulta**: mudar não reindexa nada, e por isso não é classe cara. O painel os
  expõe sem uma linha nova — `CAMPOS_DE_PESO` deriva da dataclass, e a regra
  "salvar exige ter medido" passou a valer para eles de graça.
- `eval/fonte.py` — o recorte por tipo de fonte, em todo relatório do harness.
- `eval/memo.py` — memória na fronteira do `Store`, para 18 braços caberem em
  4 minutos em vez de horas.

**Os pesos ficam na configuração e não viram constante nova.** Este acervo tem
nome de arquivo informativo; o próximo pode ser `IMG_2034.pdf`, e aí a leitura 1
provavelmente se inverte. É o argumento de `R6.1`, e é por isso que o botão
existe mesmo com a hipótese refutada aqui.

## A validação que dá confiança no instrumento

O recorte por tipo de fonte é **derivado** do caminho da fonte, não anotado — e a
primeira versão errou. Depois de corrigida, o braço de referência e o braço
`nome = 0` reproduzem `dourado-cobertura.md` **exatamente**, em quatro números
medidos de forma independente:

| | aqui | `dourado-cobertura.md` |
|---|---:|---:|
| 59 no escopo, com nome — recall@1 / MRR / nDCG@5 | 0,551 / 0,680 / 0,682 | 0,551 / 0,680 / 0,682 |
| 59 no escopo, sem nome | 0,534 / 0,668 / 0,693 | 0,534 / 0,668 / 0,693 |
| 11 de reunião, com nome — MRR | 0,287 | 0,287 |
| 11 de reunião, sem nome — MRR | 0,459 | 0,459 |

Isso prova duas coisas de uma vez: a regra derivada reencontra a seleção feita à
mão, e o caminho de código novo — pesos de coluna, memo de varredura — não moveu
número nenhum.

## Os dois defeitos que a primeira passada expôs

Ficam registrados porque são de classe repetida, não de descuido.

**O recorte media 10 perguntas de reunião onde já se sabia que eram 11.** A regra
exigia a palavra no começo de um segmento de caminho, e **14 dos 36 segmentos de
pasta distintos** do dourado real começam com prefixo de ordenação — `09. `,
`10 - `, `260722_`. São 39%, e não é peculiaridade de um acervo: é como pasta de
trabalho é nomeada. O número menor era plausível, então passaria.

É exatamente a classe dos cinco defeitos do grafo da `F4`: *o mesmo nome escrito
de outra forma não liga, e cada grafia produz o seu próprio resultado plausível.*
O que pegou aqui foi o mesmo que pegou lá — conferir contra a distribuição real, e
contra um número já medido por outro caminho.

De brinde, o meu próprio teste escondia um segundo caso: `reuni[oõ]` **não casa
`Reunião`**, porque depois de `reuni` vem `ã`. O teste passava porque usava
`Reuniões`. Vocabulário de teste que cobre só a grafia que funciona não é teste.

**O desempate da regra era cego a um eixo.** Dois braços mediram idêntico com
`trilha` 0,5 e 1,0, e a escolha caiu na ordem da grade — sorte, não desenho, a
mesma frase que `eval/varredura.py` já registrou uma vez. O desempate passou a
preferir **não mexer** no peso que mediu plano. A emenda é posterior à corrida e
está declarada como tal na docstring de `REGRA`; ela só age entre braços já
empatados no que a regra otimiza, então não pode inverter conclusão — e nesta
corrida ela reduz o ganho relatado (nDCG@5 0,700 → 0,696) em vez de aumentá-lo.

## Decisão

1. **`fts_caminho` e `fts_trilha` ficam em 1,0.** `C3.a` não muda o FTS neste
   acervo. O botão fica, porque acervo de nome ruim é outra história e é `R6.1`
   que vai medi-la.
2. **`nome = 0,25` é recomendação medida, e não foi aplicada aqui.** Domina 0,5
   em tudo que a porta e o relatório olham, mas quem decide o peso do nome é
   `F4-P`, que começa agora e pode escolher peso por tipo de fonte. Mudar duas
   vezes em dois dias quebraria a comparabilidade da própria linha de base de
   `F4-P`. Para aplicar antes disso, na base corporativa e **não** em `[padrao]`:

   ```toml
   [base.pesos]
   nome = 0.25
   ```
3. **`F4-P` começa com teto declarado:** +0,020 de MRR agregado sobre o melhor
   global, oráculo e otimista. Se a implementação real ficar perto de 0,004, o
   peso global resolveu e o mecanismo não se paga.
