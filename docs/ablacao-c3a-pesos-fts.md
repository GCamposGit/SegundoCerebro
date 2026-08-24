# Pesos de coluna do bm25 — `C3.a` fechado em 24/08/2026

Primeiro pacote da onda 2, e o resultado não é um sim nem um não: **os dois
critérios vivos do projeto discordam sobre o mesmo peso.** Pela regra declarada,
nada passa e a hipótese está refutada. Pela régua que a onda 1 acabou de
construir, `fts_caminho = 0,3` é a coisa mais barata já medida a mexer o critério
cross-lingual — e é uma pergunta de doze, então é pista e não resultado.

Evidência regenerável em `docs/metricas-c3a-pesos-fts.md` (fora do Git, pelo
padrão `docs/metricas-*.md`). Instrumento em `eval/varredura_fts.py`, grade e
regra declaradas lá **antes** de rodar, com a conclusão negativa junto.

```bash
py -m eval.varredura_fts --base padrao --glossario eval/glossario-teste.toml --out docs/metricas-c3a-pesos-fts.md
```

Condição: 59 perguntas no escopo, 2.156 documentos, 98.326 chunks, `e5-large`,
200 candidatos por ranqueador, **reranking desligado nos 18 braços**. Corpus da
medição: corporativo. 18 braços em ~4 min, com memo na fronteira do `Store`.

## A pergunta

O nome do arquivo pontua duas vezes. Dentro do bm25, pela coluna `caminho` do
FTS5 — que é o path com separadores virados em espaço, e pesa 1,0 porque é o
padrão do SQLite. E de novo na fusão, pelo `RanqueadorDeNome` com peso 0,5. Dois
votos do mesmo sinal, numa arquitetura cuja lição mais repetida é que o que soma é
**consenso de sinais de natureza diferente** (`ablacao-f2.md`).

O complemento descreveu esse mecanismo em `C3.a`. Em
[`dourado-cobertura.md`](dourado-cobertura.md) o notebook mediu o **efeito**:
desligar o ranqueador de nome sobe o MRR das perguntas de reunião 60% e piora o
resto. O `ROADMAP.md` tirou daí a ordem da onda 2: *se a dupla contagem explica o
efeito, a correção é mais barata e mais geral que um peso por tipo de fonte.*

Ela não explica. E o que a grade achou no lugar é mais interessante.

## O veredito pela regra declarada: nada passa

> **2 braços mantêm a porta 3 e o MRR agregado, e todos pioram a fatia
> cross-lingual** (referência 0,496).

A guarda cross-lingual não estava na regra da primeira corrida — entrou depois,
declarada como emenda na docstring de `REGRA`, porque a onda 1 tinha acabado de
construir exatamente esse recorte e medir sem ele seria ter feito a régua e não
usado. Ela é o critério que eliminou os dois candidatos, e o motivo está na leitura 3.

## As quatro leituras

### 1. Em MRR e recall@1, a coluna `caminho` se paga — a hipótese está refutada

Mais é melhor, em todos os níveis de `nome`:

| nível de `nome` | MRR com caminho 0 | 0,3 | 1,0 | recall@1 com caminho 0 | 0,3 | 1,0 |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 0,606 | 0,657 | **0,668** | 0,466 | 0,534 | **0,534** |
| 0,25 | 0,661 | 0,677 | **0,684** | 0,525 | 0,534 | **0,551** |
| 0,5 | 0,647 | 0,671 | **0,680** | 0,483 | 0,517 | **0,551** |

Zerar a coluna custa até 0,062 de MRR e 6,8 pontos de recall@1. **A hipótese de
que a coluna `caminho` seja ruído dobrado está refutada neste acervo.**

### 2. Mas o que ela cobra é recall@5, e isso não estava na hipótese

O mesmo eixo, olhado um k adiante, inverte:

