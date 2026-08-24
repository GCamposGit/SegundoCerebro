# A fatia cross-lingual — C4.5

**24/08/2026, notebook.** Condição C: acervo corporativo, índice com 2.156
documentos e 98.326 trechos, `e5-large`, sem reranking, glossário de siglas
ligado. O conjunto dourado real (62 perguntas) e os relatórios por pergunta não
vão para o Git; aqui só entram números agregados.

Este documento é a saída do pacote `C4.5` do
[`dossie-complemento-update-devs.md`](dossie-complemento-update-devs.md): fazer o
harness recortar toda medição em `mesma-língua` contra `cross-lingual`.

---

## O acervo é bilíngue, e ninguém tinha medido quanto

| | documentos | %  |
|---|---:|---:|
| português | 1.590 | 83,7% |
| **inglês** | **284** | **15,0%** |
| misto | 11 | 0,6% |
| sem evidência de idioma | 15 | 0,8% |
| **com conteúdo indexado** | **1.900** | 100% |

E no conjunto dourado, por pergunta:

| Fatia | n |
|---|---:|
| mesma-língua | 44 |
| **cross-lingual** | **12** |
| não declarado | 6 |

Um sexto do acervo e um quinto do dourado. Não é um caso de borda.

## O número que a fatia acusa

Recuperador híbrido, sem reranking, 59 perguntas no escopo:

| Fatia | n | recall@1 | recall@5 | recall@10 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|
| mesma-língua | 44 | 0.625 | 0.852 | 0.932 | 0.750 | 0.754 |
| **cross-lingual** | **12** | **0.333** | **0.625** | 0.875 | **0.496** | **0.493** |
| não declarado | 3 | 0.333 | 0.667 | 0.667 | 0.400 | 0.394 |

**recall@1 cai 47% quando a pergunta e a fonte estão em idiomas diferentes**
(0.625 → 0.333), e o MRR cai 34%. A razão cross-lingual / mesma-língua em
recall@5 é **0.73**, abaixo do **0.80** que o próprio `C4.5` põe como critério de
aceite.

A média agregada da mesma passada é recall@1 **0.551** — o piso de regressão que
o `ROADMAP.md` já registra. Ela não mostra nada disto: a fatia mesma-língua é
quase quatro vezes maior e a esconde por construção.

O sinal recupera em recall@10 (0.875 contra 0.932) e chega a **1.000 em
recall@20**. Isso localiza o defeito: **o documento certo está sendo alcançado, e
está sendo mal ordenado.** É o perfil de quem tem um ranqueador cego no meio da
fusão, não o de quem não encontra.

E é exatamente o que a arquitetura prevê. A ponte entre idiomas mora num
ranqueador só — o denso é multilíngue e alinhado; o bm25 é cego a idioma **por
construção**, porque FTS5 não casa `contrato` com `agreement`; e o ranqueador de
nome herda o idioma do nome do arquivo. Numa consulta cross-lingual, dois dos
três votos da fusão votam no idioma errado.

## O que este número não prova

- **São 12 perguntas.** Chegam para acusar direção, não para escolher peso. O
  intervalo é largo e uma pergunta a mais ou a menos move a terceira casa.
- **É um acervo só**, com a limitação já declarada em
  [`dourado-cobertura.md`](dourado-cobertura.md): o dourado cobre 25% do índice.
  A fatia herda essa limitação inteira.
- **Não isola a causa.** "Dois de três ranqueadores são cegos a idioma" é a
  explicação que a arquitetura sugere e que o perfil recall@10-alto /
  recall@1-baixo é consistente com — não é uma ablação. Medir `--sem-nome` e
  denso puro **na fatia** é o que decidiria, e isso é `F4-P` (onda 2).

O valor da entrega não é este número. É que a partir de agora **nenhuma troca de
modelo denso ou de reranker pode passar sem que a coluna cross-lingual apareça
do lado da média.** Antes de hoje, uma que quebrasse só a ponte teria passado
como ganho.

## Três decisões de desenho, e por quê

**1. Três resultados, não dois.** `não declarado` existe porque a alternativa é
pior. Uma consulta de três palavras feita de sigla e número não tem evidência de
idioma nenhuma, e chutar `pt` porque o acervo é 84% português colocaria a
pergunta na fatia errada em silêncio — inflando justamente a métrica que existe
para achar a fraqueza. Fatia vazia aparece na tabela com o zero à mostra, para
"medimos e não há par cross-lingual" nunca virar a mesma linha que "a fatia não
foi calculada".

