# Ablação da F1 — medição sobre o índice reconstruído

13/08/2026. Índice refeito com `e5-large` depois dos três defeitos encadeados de
`docs/truncagem-silenciosa.md`: 434 documentos, **11.208 chunks**, 11.208 vetores,
zero chunks acima do orçamento de 488 tokens, **100% do texto virando vetor**
contra 19,3% antes.

Esta medição **substitui** a de 12/08. Aquela foi tirada sobre um índice em que o
encoder lia um terço de cada chunk, e a coluna densa dela não vale.

## O critério, inalterado

Mesmo universo (`--prefixo` recorta o baseline para a mesma subárvore) e mesmas
perguntas (**45 no escopo**, com 6 excluídas por motivo declarado: `.msg`, PDF
digitalizado, e um email com extensão `.pdf`). Detalhe em `estado-f1.md`.

## A tabela

45 perguntas no escopo, 434 documentos, 11.208 chunks, 200 candidatos por ranking.

| Recuperador | recall@1 | recall@10 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| baseline por nome de arquivo | 0,533 | 0,844 | 0,670 | 0,705 |
| bm25 puro | 0,500 | 0,767 | 0,598 | 0,633 |
| denso puro | 0,522 | 0,885 | 0,678 | 0,726 |
| denso + bm25, ambos com peso 1 | 0,589 | 0,852 | 0,712 | 0,737 |
| denso + nome, sem bm25 | 0,589 | 0,907 | 0,755 | 0,779 |
| **escolhida — `denso 1, bm25 0,25, nome 0,5`** | **0,622** | **0,919** | **0,759** | **0,783** |

A configuração escolhida saiu da varredura de **37 pontos** com os três pesos
variando (`docs/varredura-pesos-f1.md`), sob a regra declarada antes de rodar.
A grade anterior fixava o lexical em 1,0 e por isso não enxergava metade do
espaço; a correção está descrita lá.

E os subconjuntos que dizem se a fase entregou o que prometeu:

| Recuperador | armadilhas | multi-hop | perguntas do usuário (MRR) |
|---|---:|---:|---:|
| baseline por nome de arquivo | 3 de 6 | 3 de 5 | 0,557 |
| bm25 puro | **5 de 6** | 1 de 5 | 0,333 |
| denso puro | **5 de 6** | 1 de 5 | 0,583 |
| `denso 1, bm25 0, nome 1` | 3 de 6 | **4 de 5** | 0,672 |
| `denso 1, bm25 0, nome 0,25` | **5 de 6** | 2 de 5 | 0,694 |
| **escolhida — `denso 1, bm25 0,25, nome 0,5`** | 4 de 6 | 2 de 5 | **0,623** |

A contagem por caso vem da varredura, que a calcula com o modo certo
(`recall@10 == 1`, e multi-hop exige todas as fontes). A média de recall que
aparece nos relatórios por braço é proporcional e não coincide com a contagem.

## O que mudou em relação a 12/08

**A F1 passou a bater o baseline, e com folga.** Recall@1 vai de 0,533 para
**0,644** (+11,1 pontos) e MRR de 0,670 para **0,742** (+7,2). Na medição
anterior o sistema completo *empatava* com o baseline (0,522 contra 0,533). A
diferença não é ajuste de peso: é o índice ter passado a conter o texto inteiro.

**Duas conclusões de ontem estão retratadas.**

*"O peso ótimo do denso é zero."* **Falso.** Era artefato do defeito. Na grade
nova o MRR sobe monotonicamente com o peso do denso em todos os níveis de peso de
nome, e as quatro linhas com `denso = 0` ocupam o fundo da tabela (MRR 0,598 a
0,684) enquanto as com `denso = 1` ocupam o topo (0,712 a 0,742). Um ranqueador
que lia 19% do acervo perder de um que lia 100% era evidência sobre o defeito,
nunca sobre embeddings.

*"O conflito entre nome e conteúdo é de forma, não de intensidade — nenhum peso
resolve."* **Falso como afirmado.** Ontem o único ponto com 5 de 6 armadilhas
tinha MRR 0,590, abaixo do próprio baseline; era de fato irreconciliável. Hoje o
ponto `denso = 0,25, nome = 0,25` faz **5 de 6 armadilhas com MRR 0,707**, acima
do baseline. A tensão continua existindo — o peso do nome ainda troca armadilha
por média — mas deixou de ser um beco sem saída.

**Duas conclusões sobreviveram.**