| `caminho` (com `nome` 0,5) | recall@1 | **recall@5** | recall@10 | MRR@10 | nDCG@5 |
|---:|---:|---:|---:|---:|---:|
| 1,0 (referência) | **0,551** | 0,797 | 0,907 | **0,680** | 0,682 |
| 0,3 | 0,517 | **0,847** | 0,907 | 0,671 | **0,692** |
| 0 | 0,483 | 0,831 | 0,907 | 0,647 | 0,668 |

`recall@10` é **idêntico** nos três: não se ganha nem se perde documento, só se
reordena dentro do top-10. O que a coluna `caminho` faz é empurrar o documento que
casa **por nome** para o primeiro lugar, e no caminho ela expulsa do top-5 três
documentos que casam por conteúdo. `caminho = 0,3` tem o **maior recall@5 da grade
inteira** — 0,847 contra 0,797, três perguntas.

É uma troca de produto, não um ótimo: um agente que lê o 1º resultado quer 1,0;
um que lê cinco e compõe `search` → `neighbors` quer 0,3. Como este servidor
existe para o segundo caso, a troca merece decisão explícita em `F4-P` — não é
para ser resolvida aqui.

### 3. O ranqueador de nome é uma ponte entre idiomas, e baixá-lo a derruba

Aqui está o que eliminou os candidatos, e é achado próprio:

| `nome` (com `caminho` 1,0) | MRR cross-lingual (n=12) |
|---:|---:|
| 0,5 (referência) | **0,496** |
| 0,25 | 0,475 |
| 0 | 0,461 |

Monotônico, e o mecanismo é claro: **o nome do arquivo é um sinal agnóstico a
idioma.** Identificador, código de contrato, data e nome próprio casam igual em
português e inglês, enquanto o bm25 é cego por construção — FTS5 não casa
`contrato` com `agreement`. Dos três votos da fusão, o nome é uma das duas únicas
pontes PT↔EN que existem, e a outra é o denso.

Isto **corrige** o que a primeira leitura desta varredura afirmou. `nome = 0,25`
sobe o MRR agregado (+0,004), o nDCG@5 (+0,013) e o MRR de reunião (+0,122), e por
isso foi descrito como dominante. Ele não domina: **derruba a ponte em 0,021**, e
a fatia mesma-língua, quatro vezes maior, esconde a conta na média. É a mesma
classe de erro que `C4.5` existe para fechar, cometida com o instrumento do `C4.5`
disponível e não usado.

### 4. E a ponte prefere `caminho` baixo — pelo motivo oposto

| `caminho` (com `nome` 0,5) | r@5 cross (n=12) | r@5 mesma (n=44) | razão `C4.5` |
|---:|---:|---:|---:|
| 1,0 (referência) | 0,625 | 0,852 | **0,73** |
| 0,3 | **0,708** | **0,898** | 0,79 |
| 0 | **0,708** | 0,875 | 0,81 |

**As duas fatias sobem**, então não é artefato de denominador — foi a dúvida que
motivou imprimir os dois recall@5 crus ao lado da razão. Uma pergunta cross-lingual
a mais entra no top-5 (+0,083 em n=12 é exatamente uma), e nenhuma mesma-língua
sai.

Isso importa além do pacote: [`fatia-cross-lingual.md`](fatia-cross-lingual.md)
deixou a lacuna cross-lingual aberta apontando para `F4-P`, e as rotas previstas
para ela eram trocar o modelo denso (`R3.1`) ou pôr um reranqueador multilíngue
(`R6.2`/`C4.2`) — as duas caras, as duas com rebuild ou com 6,9× de latência. Um
**peso de coluna de consulta** move o critério 6 pontos a custo zero.

**Uma pergunta de doze é pista, não resultado.** O lugar de confirmar é o perfil
bilíngue do `R9.1`, onde a fatia terá tamanho. Registrado como candidato, não como
decisão.

## O critério do `C4.5` é satisfazível piorando o denominador, e esta grade prova

O critério de aceite de `C4.5` é razão ≥ 0,80. Dois braços desta grade:

