# Rigor estatístico mínimo — o pacote `E5`, 24/08/2026

O harness comparava médias secas. Este pacote põe um intervalo de confiança ao
lado de cada número e uma regra de adoção escrita ao lado de cada comparação.

Instrumento em [`eval/estatistica.py`](../eval/estatistica.py); as duas tabelas
novas saem de `eval.rodar` (ruído por recorte) e de `eval.comparar` (Δ pareado).

```bash
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank --glossario eval/glossario-teste.toml --out docs/metricas-e5.md
py -m eval.comparar --base padrao --antes hibrido --depois hibrido --rerank-depois --glossario eval/glossario-teste.toml --out docs/metricas-e5-rerank-reanalise.md
```

## Por que agora, e não na F0

Porque só agora o projeto começou a decidir sobre fatias pequenas. Enquanto a
régua era "recall@1 do conjunto inteiro" com n=45, a média secas bastava para
distinguir 0,533 de 0,678. A onda 2 decide outra coisa: a `F4-P` tem alvo
declarado no grupo **reunião**, que tem **11 perguntas**, e na fatia
**cross-lingual**, que tem **12**. Nessa escala uma pergunta vale 9 e 8 pontos —
e um "ganho de 9 pontos" numa tabela de médias é indistinguível de sorte.

Não é hipótese: `C3.a` já foi decidido no fio disso. A primeira leitura daquela
varredura recomendava `nome = 0,25` por +0,004 no agregado, e o que a retirou foi
uma fatia de 12 perguntas com efeito de 0,021. As duas grandezas são da mesma
ordem que o ruído, e nenhuma das duas tinha intervalo.

## O método, e as três escolhas que ele faz

**Bootstrap de percentil, 1.000 reamostragens.** É o instrumento padrão da
literatura de IR (Smucker, Allan & Carterette, CIKM 2007) e não assume forma
nenhuma para a distribuição — o que importa porque a métrica por pergunta é 0/1
em recall@1 e discreta em MRR (1, ½, ⅓, …). Um intervalo `média ± 1,96 σ/√n`
seria simétrico onde a amostra não é.

**Pareado, e isso não é detalhe.** As duas configurações respondem **as mesmas
perguntas sobre o mesmo corpus**: uma pergunta difícil é difícil dos dois lados.
Reamostrar os braços de forma independente joga essa correlação fora e infla o
intervalo — é potência descartada de graça. O bootstrap pareado sorteia
*perguntas* e usa os mesmos índices nos dois braços.

E há uma identidade que torna o pareamento **estrutural em vez de convenção**:
como a média é linear,

```
media(depois[idx]) - media(antes[idx])  ==  media((depois - antes)[idx])
```

Então reamostrar o vetor de **diferenças por pergunta** é exatamente o mesmo
cálculo. É o que `ic_do_delta` faz, e a vantagem é que não existem dois vetores
para alguém dessincronizar depois.

**Semente fixa.** O intervalo entra em documento versionado. Um IC que mudasse a
cada regeneração faria o diff do relatório mentir sobre o que mudou, e a tabela
regenerável é metade do valor de `ablacao-f2-tabela.md`.

## A regra de adoção

> Uma mudança **ganha** na fatia que ela mira se o IC95 do Δ pareado **exclui
> zero**. Empate estatístico resolve **por simplicidade** — não adotar.

Duas consequências que valem escrever, porque as duas já teriam mudado decisões
passadas:

- **A fatia-alvo é declarada antes de olhar a tabela.** Com oito recortes na
  tabela, escolher depois qual deles justifica a mudança é escolher a conclusão.
  O `C3.a` fez isso certo por acidente de cronologia — a fatia cross-lingual
  existia antes da varredura. É para não depender de sorte que a regra é escrita.
- **Empate não é "meça mais".** Um braço que empata estatisticamente com o padrão
  e custa mais — latência, rebuild, um botão a mais na configuração — perde por
  não empatar em custo. É por isso que o veredito tem três valores e não dois.

## O piso de n, e por que ele é uma marca e não um filtro

`N_MINIMO = 30` (de `E5.3`). Não é limiar mágico: é o ponto a partir do qual o
intervalo de uma proporção fica estreito o bastante para separar os efeitos que
este projeto persegue, que são de 2 a 4 pontos.