*O bm25 puro ganha nas armadilhas por 5 a 3.* Confirmado, mesmo número. E agora
o **denso puro também faz 5 de 6**, o que fortalece a leitura: o que resolve
armadilha é ler o conteúdo, qualquer que seja o sinal.

*O denso lidera no subconjunto sem viés de construção.* Confirmado e ampliado: o
denso puro mede 0,583 de MRR nas perguntas escritas de memória contra 0,333 do
bm25 puro, e `denso + nome` chega a **0,722**.

**O peso do nome caiu de 1,0 para 0,5.** Parte do que o nome carregava era
compensação por um denso quebrado. Com o denso funcionando, o pico de MRR sai de
`nome = 1,0` para `nome = 0,5`.

## O que a tabela mostra e a varredura não podia mostrar

A grade fixa o lexical em 1,0, então **`denso + nome` sem bm25 estava fora dela** —
e é o ponto de maior MRR (0,755 contra 0,742), maior recall@10 (0,907), melhor
multi-hop (**4 de 5**) e melhor subconjunto do usuário (0,722).

Ele não foi escolhido, e a regra declarada é o motivo: faz **3 de 6 armadilhas**,
abaixo do mínimo de 4. Ou seja, a regra teria rejeitado esse ponto mesmo se a
grade o incluísse — a escolha se sustenta. Mas o ponto cego da grade fica
registrado, e o desenho da próxima varredura tem que variar os três pesos.

Isso levanta a hipótese seguinte, para medir e não para supor: **o bm25 pode
estar atrapalhando os subconjuntos honestos**. Ele custa 0,189 de MRR nas
perguntas do usuário (0,722 → 0,533) e 4 para 3 no multi-hop, comprando em troca
uma armadilha. É exatamente o tipo de troca que a média esconde.

## A tensão que a regra criou, e que eu não vou resolver sozinho

A regra declarada exige **≥ 4 de 6 armadilhas** para um ponto ser elegível, e com
isso rejeitou `denso = 1, bm25 = 0, nome = 1` — que tem o **maior MRR da grade**
(0,769), o melhor multi-hop (4 de 5) e recall@1 0,633, mas faz 3 de 6 armadilhas.

O problema é que o limiar de 4 foi calibrado ontem, sobre as medições
defeituosas, com o raciocínio "o baseline faz 3 e o bm25 puro faz 5, então 4
corta quem compra média entregando armadilha". Aquele raciocínio se apoiava em
números que caíram.

Ele também não é a porta: o ROADMAP pede **5 de 6**. Ou seja, o filtro é um valor
intermediário que eu escolhi, e ele está decidindo a configuração. Três leituras
possíveis, e a escolha é do dono do projeto:

1. **Manter a regra como está.** É o que está feito. Vantagem: a regra foi
   declarada antes e honrá-la é o que impede escolha post-hoc.
2. **Subir o filtro para 5**, alinhando com a porta. Escolheria
   `denso = 1, bm25 = 0, nome = 0,25` — 5 de 6 armadilhas, MRR 0,744, e o melhor
   recall@10 da grade inteira (0,941).
3. **Trocar o critério de elegibilidade pelas portas de fato**, exigindo
   simultaneamente armadilhas e multi-hop. Nenhum ponto da grade satisfaz os
   dois, o que é informação e não impasse: diria que falta algo além de peso.

Qualquer mudança agora é post-hoc e precisa ser declarada como tal.

## As portas na condição C — medidas em 16/08/2026

O corpus completo foi indexado: **1.601 documentos, 92.125 chunks, 92.125
vetores**, com a reconciliação removendo 154 documentos que a limpeza de pastas
do usuário tinha deixado como fantasma. Esta é a condição em que as portas são
definidas, e portanto o primeiro veredito legítimo.

Baseline por nome de arquivo, mesmo universo, 45 perguntas no escopo:
recall@1 0,467 · recall@10 0,800 · MRR@10 0,592.

| Porta | limiar | medido | |
|---|---:|---:|:--:|
| 1. recall@1 ≥ baseline + 0,10 | 0,567 | **0,600** | ✅ |
| 2. MRR@10 ≥ baseline + 0,08 | 0,672 | **0,736** | ✅ |
| 3. armadilhas: 5 de 6 no top-10 | 5 | 4 | ❌ |
| 4. multi-hop: 3 de 5 com todas as fontes | 3 | 1 | ❌ |
| 5. orçamento de regressão | 0 críticas, ≤ 3 quedas | **0 e 0** | ✅ |