| braço | r@5 cross | r@5 mesma | razão | passa? |
|---|---:|---:|---:|:--:|
| trilha 1, caminho 0,3, nome 0,5 | 0,708 | **0,898** | 0,79 | **não** |
| trilha 0,5, caminho 0,3, nome 0,5 | 0,708 | 0,875 | **0,81** | **sim** |

Mesma ponte — recall@5 cross-lingual **idêntico**, 0,708. O segundo passa porque é
**pior** na fatia mesma-língua. O braço melhor nas duas fatias reprova; o pior numa
delas aprova.

Não é sofisma: é o que uma razão faz quando é usada como porta. `C4.5` acertou em
criar o recorte — sem ele nada disto seria visível —, e a **forma** do critério
precisa de um piso absoluto ao lado da razão, por exemplo *recall@5 cross-lingual
≥ X **e** razão ≥ 0,80*. Sem o piso, a maneira mais fácil de fechar a lacuna é
degradar o lado grande. Fica registrado aqui e apontado de `fatia-cross-lingual.md`;
quem muda o critério é `F4-P`, que é dono da decisão de ranking.

## O que `F4-P` herda

**A referência já é o ótimo do escritório.** Com `nome` 0,5 o MRR de escritório é
0,761, o maior da grade. Então **toda** a folga do peso por tipo de fonte está no
grupo de reunião: dar-lhe `nome = 0` (MRR 0,459 contra 0,287) põe o agregado em
**0,712**, ou **+0,032** sobre a referência.

Três ressalvas, e a terceira é nova:

- **É teto de oráculo.** Supõe rotear pelo grupo da **fonte esperada**, que o
  recuperador não sabe; ele só pode ponderar o grupo do **documento candidato**.
- **n = 11** no grupo de reunião. Sinal, não decisão.
- **3 das 11 perguntas de reunião são cross-lingual.** Medido no cruzamento
  grupo × fatia. Então baixar `nome` na reunião tira a ponte de 27% do próprio
  grupo que se quer melhorar, e o teto de +0,032 **não** desconta isso. `F4-P`
  tem de medir a interseção, não só os dois eixos.

Cruzamento completo, no escopo de 59:

| | mesma-língua | cross-lingual | não declarado |
|---|---:|---:|---:|
| escritório | 36 | 9 | 1 |
| reunião | 6 | 3 | 2 |
| email | 2 | 0 | 0 |

## Por que 0,5 não é o número errado, ao contrário do que eu disse antes

O peso 0,5 do nome saiu da varredura de 13/08/2026
([`varredura-pesos-f1.md`](varredura-pesos-f1.md)), num conjunto dourado **sem
nenhuma pergunta de reunião** — as 11 entraram com a `F4-M`, e `Meetings/` só foi
indexado depois. A primeira leitura desta varredura concluiu daí que o ótimo tinha
envelhecido e que 0,25 o substituía.

A metade certa dessa conclusão: **quando a régua cresce, o ótimo anterior tem de
ser rederivado, não herdado** — e nenhum alarme dispara sozinho, porque o grupo
novo é minoria e o agregado continua bonito. A metade errada: rederivar não deu
0,25. Deu 0,5 de novo, agora por dois motivos em vez de um — escritório **e**
ponte PT↔EN —, com a reunião como preço declarado. Ótimo reconfirmado por razão
diferente da original é resultado, não empate.

## O que entrou no código

- `Store.buscar_lexical` aceita pesos de coluna: `bm25(chunks_fts, ?, ?, ?)`.
  `None` mantém o `bm25(chunks_fts)` **sem argumento**, que é o SQL que produziu
  todos os números de F1 a F4 — passar `(1,1,1)` daria o mesmo número por um
  caminho de código não medido.
- `config.Pesos` ganhou `fts_texto`, `fts_trilha` e `fts_caminho`, em 1,0. Peso de
  **consulta**: mudar não reindexa nada, e por isso não é classe cara. O painel os
  expõe sem uma linha nova — `CAMPOS_DE_PESO` deriva da dataclass, e a regra
  "salvar exige ter medido" passou a valer para eles de graça.