Abaixo dele o intervalo **não é inválido — é honesto, e larguíssimo**. Por isso a
tabela marca a fatia com `⚠` em vez de escondê-la: "n=11, intervalo de 30 pontos"
é o diagnóstico, não um defeito do relatório. É o mesmo argumento de `por_fatia()`
mostrar a fatia vazia com o zero à mostra.

É este piso que dimensiona as ≥500 perguntas do `E1`.

## Uma armadilha de leitura que o relatório precisa avisar

`eval.rodar` imprime o intervalo de **um braço isolado**. Ele é largo de
propósito: ignora a correlação que o pareado aproveita. **Dois intervalos de
braço isolado que se sobrepõem não provam empate** — é o erro de leitura mais
comum com intervalos, e com n pequeno ele aparece o tempo todo. Quem compara
duas configurações lê o Δ pareado de `eval.comparar`, e só ele.

## O achado de bônus: a porta 5 não rodava

Ao plugar a regra de adoção em `eval.comparar` — a ferramenta que implementa a
**porta 5**, a que bloqueia merge por regressão — descobriu-se que ela levantava
`AttributeError` em qualquer recuperador que não fosse o baseline.

`comparar._montar` monta à mão um arremedo de `Args` para reusar
`rodar._montar`, e a lista de campos que `rodar._montar` lê cresceu com as fases.
Faltavam quatro: `base_cfg`, `glossario`, `rerank`, `sem_rerank`. Na prática a
porta 5 estava inexecutável desde o bloco A da F3.5 (15/08), quando `base_cfg`
entrou.

**Nenhum dos testes pegou, e o motivo é instrutivo:** todos montam objetos
`Resultado` à mão e nunca passam por `_montar`. São bons testes da lógica de
comparação e são cegos ao caminho de montagem — a mesma família do defeito de
`F4-P.0`, em que o eval media um recuperador que o cliente não executa.

O conserto tem duas partes, e a segunda é a que importa: além de completar os
campos, `_CAMPOS_DE_MONTAGEM` declara o contrato e um teste o confere contra o
que `rodar._montar` de fato lê, por leitura do código-fonte. A próxima fase que
acrescentar um campo quebra o teste, que é barato, em vez de quebrar a porta.

Dois defeitos menores da mesma ferramenta, consertados junto:

- `--peso-denso`/`--peso-nome` ausentes eram substituídos pelas **constantes do
  módulo**, e não pelo que a base configura. Com os `fts_*` que o `C3.a`
  acrescentou e o que a `F4-P` vai mexer, a porta 5 mediria pesos de fábrica
  contra uma base que configura outros. Agora `None` significa "o que a base
  configura", como em `eval.rodar`.
- Não havia como pedir braços **assimétricos**, o que impedia medir a ablação
  mais óbvia que existe: "esta feature vale a pena?". `--rerank-depois` liga o
  reranking só no braço `depois`; `--rerank` continua ligando nos dois, para o
  caso oposto de segurar a feature constante enquanto se compara outra coisa.

## A tabela de ruído no acervo corporativo

```bash
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank --glossario eval/glossario-teste.toml --out docs/metricas-e5-ruido.md
```

| Recorte | n | recall@1 | IC95 | MRR@10 | IC95 | largura |
|---|---:|---:|:---:|---:|:---:|---:|
| **conjunto no escopo** | 59 | 0.551 | [0.432, 0.678] | 0.680 | [0.581, 0.784] | 0.203 |
| idioma · mesma-língua | 44 | 0.625 | [0.500, 0.761] | 0.750 | [0.647, 0.856] | 0.209 |
| idioma · cross-lingual ⚠ | 12 | 0.333 | [0.083, 0.583] | 0.496 | [0.290, 0.706] | 0.417 |
| idioma · não declarado ⚠ | 3 | 0.333 | [0.000, 1.000] | 0.400 | [0.000, 1.000] | 1.000 |
| fonte · escritório | 46 | 0.641 | [0.521, 0.772] | 0.761 | [0.655, 0.858] | 0.204 |
| fonte · reunião ⚠ | 11 | 0.091 | [0.000, 0.273] | 0.287 | [0.148, 0.464] | 0.315 |
| fonte · email ⚠ | 2 | 1.000 | [1.000, 1.000] | 1.000 | [1.000, 1.000] | 0.000 |
| fonte · misto | 0 | — | — | — | — | — |

