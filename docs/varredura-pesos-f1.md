# Varredura de pesos da fusão RRF — F1

45 perguntas no escopo, 437 documentos, 11208 chunks, modelo `e5-large:1024:fastembed0.8.0`, 200 candidatos por ranking.

Grade e regra de escolha declaradas em `eval/varredura.py` **antes** de rodar.
São 37 configurações sobre 45 perguntas, e escolher olhando a tabela
pronta seria escolher o ruído; como os 6 casos-armadilha estão dentro dos 39
rascunhos, não existe divisão limpa entre ajuste e validação. A grade inteira
está aqui porque superfície plana e superfície com pico levam a conclusões
diferentes.

Os três pesos variam. A grade anterior fixava o lexical em 1,0 — o que não
normaliza a escala, apenas **impede o lexical de ser zero** — e por isso não
enxergava `denso + nome` sem bm25. Aqui os triplos são canônicos: como `rrf` é
linear nos pesos, `(2, 2, 1)` ordena igual a `(1, 1, 0,5)`, então basta manter
os de máximo 1,0. Um representante por razão distinta, sem perder ponto.

**Regra:** maior MRR@10 entre as configurações com pelo menos 4 de 6 casos-armadilha no top-10. Desempate por recall@1 e,
persistindo, pelo menor peso de nome.

## A grade

