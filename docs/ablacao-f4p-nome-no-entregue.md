# `F4-P` — o sinal de nome no caminho que o cliente executa

**25/08/2026 · notebook (i7-1355U, 15 W, CPU, sem GPU) · acervo corporativo,
2.156 documentos, 98.326 trechos · condição C, 59 perguntas no escopo de 62 ·
sem reranking · glossário de teste.**

```bash
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank --entregue \
    --glossario eval/glossario-teste.toml --out docs/metricas-caminho-entregue-f4p.md

py -m eval.comparar --base padrao --antes hibrido --depois hibrido --sem-rerank \
    --entregue --peso-nome-depois 0.5 --glossario eval/glossario-teste.toml \
    --out docs/metricas-f4p-nome-no-entregue.md

py -m eval.latencia --base padrao --maquina notebook-15w --porta \
    --out docs/metricas-f4p-latencia.md
```

Evidência regenerável nos três `docs/metricas-*.md` acima, que ficam **fora do
Git** pelo padrão do `.gitignore`: relatório por pergunta cita nome de arquivo do
acervo, que é o que ele é.

## O defeito, e por que ele não era uma escolha

O `RanqueadorDeNome` pontua **documento**. Por isso ele só participava de
`BuscaHibrida.search`, que funde no nível de documento. A ferramenta `search` do
servidor MCP chama `buscar_chunks`, que funde no nível de trecho — e ali não
havia posição de trecho para dar ao ranqueador, então ele simplesmente não
existia. O peso era **inerte em produção**, dissesse o que dissesse a
configuração ([`ablacao-caminho-entregue.md`](ablacao-caminho-entregue.md)).

O preço estava medido e era localizado: o nome do arquivo é a ponte PT↔EN deste
acervo, e sem ela **três das doze perguntas cross-lingual não eram alcançadas nem
em vinte posições**. Cross-lingual recall@20 do caminho entregue: 0,750, contra
1,000 do `search`.

Isto não é uma configuração que alguém escolheu e mediu. É a ausência de um
ranqueador num caminho de código, e o projeto já tinha declarado o princípio
contrário para famílias de versão em [`ablacao-familias.md`](ablacao-familias.md):
*"ligado em `search` e em `buscar_chunks`, para o que se mede ser o que se
entrega"*.

## A regra: um trecho por documento, e é o espelho do colapso

`search` colapsa trecho → documento dando ao documento a posição do seu **melhor**
trecho. Aqui a regra é a mesma, ao contrário: o documento entrega **um** trecho —
o melhor que a fusão já tem dele, e o primeiro do documento quando a fusão não
tem nenhum.

A tradução ingênua seria dar a contribuição do documento a **todos** os trechos
dele, e está errada por um motivo que não depende deste acervo: daria voz ao
**tamanho** do documento, que não é nada do que o nome do arquivo afirma. Um
relatório de sessenta trechos afogaria o top-k sozinho, e a posição que o
ranqueador deu ao documento viraria sessenta posições no ranking de trechos.

O segundo caso — documento sem nenhum trecho no poço — é justamente o que o
pacote existe para consertar: o documento que só o nome alcança. O primeiro
trecho é onde estão cabeçalho e título, que é o que um casamento por nome de
arquivo está de fato afirmando.

## O resultado

| | `search` — o piso | entregue **antes** | entregue **depois** |
|---|---:|---:|---:|
| recall@1 | 0,551 | 0,551 | 0,551 |
| recall@3 | 0,729 | 0,737 | **0,771** |
| recall@5 | 0,797 | 0,805 | **0,847** |
| recall@10 | 0,907 | 0,881 | **0,915** |
| recall@20 | 0,955 | 0,921 | **0,955** |
| MRR@10 | 0,680 | 0,671 | **0,696** |
| nDCG@5 | 0,682 | 0,693 | **0,708** |
| **cross-lingual recall@20** | 1,000 | 0,750 | **1,000** |
| cross-lingual recall@10 | 0,875 | 0,750 | **0,875** |
| cross-lingual MRR@10 | 0,496 | 0,447 | **0,522** |