Os pontos batem com o que já estava registrado — recall@1 0,551, MRR 0,680,
cross-lingual 0,333, reunião 0,287. O que é novo são as colunas de intervalo, e
elas dizem três coisas:

- **Metade dos recortes não tem n para medir nada.** Quatro dos oito estão abaixo
  do piso, e dois deles são risíveis: `email` com **2** perguntas e `não declarado`
  com **3**, cujo MRR cabe num intervalo de **1,000** — a largura inteira da
  métrica. `email` marcar 1,000 de recall@1 é ruído com aparência de perfeição.
- **`email` com n=2 tem intervalo degenerado**, e isso é uma armadilha própria: o
  bootstrap de uma amostra em que todos os valores são iguais devolve
  `[1,000; 1,000]`, que *parece* certeza absoluta. Não é — é o instrumento
  dizendo que com n=2 e nenhuma variação observada ele não tem o que reamostrar.
- **O alvo da `F4-P` cabe dentro do intervalo do próprio baseline.** A meta de
  0,452 de MRR em reunião está **dentro** de [0,148; 0,464], o intervalo do estado
  atual. Isso **não** significa que a `F4-P` seja indetectável — o teste pareado é
  muito mais potente que comparar dois intervalos isolados, e é exatamente por
  isso que a armadilha de leitura acima está escrita. Mas significa que a `F4-P`
  **não pode** ser justificada exibindo dois relatórios de `eval.rodar` lado a
  lado. Ela tem de sair de `eval.comparar`.

## O que o n=11 consegue e não consegue detectar

A pergunta prática da `F4-P` é: *se o mecanismo funcionar, o instrumento vai ver?*
Ela é respondível sem índice nenhum, e a resposta tem uma forma que não estava na
hipótese.

Simulando sobre as 11 perguntas de reunião, com um ganho **concentrado** (algumas
perguntas saem de "não achada" para 1º lugar e o resto não muda):

| perguntas que sobem | Δ MRR | IC95 | veredito |
|---:|---:|:---:|:--:|
| 1 | +0.091 | [+0.000, +0.273] | ➖ empate |
| 2 | +0.182 | [+0.000, +0.455] | ➖ empate |
| 3 | +0.273 | [+0.000, +0.545] | ➖ empate |
| **4** | **+0.364** | **[+0.091, +0.636]** | ✅ **ganha** |
| 5 | +0.455 | [+0.182, +0.727] | ✅ ganha |

E com o mesmo ganho **espalhado** (todas as 11 sobem um pouco):

| ganho por pergunta | Δ MRR | IC95 | veredito |
|---:|---:|:---:|:--:|
| +0.05 | +0.050 | [+0.050, +0.050] | ✅ ganha |
| +0.10 | +0.100 | [+0.100, +0.100] | ✅ ganha |
| +0.15 | +0.150 | [+0.150, +0.150] | ✅ ganha |

**A detectabilidade em n=11 depende da forma do efeito, não só do tamanho.** Um Δ
de **+0,273** concentrado em três perguntas é **empate**; um Δ de **+0,150**
espalhado pelas onze **ganha**. O concentrado é 1,8× maior e reprova, porque o que
o intervalo mede é a variância da diferença por pergunta — e três acertos em onze
sorteios com reposição às vezes saem zero.

Três consequências diretas para a `F4-P`:

1. **O alvo de +0,165 em reunião, se vier de duas perguntas indo para o 1º lugar
   (+0,182), é empate.** Está na tabela. A `F4-P` precisa de um mecanismo que
   melhore a ordenação de forma **ampla** na fatia, não de duas perguntas
   consertadas.
2. **Isso é diagnóstico, não obstáculo.** Uma mudança de peso que só conserta duas
   perguntas provavelmente é ajuste àquelas duas — que é precisamente o
   sobreajuste que o `E1` e o `E3` existem para impedir. O instrumento estar
   recusando esse caso é ele funcionando.