**Três de cinco. A F1 não fecha.**

O ganho sobre o baseline é grande e consistente — +13,3 pontos de recall@1,
+14,4 de MRR, e as seis perguntas escritas de memória passam a ser **todas**
encontradas no top-10 (recall@10 = 1,000 contra 0,833). A porta 5 passa limpa:
12 perguntas melhoraram, 2 pioraram por uma posição cada, nenhuma armadilha
regrediu.

**O que falta é específico e nomeado.**

*Porta 3* — faltam `g010` (qual a versão vigente da Política de IA) e `g036`
(qual empresa propôs implantação de IA). A `g010` é o caso de família de versão
puro: o índice tem `_v1`, `_v3`, `_v6`, `_v7` e o vigente sem sufixo, e nada no
ranqueamento sabe qual é o mais novo. É trabalho previsto da F2.

*Porta 4* — e aqui há uma distinção que a média esconde. O **MRR multi-hop saltou
de 0,117 para 0,600**, o maior ganho relativo de toda a medição: o sistema acha
*uma* das fontes muito bem. O que ele não faz é trazer **todas** ao mesmo tempo,
e a porta é por caso. Isso não se resolve com peso — é o argumento estrutural a
favor do `neighbors` sobre grafo derivado (F4), que a `escala-f0.md` já tinha
antecipado.

## Onde isso deixava as portas na condição B

As cinco portas são medidas **na condição C** (corpus completo, 3.154
documentos), e o que existe aqui é a condição B (subárvore de dev). Portanto
**nenhuma porta está declarada cumprida**. Usando os limiares equivalentes sobre
o baseline da condição B:

| Porta | limiar em B | medido | |
|---|---:|---:|:--:|
| recall@1 ≥ baseline + 0,10 | 0,633 | 0,622 | ✳ falta 0,011 |
| MRR@10 ≥ baseline + 0,08 | 0,750 | **0,759** | ✅ |
| armadilhas: 5 de 6 | 5 | 4 | ❌ |
| multi-hop: 3 de 5 | 3 | 2 | ❌ |
| **orçamento de regressão** | 0 críticas, ≤ 3 quedas | **0 e 0** | ✅ |

A porta 5 deixou de ser inavaliável: `eval/comparar.py` compara pergunta a
pergunta e o veredito está em `docs/regressao-f1.md`. Contra o baseline, **12
perguntas melhoraram e 2 pioraram**, as duas por uma única posição (7→8 e 2→3).
Nenhuma armadilha regrediu, nenhuma pergunta caiu do primeiro lugar, nenhuma
sumiu do ranking. A `g007` saiu de *não encontrada em nenhuma posição* para a
posição 2.

**As perguntas do usuário deixaram de discordar da média.** Na medição anterior
elas pioravam contra o baseline (0,533 contra 0,557); com o peso do bm25 em 0,25
elas sobem para **0,623**, e as seis passam a ser encontradas dentro do top-10
(recall@10 = 1,000). Era o sinal de alerta da rodada passada, e ele se resolveu
ao reduzir justamente o ranqueador que o estava causando.

**O multi-hop continua sendo o ponto fraco**, e piorou na contagem por caso: 2 de
5 contra 3 do baseline. Com n = 5 é uma pergunta, mas é a mesma direção que a
`escala-f0.md` já tinha apontado como a mais frágil. Vale notar que
`denso = 1, bm25 = 0, nome = 1` faz 4 de 5 — o multi-hop parece preferir o
extremo sem bm25.

## Arquivos

| Braço | Relatório |
|---|---|
| baseline, mesmo universo | `metricas-baseline-dev.md` |
| baseline, raiz completa | `metricas-baseline-raiz.md` |
| configuração escolhida | `metricas-f1.md` |
| bm25 puro | `ablacao-bm25-sem-nome.md` |
| denso puro | `ablacao-denso-sem-nome.md` |
| denso + bm25, sem nome | `ablacao-hibrido-sem-nome.md` |
| bm25 + nome | `ablacao-bm25-com-nome.md` |
| denso + nome | `ablacao-denso-com-nome.md` |
| grade de pesos | `varredura-pesos-f1.md` |

```bash
py -m eval.rodar --retriever baseline --prefixo "01. Inteligência Artificial" --out docs/metricas-baseline-dev.md
py -m eval.rodar --retriever hibrido --out docs/metricas-f1.md
py -m eval.varredura --out docs/varredura-pesos-f1.md
```