**2. A anotação é estática no conjunto dourado, não derivada do índice.** O
motivo é comparabilidade entre fases, que é a razão de o harness existir antes
dos recuperadores: **o baseline por nome não abre o índice.** Se a fatia fosse
calculada no relatório, ela sumiria do lado F0 de toda comparação. O preço é que
a anotação envelhece — e o preço se paga com `conferir()`, que confronta
anotação e índice a cada `eval.rodar` e separa "falta anotar" (contagem) de
"anotado diferente do que o índice mostra" (uma a uma).

**3. Os dois campos de idioma não são simétricos.** `idioma` (da pergunta) tem
detecção de reserva, porque o texto está no arquivo; `idioma_fonte` não tem, pelo
motivo acima. Consequência que só apareceu escrevendo: `indefinido` **não** é
gravado em `idioma`. Gravá-lo congelaria a pergunta contra o detector — sem
`conferir()` daquele lado, melhorar as listas deixaria de alcançá-la e nada
avisaria. Em `idioma_fonte` é o contrário: ali `indefinido` é dado, e é conferido.

## O detector

Contagem de palavra funcional, sem dependência nova, em `eval/idioma.py`. Não é
classificador de idioma e não precisa ser: as duas línguas do acervo são
conhecidas, e o que se pede dele é separar duas listas fechadas.

Palavra funcional é o sinal certo aqui porque é o que **não** viaja por
empréstimo: `compliance`, `template` e `budget` aparecem em documento português;
artigo, preposição e conjunção, não.

Duas correções que só o teste achou, e as duas são de **normalização**, não de
vocabulário:

- `as` é tão inglês quanto português e faltava na lista EN. Sem isso, texto
  inglês longo acumulava pontos de português proporcionais ao tamanho — quanto
  maior o documento, mais errado o veredito.
- `só` perde o acento na normalização e vira `so`, que é palavra funcional
  inglesa. Sem o desconto, o português pontuava para o inglês toda vez que
  dizia "só".

As duas se resolvem pelo mesmo mecanismo, que é o desconto das palavras
ambíguas: `a`, `as`, `do`, `no`, `so` não contam para ninguém. Descontar é mais
honesto que dar peso baixo — palavra que existe nos dois idiomas não é evidência
de nenhum, e mantê-la só adiciona ruído proporcional ao tamanho do texto.

Sobre o acervo real o detector deixa **15 documentos** e **1 pergunta** sem
decidir. A pergunta foi anotada à mão: tem uma única palavra funcional, abaixo
do limiar. Baixar o limiar para acertá-la passaria a errar as outras sessenta em
silêncio — por isso a saída é anotar, não afrouxar.

## O que muda na fila

- **`R3.1` (ablação de modelo) e `R6.2` (rerank v2)** não podem mais ser
  decididos pela média. A tabela de `eval.ablacao_f2` ganhou duas colunas de MRR,
  mesma-língua e cross-lingual, lado a lado.
- **`R6.2` ganha um alvo medido.** O `bge-reranker-base` de hoje é treinado
  primariamente em CN+EN, e par pergunta-PT / documento-EN é o pior caso dele. A
  fatia diz onde ele deve perder por mais.
- **`F4-P` (peso por tipo de fonte) herda uma pergunta.** Se dois dos três votos
  da fusão são cegos a idioma, o peso por fatia é candidato pelo mesmo argumento
  que o peso por tipo de fonte — e a primeira coisa a varrer continua sendo a
  dupla contagem do nome de arquivo (`C3.a`).
- **`R9.1` (perfil sintético bilíngue) tem contrato.** O gerador precisa emitir
  `idioma` e `idioma_fonte` já preenchidos. Corpus bilíngue sem `idioma_fonte`
  produz fatia de tamanho zero e um relatório que parece aprovado. Formato em
  [`../eval/golden/README.md`](../eval/golden/README.md).

## Reproduzir

```bash
py -m eval.idioma --base padrao                      # relata a fatia
py -m eval.idioma --base padrao --escrever           # anota o dourado
py -m eval.rodar --base padrao --retriever hibrido --sem-rerank \
    --glossario eval/glossario-teste.toml \
    --out docs/metricas-f4-c45-cross-lingual.md      # gitignorado
```