3. **Se a `F4-P` medir empate em reunião, isso não fecha o pacote como fracasso** —
   fecha como "não decidível neste n", e a decisão espera o `E1`. É a diferença
   entre um resultado e uma pendência declarada, e o roadmap já sabe lidar com a
   segunda.

## A re-análise: o reranking da F2

O aceite do `E5` pede uma ablação antiga reanalisada como demonstração, e a
candidata nomeada era o reranking — o ganho de **poucos pontos** que a F2 adotou.

```bash
py -m eval.comparar --base padrao --antes hibrido --depois hibrido --rerank-depois --glossario eval/glossario-teste.toml --out docs/metricas-e5-rerank-reanalise.md
```

Índice atual: 2.156 documentos, 98.326 chunks, 1.900 alcançáveis pela busca,
`e5-large`, 59 perguntas no escopo, glossário de teste ligado nos dois braços.

**Isto não refaz a medição da F2** — é o mesmo braço medido no acervo de hoje, que
é maior. O que se compara não é o valor com o de 16/08; é o valor **com o próprio
intervalo**.

| Recorte | n | Δ recall@1 | | Δ MRR@10 | | Δ nDCG@5 | |
|---|---:|:---:|:--:|:---:|:--:|:---:|:--:|
| **conjunto no escopo** | 59 | +0.000 [-0.051, +0.051] | ➖ | **+0.012 [-0.031, +0.055]** | ➖ | **+0.022 [-0.010, +0.054]** | ➖ |
| idioma · mesma-língua | 44 | +0.000 [-0.068, +0.068] | ➖ | +0.005 [-0.053, +0.055] | ➖ | +0.022 [-0.022, +0.066] | ➖ |
| idioma · cross-lingual ⚠ | 12 | +0.000 [+0.000, +0.000] | ➖ | **+0.031 [+0.003, +0.064]** | ✅ | +0.024 [+0.000, +0.070] | ➖ |
| idioma · não declarado ⚠ | 3 | +0.000 [+0.000, +0.000] | ➖ | +0.044 [+0.000, +0.133] | ➖ | +0.018 [+0.000, +0.053] | ➖ |
| fonte · escritório | 46 | +0.000 [-0.065, +0.065] | ➖ | +0.005 [-0.048, +0.058] | ➖ | +0.017 [-0.018, +0.056] | ➖ |
| fonte · reunião ⚠ | 11 | +0.000 [+0.000, +0.000] | ➖ | +0.046 [-0.028, +0.102] | ➖ | +0.049 [-0.031, +0.141] | ➖ |
| fonte · email ⚠ | 2 | +0.000 [+0.000, +0.000] | ➖ | +0.000 [+0.000, +0.000] | ➖ | +0.000 [+0.000, +0.000] | ➖ |
| fonte · misto | 0 | — | | — | | — | |

Porta 5 no mesmo relatório: **passa** — zero regressão em armadilha, 2 quedas do
1º lugar contra o orçamento de 3, nenhuma pergunta sumiu do ranking. 13 melhoraram,
3 pioraram, 43 ficaram iguais.

### O que a re-análise diz

**1. O ganho é real em sinal e em tamanho, e está dentro do ruído.** O Δ de MRR
agregado é **+0,012**, quase exatamente o +0,011 que a F2 registrou; o de nDCG@5 é
**+0,022**, o dobro do +0,011 que a fase citou. E os dois intervalos cruzam zero —
**[−0,031; +0,055]** e **[−0,010; +0,054]**. Pela regra de adoção o veredito é
**empate** nas três métricas, e empate resolve por simplicidade.

Vale notar o que isso **não** é: não é "o reranking não funciona". O ponto estimado
é positivo em todas as métricas e em todos os recortes — nenhum Δ negativo na
tabela inteira. É que com n=59 o instrumento não separa +0,022 de zero, e uma
feature que custa 6,8× no tempo de consulta precisa de mais que "provavelmente
positivo".

Isso **não retrata a F2** e nem é uma correção: o reranking já está **desligado por
padrão** desde 16/08, e o motivo declarado foi custo — 6,8× no tempo de consulta
por 3,4 pontos. A re-análise fortalece a decisão que já tinha sido tomada, e
mostra que ela foi tomada pelo argumento certo por um caminho mais longo. Com o
intervalo à mão, a conversa sobre custo nem precisaria ter acontecido.