- `eval/fonte.py` — o recorte por tipo de fonte, em todo relatório do harness.
- `eval/memo.py` — memória na fronteira do `Store`, 18 braços em 4 min.

**Os pesos ficam na configuração e não viram constante nova.** Este acervo tem
nome de arquivo informativo; o próximo pode ser `IMG_2034.pdf`, e aí a leitura 1
provavelmente se inverte. É o argumento de `R6.1`, e é por isso que o botão existe
mesmo com a hipótese refutada aqui.

## A validação que dá confiança no instrumento

O recorte por tipo de fonte é **derivado** do caminho da fonte, não anotado. Depois
de corrigido, o braço de referência e o braço `nome = 0` reproduzem
`dourado-cobertura.md` **exatamente**, em quatro números independentes:

| | aqui | `dourado-cobertura.md` |
|---|---:|---:|
| 59 no escopo, com nome — recall@1 / MRR / nDCG@5 | 0,551 / 0,680 / 0,682 | 0,551 / 0,680 / 0,682 |
| 59 no escopo, sem nome | 0,534 / 0,668 / 0,693 | 0,534 / 0,668 / 0,693 |
| 11 de reunião, com nome — MRR | 0,287 | 0,287 |
| 11 de reunião, sem nome — MRR | 0,459 | 0,459 |

A regra derivada reencontra a seleção feita à mão, e o caminho de código novo —
pesos de coluna, memo de varredura — não moveu número nenhum.

## Os defeitos que as corridas expuseram

Quatro, todos registrados porque são de classe repetida.

**O recorte media 10 perguntas de reunião onde já se sabia que eram 11.** A regra
exigia a palavra no começo de um segmento de caminho, e **14 dos 36 segmentos de
pasta distintos** do dourado começam com prefixo de ordenação — `09. `, `10 - `,
`260722_`. São 39%, e não é peculiaridade de um acervo: é como pasta de trabalho é
nomeada. O número menor era plausível, então passaria. Exatamente a classe dos
cinco defeitos do grafo da `F4`: *o mesmo nome escrito de outra forma não liga.*

**Meu próprio teste escondia um segundo caso:** `reuni[oõ]` **não casa `Reunião`**,
porque depois de `reuni` vem `ã`. O teste passava porque usava `Reuniões`.
Vocabulário de teste que cobre só a grafia que funciona não é teste.

**O desempate da regra era cego a um eixo.** Dois braços mediram idêntico com
`trilha` 0,5 e 1,0, e a escolha caiu na ordem da grade — sorte, não desenho, a
mesma frase que `eval/varredura.py` já registrou uma vez. Passou a preferir **não
mexer** no peso que mediu plano.

**O veredito passou a dar o motivo errado quando a guarda entrou.** A mensagem
citava dois critérios de forma fixa; com o terceiro, braços que mantinham porta e
agregado e perdiam a ponte eram relatados como se tivessem quebrado a porta.
Relatório que dá o motivo errado é pior que relatório sem motivo — a peneira agora
é em etapas e nomeia o critério que eliminou.

## Decisão

1. **Nada muda na configuração.** `fts_texto`, `fts_trilha` e `fts_caminho` ficam
   em 1,0, e `nome` fica em 0,5. Pela regra declarada nenhum braço passa, e a
   recomendação de `nome = 0,25` da primeira leitura está **retirada**: ela derruba
   a ponte PT↔EN.
2. **`fts_caminho = 0,3` fica registrado como candidato**, não aplicado, com o
   preço à vista: −0,034 de recall@1 e −0,009 de MRR contra +0,050 de recall@5,
   +0,010 de nDCG@5 e a razão `C4.5` de 0,73 para 0,79. Quem decide é `F4-P`, e a
   decisão é de produto: o primeiro resultado ou os cinco primeiros.
3. **O critério de aceite de `C4.5` precisa de um piso absoluto** ao lado da razão.
   Esta grade contém o contraexemplo.
4. **`F4-P` começa com teto de +0,032**, oráculo, e com a interseção medida: 3 das
   11 perguntas de reunião são cross-lingual, e o teto não desconta isso.