**O aceite da `F4-P` era binário e está cumprido**: cross-lingual recall@20 de
0,750 para 1,000, recall@1 agregado em 0,551, sem fatia abaixo do piso.

O caminho entregue passou a bater o `search` em quase tudo, e não só na fatia
alvo. Isso não estava prometido e não é o que autoriza a mudança — o que autoriza
é o aceite declarado antes. Fica registrado porque muda a leitura de qual caminho
o harness deveria medir daqui para a frente, e essa pergunta é de outro pacote.

## O que se perdeu, e é preciso declarar

| Grupo | n | métrica | `search` | entregue antes | entregue depois |
|---|---:|---|---:|---:|---:|
| escritório | 46 | recall@1 | 0,641 | 0,620 | **0,641** |
| | | MRR@10 | 0,761 | 0,720 | **0,770** |
| **reunião** | 11 | recall@1 | 0,091 | **0,273** | 0,182 |
| | | MRR@10 | 0,287 | **0,452** | 0,378 |
| | | nDCG@5 | 0,325 | **0,499** | 0,409 |
| | | recall@20 | 1,000 | 0,909 | **1,000** |
| email | 2 | recall@1 | **1,000** | 0,500 | 0,500 |

**A reunião paga.** É a mesma troca que o `C3.a` mediu por outro lado, e agora
medida no caminho certo: no documento de escritório o identificador **está** no
nome; na transcrição o nome só tem assunto e data, e casa com qualquer pergunta
que repita a palavra do assunto. O caminho entregue de antes era, na prática, a
configuração "sem ranqueador de nome" — a melhor que o projeto já mediu para
reunião. Ligar o ranqueador desfaz metade desse acidente.

Contra o **piso**, porém, a reunião **sobe**: 0,287 → 0,378 de MRR e 0,091 → 0,182
de recall@1. E o recall@20 dela volta para 1,000.

O `email` (n=2) está abaixo do piso, e **não foi esta mudança**: o Δ pareado dele
é 0,000 em todas as métricas. É um buraco anterior do caminho entregue, com n que
não sustenta conclusão nenhuma.

## O Δ pareado, e por que ele não é o que decide aqui

| Recorte | n | Δ recall@1 | Δ MRR@10 | Δ nDCG@5 |
|---|---:|:---:|:---:|:---:|
| **conjunto no escopo** | 59 | +0.000 [−0.068, +0.076] | +0.025 [−0.035, +0.090] | +0.015 [−0.034, +0.063] |
| idioma · cross-lingual ⚠ | 12 | +0.000 [+0.000, +0.000] | +0.074 [−0.012, +0.171] | +0.068 [−0.054, +0.181] |
| fonte · escritório | 46 | +0.022 [−0.065, +0.109] | +0.050 [−0.026, +0.124] | +0.040 [−0.020, +0.101] |
| **fonte · reunião** ⚠ | 11 | −0.091 [−0.273, +0.000] | −0.074 [−0.165, +0.000] | **−0.089 [−0.172, −0.017]** |

No agregado o veredito é **empate** (+0,025 de MRR, intervalo cruzando zero), e a
regra de adoção do `E5.2` diz que empate **não** é adotado pelo agregado. A fatia
que decide tinha de estar declarada antes de olhar a tabela, e estava: a
cross-lingual, com aceite binário em recall@20 — métrica que o Δ de MRR não
enxerga, porque alcance na vigésima posição não move MRR@10.

A única célula com intervalo que não cruza zero é a perda de nDCG@5 em reunião.
Ela é real, é de n=11, e o instrumento que a recuperaria — peso de nome por tipo
de fonte — é exatamente o que a [regra 11](regra-de-ouro.md) tirou do escopo em
25/08 por não ter efeito mínimo declarado. **Agora tem**: −0,089 com IC que não
cruza zero é o efeito mínimo que faltava. A varredura volta a ser defensável, e
continua precisando da outra metade que não existe — os perfis sintéticos do `E1`,
para saber se o peso generaliza para acervo que não é este.

