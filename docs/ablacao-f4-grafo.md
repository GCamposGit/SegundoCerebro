# F4 — o grafo derivado, e o que medir nele ensinou

> Medido em 20/08/2026 no acervo corporativo: 1.601 documentos no registro,
> 92.137 chunks. As métricas de recuperação estão em `docs/metricas-f4-grafo.md`
> (gitignorado — relatório por pergunta cita nome de arquivo do acervo).
>
> Este arquivo é escrito à mão e é onde mora o raciocínio, separado da evidência
> pelo mesmo motivo de `ablacao-f2.md`: uma regeneração não pode apagar em
> silêncio a conclusão.

## O problema, em uma frase

Este acervo não tem wikilink nenhum, então a única ligação explícita entre dois
documentos é o identificador que os dois citam. Um plano de ação que termina em
"certificação ISO 42001" e o texto da norma, em outra pasta, não têm **nada** em
comum — nem nome, nem pasta, nem vocabulário. Nenhum peso de fusão os aproxima,
por melhor que seja: o que faltava não era precisão, era uma aresta.

## O critério de saída

| Metade | Estado |
|---|---|
| Métricas da F2 não regridem com o grafo construído | ✅ recall@1 **0,667**, MRR **0,787**, nDCG@5 **0,793** — idênticas |
| Uma pergunta multi-hop que **só** é respondível via `neighbors` | ✅ o caso do plano → norma, detalhado abaixo |

A ausência de regressão era esperada — o grafo não entra no caminho de consulta —
mas a regra do projeto é medir, não presumir. Ficou medida.

## O que a passada separada compra

O grafo é derivado do índice, não do disco: `retrieve.grafo` lê os chunks que já
estão no SQLite. Duas consequências, e a primeira decidiu a fase.

**Reconstruir o grafo inteiro custa 30 segundos.** Contra 39 h de reindexação. Numa
fase cujo trabalho *é* refinar regras de extração, isso é a diferença entre cinco
iterações e nenhuma — e foram necessárias cinco, todas abaixo.

**O laço do indexador não foi tocado.** `docs/colaboracao.md` dá esse laço ao outro
setup, e mexer nele exigiria PR separado e coordenação. Sair de graça foi
consequência do desenho, não sorte.

O custo é o grafo poder ficar velho em relação ao índice. `--estado` reporta a
diferença, e `neighbors` avisa explicitamente quando o grafo está vazio — sem
isso, "grafo nunca construído" e "documento sem ligações" seriam a mesma resposta,
e ninguém investiga o que parece legítimo.

## Cinco correções, e todas eram a mesma classe de defeito

Nenhuma apareceu no teste unitário. Todas apareceram ao rodar no acervo real e
**olhar a distribuição**, e todas eram "o mesmo identificador escrito de outra
forma não liga" — o defeito mais insidioso possível aqui, porque cada grafia
produz sua própria aresta, igualmente plausível, e nada parece errado.

| Achado | Efeito antes da correção |
|---|---|
| `ISO 42001:2023` ≠ `ISO 42001` | mesma norma, duas arestas, documentos não se ligavam |
| `ISO 14.001` → `ISO 14` | o ponto de milhar truncava o número; 15 documentos órfãos |
| `ISO-420012023` (ano colado) | a expressão **falhava inteira**; o documento da norma ficava sem menção |
| `LEI 13.709/2018` ≠ `LEI 13.709` | LGPD partida em 40 + 15 documentos que não se ligavam |
| teto de 25 documentos | cortava a `ISO 42001` (27 docs) — **o caso motivador da fase** |

O último é o mais instrutivo: um limite escolhido no abstrato, com raciocínio
plausível ("1,5% do acervo já é recorrente demais"), excluía exatamente a aresta
que a fase existia para construir. Só a distribuição real desfaz esse tipo de
erro.

E uma assimetria vale registrar: para **norma promulgada** o ano é decoração
(a LGPD é a Lei 13.709 com ou sem `/2018`), mas para **projeto de lei** o ano é
identidade — a numeração reinicia a cada ano, e `PL 2338/2023` não é `PL 2338/2019`.
A regra segue a numeração legislativa, não a conveniência de unificar.

## Nome de arquivo é fonte de identificador, e o achado que decorre disso

O documento que a pergunta multi-hop precisa é um **PDF digitalizado**: 61
páginas, `status: vazio`, zero chunks, nenhuma linha de texto extraível. Extrair
identificador só do texto o deixaria permanentemente fora do grafo.

O nome do arquivo resolve, e não é remendo: neste acervo o nome é o sinal mais
forte que existe — o baseline por nome de arquivo sozinho tira recall@1 = 0,55
(F0). Varrer o caminho além do texto resgata **todo** documento digitalizado, e
custa nada.

Disso saiu o desempate que consertou o resultado. Com 27 documentos citando a
`ISO 42001`, todos empatavam no mesmo peso e a ordem saía **alfabética** —
exercícios de um curso que mencionam a norma de passagem vinham antes do próprio
texto da norma. Nome e corpo não são o mesmo tipo de evidência:

- identificador no **nome**: este documento **é** o assunto
- identificador no **corpo**: este documento **fala sobre** o assunto

Entrou como categoria e não como multiplicador, porque não existe número
justificável para "quantas vezes melhor" é ser o documento canônico. E entrou
**como desempate, não como prioridade**: um código de contrato citado por dois
documentos é evidência mais específica que ser o canônico de uma norma que meio
acervo cita. A ordem dos dois critérios foi um defeito real, pego por teste.

## A distribuição, que é o que faz a ferramenta valer

7.109 identificadores distintos em 383 documentos. Dos que aparecem em mais de um
documento — os únicos que viram aresta:

| Documentos que citam | Identificadores | Leitura |
|---|---:|---|
| 2–5 | 363 | as arestas fortes |
| 6–10 | 30 | |
| 11–20 | 19 | |
| 21–30 | 9 | norma em discussão num projeto |
| 31–54 | 14 | certificação que a empresa **tem**, e o CNPJ dela própria |
| 55+ | 0 | |

O peso da aresta é `1/documentos` — a mesma intuição do IDF, aplicada a aresta em
vez de termo. Sem isso a ferramenta seria inútil e não por pouco: o CNPJ da
própria empresa aparece em 48 documentos e ligaria todo contrato a todo contrato,
com procedência correta e relação nenhuma. É o pior tipo de resposta errada,
porque não há como o cliente desconfiar.

**O que o teto separa, e o nome confirma:** abaixo de 40, norma em discussão;
acima, certificação que a empresa possui e cita em todo documento de ESG. Não é
fronteira perfeita — uma norma de qualidade em 37 documentos passa e é fraca — e é
por isso que o peso continua sendo a defesa principal: 1/37 perde de longe para
1/2.

## Um achado que ficou registrado em vez de resolvido

**90% dos identificadores extraídos são número de processo, e vêm de dois
arquivos.** Duas planilhas de contencioso concentram 6.567 das 8.503 menções.
Ficam porque não fazem mal: quase todo processo é citado por um documento só, e
identificador em um documento só não gera aresta nenhuma. Onde duas planilhas
listam o mesmo processo, a aresta é legítima.

Mas mostra o limite do corte por chunk: o teto de 40 identificadores por chunk
não pega uma planilha de milhares de linhas, porque ela se espalha em milhares de
chunks e nenhum deles passa do teto. Um teto **por documento** pegaria — e não foi
acrescentado porque não há evidência de dano, e um limite a mais sem dano medido é
complexidade paga sem retorno.