| denso | bm25 | nome | recall@1 | recall@10 | MRR@10 | nDCG@10 | armadilhas | usuário MRR | multi-hop | elegível |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| 1 | 0 | 1 | 0.633 | 0.911 | 0.769 | 0.793 | 3 de 6 | 0.672 | 4 de 5 | não |
| 1 | 0.25 | 0.5 | 0.622 | 0.919 | 0.759 | 0.783 | 4 de 6 | 0.623 | 2 de 5 | sim **←** |
| 1 | 0.5 | 0.25 | 0.644 | 0.885 | 0.756 | 0.772 | 4 de 6 | 0.572 | 2 de 5 | sim |
| 1 | 0 | 0.5 | 0.589 | 0.907 | 0.755 | 0.779 | 3 de 6 | 0.722 | 3 de 5 | não |
| 1 | 0 | 0.25 | 0.567 | 0.941 | 0.744 | 0.776 | 5 de 6 | 0.694 | 2 de 5 | sim |
| 1 | 0.5 | 0.5 | 0.622 | 0.896 | 0.743 | 0.767 | 4 de 6 | 0.572 | 2 de 5 | sim |
| 1 | 1 | 0.5 | 0.644 | 0.863 | 0.742 | 0.763 | 4 de 6 | 0.533 | 2 de 5 | sim |
| 1 | 0.25 | 1 | 0.600 | 0.900 | 0.742 | 0.768 | 3 de 6 | 0.660 | 3 de 5 | não |
| 1 | 0.25 | 0.25 | 0.600 | 0.885 | 0.735 | 0.763 | 4 de 6 | 0.576 | 1 de 5 | sim |
| 1 | 0.5 | 1 | 0.600 | 0.900 | 0.735 | 0.762 | 3 de 6 | 0.624 | 3 de 5 | não |
| 0.5 | 0.5 | 1 | 0.600 | 0.911 | 0.734 | 0.765 | 3 de 6 | 0.614 | 4 de 5 | não |
| 1 | 1 | 1 | 0.622 | 0.874 | 0.734 | 0.757 | 3 de 6 | 0.558 | 2 de 5 | não |
| 0.5 | 0 | 1 | 0.578 | 0.911 | 0.734 | 0.770 | 3 de 6 | 0.672 | 4 de 5 | não |
| 0.5 | 0.25 | 1 | 0.578 | 0.911 | 0.729 | 0.765 | 3 de 6 | 0.657 | 4 de 5 | não |
| 1 | 0.25 | 0 | 0.622 | 0.874 | 0.727 | 0.762 | 4 de 6 | 0.562 | 1 de 5 | sim |
| 1 | 1 | 0.25 | 0.600 | 0.863 | 0.724 | 0.746 | 4 de 6 | 0.524 | 2 de 5 | sim |
| 0.5 | 1 | 1 | 0.622 | 0.844 | 0.722 | 0.743 | 3 de 6 | 0.528 | 2 de 5 | não |
| 0.5 | 1 | 0.5 | 0.600 | 0.863 | 0.721 | 0.746 | 4 de 6 | 0.528 | 2 de 5 | sim |
| 1 | 0.5 | 0 | 0.600 | 0.852 | 0.716 | 0.747 | 4 de 6 | 0.528 | 1 de 5 | sim |
| 0.25 | 1 | 1 | 0.600 | 0.844 | 0.715 | 0.735 | 3 de 6 | 0.528 | 2 de 5 | não |
| 1 | 1 | 0 | 0.589 | 0.852 | 0.712 | 0.737 | 4 de 6 | 0.433 | 1 de 5 | sim |
| 0.25 | 0.25 | 1 | 0.578 | 0.878 | 0.708 | 0.737 | 3 de 6 | 0.574 | 3 de 5 | não |
| 0.25 | 1 | 0.25 | 0.578 | 0.878 | 0.707 | 0.742 | 5 de 6 | 0.519 | 2 de 5 | sim |
| 0.25 | 0.5 | 1 | 0.578 | 0.878 | 0.707 | 0.736 | 3 de 6 | 0.558 | 3 de 5 | não |
| 0.25 | 0 | 1 | 0.578 | 0.856 | 0.704 | 0.735 | 3 de 6 | 0.607 | 3 de 5 | não |
| 0.5 | 1 | 0.25 | 0.556 | 0.863 | 0.699 | 0.733 | 4 de 6 | 0.519 | 2 de 5 | sim |
| 0.25 | 1 | 0.5 | 0.556 | 0.856 | 0.691 | 0.725 | 4 de 6 | 0.528 | 2 de 5 | sim |
| 0.5 | 1 | 0 | 0.544 | 0.841 | 0.687 | 0.722 | 4 de 6 | 0.375 | 2 de 5 | sim |
| 0 | 1 | 0.5 | 0.556 | 0.856 | 0.684 | 0.719 | 4 de 6 | 0.519 | 2 de 5 | sim |
| 1 | 0 | 0 | 0.522 | 0.885 | 0.678 | 0.726 | 5 de 6 | 0.583 | 1 de 5 | sim |
| 0 | 1 | 1 | 0.544 | 0.867 | 0.677 | 0.718 | 4 de 6 | 0.519 | 2 de 5 | sim |
| 0 | 0.5 | 1 | 0.544 | 0.856 | 0.675 | 0.712 | 3 de 6 | 0.524 | 3 de 5 | não |
| 0 | 0 | 1 | 0.533 | 0.844 | 0.672 | 0.706 | 3 de 6 | 0.565 | 2 de 5 | não |
| 0 | 0.25 | 1 | 0.544 | 0.833 | 0.671 | 0.704 | 3 de 6 | 0.533 | 3 de 5 | não |
| 0.25 | 1 | 0 | 0.522 | 0.844 | 0.665 | 0.704 | 5 de 6 | 0.361 | 1 de 5 | sim |
| 0 | 1 | 0.25 | 0.511 | 0.822 | 0.657 | 0.690 | 4 de 6 | 0.417 | 1 de 5 | sim |
| 0 | 1 | 0 | 0.500 | 0.767 | 0.598 | 0.633 | 5 de 6 | 0.333 | 1 de 5 | sim |

## Escolhido pela regra

`denso=1`, `lexical=0.25`, `nome=0.5` — MRR@10 0.759, recall@1 0.622, 4 de 6 armadilhas, 2 de 5 multi-hop.

Vale como **hipótese**, não como conclusão: foi escolhido nas mesmas 45 perguntas que servem de porta. A confirmação é a medição no corpus completo, que é amostra independente.