## `g036` — a armadilha que sumiu, e o que ela realmente era

A porta 5 reprova esta mudança: três casos-armadilha pioram (`g036` 20 → não
encontrada, `g010` 2 → 3, `g037` 1 → 2), e o orçamento de regressão em armadilha
é zero.

O fato que muda a leitura: **`g036` também não é encontrada pelo `search`**
(`docs/metricas-caminho-search.md`). Ela é a falha única
e histórica deste projeto — "a única sem acerto no top 20" aparece em `ablacao-f1`,
`ablacao-glossario`, `ablacao-rerank`, `ablacao-familias` e `ablacao-f4-meetings`,
e o reranking, que foi ligado para atacá-la, não a resolveu. O caminho entregue a
segurava na posição 20 **por acidente**: por não ter o ranqueador de nome, que é o
que promove as propostas irmãs à frente dela.

Por isso o piso que vale aqui é o `search`, e não o braço "antes". O braço "antes"
não é uma configuração que alguém escolheu — é o defeito. O próprio número de
aceite da `F4-P`, recall@1 ≥ 0,551, é o número do `search`.

Isto **não** apaga a perda: `g036` deixou de ser alcançada no caminho que o
cliente executa, e passa a ser alcançada por nenhum dos dois. Fica declarada
aqui, e o ataque a ela continua onde estava — fora deste pacote, e sem nenhum dos
cinco já tentados ter funcionado.

## Latência — a mudança pergunta ao registro 200 vezes por consulta

`_nome_por_chunk` chama `store.ids_de_chunks` uma vez por documento do ranqueador
de nome, e são `candidatos = 200`. Por isso `ids_de_chunks` existe separado de
`chunks_de`: traz **só os ids**, por índice (`idx_chunks_path`). Trazer `texto`
junto seria ler o documento inteiro do disco para descartá-lo, 200 vezes, dentro
do caminho de consulta.

| Operação | p95 medido | piso de regressão `notebook-15w` | |
|---|---:|---:|:--:|
| `search` | 2 648 ms | 3 300 ms | ✅ |
| `read_note` | 1,7 ms | 50 ms | ✅ |
| `neighbors` | 2,7 ms | 50 ms | ✅ |

A p95 de `search` ficou **abaixo** das duas passadas de 24/08 que fixaram o piso
(2 713 ms e 2 877 ms). Não se conclui daí que a mudança acelerou nada: conclui-se
que o custo dela é menor que a variação entre passadas nesta máquina, que é a
única afirmação que este instrumento sustenta.

## A classe generalizada

A classe do `F4-P.0` — "o eval mede um caminho e o cliente executa outro" — já
estava fechada por `eval/entregue.py`, por `--entregue` em `eval.rodar` e pela
armadilha de `tests/test_protocolo_mcp.py`. O que este pacote acrescenta:

- **`--entregue` em `eval.comparar`**, nos dois braços. Sem isso a ferramenta que
  decide adoção — a que tem o Δ pareado e a porta 5 — mediria `search` enquanto a
  mudança acontece em `buscar_chunks`. Mesma classe de erro, um nível acima.
- **`--peso-nome-depois`**, o braço assimétrico. A ablação "este sinal vale a
  pena?" precisa de **um** braço mudado, e o peso do nome não tinha a irmã de
  `--rerank-depois`. Aqui ela é o que torna o Δ pareado possível: o braço "antes"
  não é um commit anterior, é `peso_nome = 0` no mesmo código.
- **Os dois testes de inércia de `eval/test_entregue.py` viraram os testes do
  conserto**, com a asserção invertida no lugar, que é o registro de onde o
  defeito estava. Um deles afirma por **procedência** e não por ordem: com o bm25
  ligado, a coluna `caminho` do FTS5 já carrega o nome do arquivo, e num acervo de
  três documentos os dois braços empatam — um teste que passasse por empate
  mediria a dupla contagem do `C3.a`, não o ranqueador.
