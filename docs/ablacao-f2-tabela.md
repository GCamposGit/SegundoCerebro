# Ablação da F2 — tabela consolidada

> Medido na condição C: 1601 documentos, 92137 chunks, 45 perguntas no escopo, modelo `e5-large:1024:fastembed0.8.0`, 200 candidatos por ranking antes da fusão.

Os braços estão declarados em `eval/ablacao_f2.py`, **em ordem de acréscimo**:
cada linha difere da anterior por um fator só, e é isso que permite atribuir
a diferença àquele fator. Todos correram na mesma passada, com o encoder aberto
uma única vez, sobre as mesmas perguntas e o mesmo índice.

O critério de saída da fase pede `denso-só vs. híbrido vs. híbrido+rerank`.
Essas são as linhas **denso puro**, **os três + famílias** e **+ rerank**; o
resto da escada está aqui porque uma superfície plana e uma com pico levam a
conclusões diferentes, e só o vencedor não distingue as duas.

## A tabela

| Recuperador | o que acrescenta | recall@1 | recall@5 | recall@10 | MRR@10 | nDCG@5 | nDCG@10 | armadilhas | multi-hop | usuário MRR | s/consulta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| _baseline por nome de arquivo_ | _referência da F0_ | _0,467_ | — | _0,800_ | _0,592_ | — | _0,643_ | _3 de 6_ | _3 de 5_ | _0,557_ | — |
| bm25 puro | só casamento exato | 0,511 | 0,733 | 0,778 | 0,611 | 0,628 | 0,648 | 4 de 6 | 1 de 5 | 0,333 | 0,14 |
| denso puro | só significado | 0,522 | 0,844 | 0,885 | 0,670 | 0,700 | 0,715 | 5 de 6 | 1 de 5 | 0,556 | 0,78 |
| denso + bm25 | + o segundo ranqueador | 0,600 | 0,830 | 0,896 | 0,712 | 0,732 | 0,751 | 5 de 6 | 1 de 5 | 0,413 | 0,89 |
| bm25 + nome | nome sobre o lexical | 0,533 | 0,722 | 0,800 | 0,638 | 0,647 | 0,675 | 3 de 6 | 1 de 5 | 0,375 | 0,19 |
| denso + nome | nome sobre o denso, sem bm25 | 0,600 | 0,889 | 0,896 | 0,750 | 0,769 | 0,772 | 3 de 6 | 2 de 5 | 0,667 | 0,70 |
| os três, sem famílias | + o terceiro ranqueador | 0,600 | 0,833 | 0,907 | 0,736 | 0,740 | 0,759 | 4 de 6 | 1 de 5 | 0,571 | 0,86 |
| os três + famílias de versão | + metadado de versão | 0,644 | 0,841 | 0,930 | 0,762 | 0,760 | 0,782 | 5 de 6 | 1 de 5 | 0,571 | 0,87 |
| **denso + nome + famílias** | o mesmo, sem bm25 | 0,644 | 0,896 | 0,896 | 0,773 | 0,789 | 0,789 | 3 de 6 | 2 de 5 | 0,667 | 0,72 |
| os três + famílias + rerank 0,25 | + o cross-encoder como 4º ranqueador | 0,678 | 0,841 | 0,930 | 0,785 | 0,771 | 0,794 | 5 de 6 | 1 de 5 | 0,570 | 6,02 |

`armadilhas` e `multi-hop` são **contagem** de casos resolvidos por inteiro no
top-10, não média — as portas 3 e 4 são por caso, e multi-hop exige todas as
fontes. A coluna `usuário MRR` é o subconjunto das 6 perguntas escritas de
memória: as outras 39 nasceram de nomes de arquivo e favorecem, por construção,
quem lê nome.