**2. O reranking não move o topo — move a cauda.** Δ recall@1 é **+0,000** em todos
os recortes, e em quatro deles o intervalo é **degenerado** (`[+0,000, +0,000]`):
nenhuma pergunta daquele recorte mudou de "acerta em 1º" para "não acerta em 1º"
ou vice-versa. No agregado o intervalo não é degenerado (`[−0,051; +0,051]`), o que
diz outra coisa: houve troca, e ela se anulou.

É consistente com o mecanismo e vale registrar: com peso 0,25 o cross-encoder entra
como **quarto ranqueador** numa fusão RRF, não como juiz. Ele reordena dentro do
top-10 e quase nunca desloca o primeiro. Quem quiser mover recall@1 com reranking
tem de mudar o **peso**, e `ablacao-rerank.md` já mediu que substituir a ordenação
é o pior resultado da grade (0,489).

**3. A única fatia que acende é a cross-lingual — e ela é uma pista, não um
resultado.** Δ MRR **+0,031 [+0,003; +0,064]**, o único ✅ da tabela. Bate com a
hipótese de `C4.2` (rerank cross-lingual, onda 7), que existe justamente porque o
cross-encoder é multilíngue e os outros dois votos são cegos a idioma.

E ela acende em **uma métrica de três**: em nDCG@5 o mesmo recorte dá
+0,024 **[+0,000; +0,070]**, que não exclui zero. Um efeito real costuma aparecer
nas três; um artefato de amostragem aparece na que teve sorte.

**Além disso a fatia não foi declarada antes**, e é aqui que a própria regra do
pacote morde: com **oito recortes** na tabela, a chance de pelo menos um acender por acaso
sob hipótese nula é `1 − 0,95⁸ ≈ 34%`. Um ✅ entre oito é, sozinho, quase o que se
espera do acaso. O que salva a leitura é a fatia ter um **prior escrito antes da
medição** — `C4.2` está no roadmap desde antes deste relatório — e o que a
transforma em resultado é medi-la de novo com ela declarada como alvo, de
preferência num n maior. É trabalho de `C4.2`, e agora ele tem número de partida.

### A comparação múltipla é uma lacuna do `E5`, e fica registrada

O relatório de origem escreve a regra de adoção para **uma** fatia-alvo e não trata
o caso de olhar oito. As duas defesas ficam assim, e as duas são de processo e não
de estatística:

1. **A fatia-alvo é declarada no pacote, antes de rodar.** É o que a `F4-P` já faz
   — o alvo dela (reunião ≥ 0,452 de MRR) está escrito desde 24/08.
2. **Fatia que acende sem ter sido declarada é pista para o pacote seguinte**, com
   o prior citado, nunca conclusão do pacote atual.

Correção de Bonferroni ou equivalente **não** entra por enquanto: com n=11 numa
fatia, dividir α por oito tornaria a tabela incapaz de detectar qualquer efeito
real, e o resultado prático seria ninguém olhar a tabela. O caminho certo é o do
`E1` — mais perguntas por fatia — e não um limiar mais duro sobre o n de hoje.

## O que fica para os pacotes seguintes

- **`F4-P` tem a régua de ruído que precisava, e ela vem com uma condição.** O Δ
  que a fase persegue em `reunião` (0,287 → 0,452 de MRR, **+0,165**) é 3,6× o que
  o reranking move na mesma fatia (+0,046, empate). Mas pela seção acima ele só é
  detectável em n=11 **se for amplo** — concentrado em duas perguntas, +0,182 dá
  empate. O critério de saída da `F4-P` ganha uma linha: além do valor, olhar
  quantas perguntas se moveram, que é o que `eval.comparar` já lista.
- **`C4.2` ganha número de partida** e a instrução de declarar a fatia antes.
- **`R6.1`** (autotune) passa a ter critério de parada: grade que não excluir zero
  na fatia declarada não muda peso nenhum.
- **`E1`** herda a razão de existir mais concreta que tinha: **quatro dos oito
  recortes desta tabela estão abaixo do piso de n**, e dois deles (`email` com 2,
  `não declarado` com 3) são pequenos a ponto de não medirem nada.
