# `F4-P.1` — peso de nome por tipo de fonte: hipótese **mal especificada**

**Data:** 27/08/2026 · **Máquina:** notebook corporativo i7-1355U (2P+8E), Windows 11 ·
**Camada 2:** `index-e1`, corpus sintético do `E1`, semente 42, `--n-por-fatia 100`,
3.630 documentos / 4.328 chunks · **Camada 1:** índice corporativo, 1.900 documentos ·
**Caminho medido:** `buscar_chunks` (`--entregue`), os dois braços · **Modelo:**
`e5-large`, sem rerank

## O contrato, como estava declarado

| Campo | Valor |
|---|---|
| Hipótese | zerar o peso do ranqueador de nome **para o documento candidato do grupo `reunião`**, mantendo 0,5 nos demais, melhora a fatia `reunião` sem derrubar o agregado |
| Efeito mínimo | fatia `reunião` da camada 2 (n≈100), Δ pareado de MRR@10 **≥ +0,05** com IC95 que não cruza zero |
| Orçamento | **uma** medição, sem grade |
| Encerramento | empate no Δ pareado **encerra** o pacote com "hipótese refutada" |

## O que a medição deu

`py -m eval.comparar --config config.e1.toml --base e1 --antes hibrido --depois hibrido
--nome-por-fonte-depois --entregue`, 2.119 perguntas no escopo, fatia `reunião` com
**n=100** e 100 de 100 fontes indexadas (a `F4-T` fechou isso no mesmo dia).

**Todas as células, em todos os recortes: `+0.000 [+0.000, +0.000]`.** Intervalo de
largura zero, não estreito — nenhuma pergunta mudou de métrica.

Pela regra declarada isso é empate, e empate encerra o pacote com "hipótese
refutada". **Não é o que este documento registra**, e a razão não é gosto.

## Por que "empate" seria a conclusão errada

Zero exato não é ruído: é ausência de manipulação. Três verificações, nesta ordem,
porque cada uma elimina uma causa diferente:

**1. A bandeira chega ao recuperador.** Instrumentando os dois braços que o
`eval.comparar` monta de verdade:

| braço | `nome_por_fonte` | `peso_do_nome` de um documento de reunião |
|---|---|---:|
| antes | `False` | **0,50** |
| depois | `True` | **0,00** |

Não é defeito de encaminhamento. Os objetos diferem.

**2. O mecanismo age — em outros documentos.** Em 40 perguntas cujas fontes são de
grupos misturados, a ordem dos documentos muda em **40 de 40** e a posição da fonte
esperada muda em 3.

**3. Na fatia declarada, a variável não existe.** Sondando as 40 primeiras das 100
perguntas que o *harness* classifica como `reunião`:

| corpus | consultas em que o ranqueador de nome pontua **algum** documento de reunião |
|---|---|
| **sintético (camada 2)** | **0 de 40** |
| real (camada 1) | 2 de 11, e nunca o documento certo |

No corpus sintético o ranqueador de nome **não pontua um único documento de
reunião**. Os nomes que o gerador produz — `Ata reuniao ATA-000.txt`,
`Gravacao_2025-03-14_0930.vtt` — não casam com as consultas. Zerar um peso que já
não se aplica a nada não pode mudar nada: **o Δ era zero por construção**.

Confirmado no sentido inverso: das 60 perguntas de reunião testadas, **nenhuma** muda
de posição entre os braços.

> A fatia tem n=100 e a **variável manipulada tem n=0.** É a mesma classe que este
> mesmo pacote encontrou de manhã — quando a fatia tinha n=0 — um nível mais fundo:
> agora a fatia está cheia, e insensível.

## E há um motivo mais forte: a alavanca age nos documentos errados

O que desbloqueou o pacote foi um efeito **real**, medido pela `F4-P` na camada 1:
nDCG@5 de reunião **−0,089 [−0,172, −0,017]**, o único IC da tabela que não cruza
zero. Esse dano existe. A pergunta que ninguém tinha feito é **de onde ele vem**.

No índice corporativo, nas perguntas de reunião em que **ligar** o sinal de nome
piora a posição da fonte esperada, o grupo dos documentos que passam à frente dela:

| grupo do intruso | ocorrências |
|---|---:|
| **escritório** | **11** |
| reunião | 1 |

**92% do dano vem de documentos de escritório promovidos pelo nome.** A hipótese
zera o peso do nome nos candidatos de **reunião** — que são as **vítimas**, não a
causa. A alavanca declarada não alcança o dano que a motivou, e nenhum corpus
melhor conserta isso: é erro de especificação, não de instrumento.

A tensão estava escrita no próprio contrato, e passou: *"o grupo é o do documento
candidato, que é o que se sabe em tempo de consulta — não o da fonte esperada, que
só o dourado conhece"*. O pacote escolheu o grupo do candidato, corretamente, e
**derivou o efeito mínimo de uma fatia definida pelo grupo da fonte esperada**. São
dois conjuntos diferentes de documentos, e a coincidência de nome escondeu isso.

## Veredito

**Hipótese mal especificada. O pacote encerra, e não reabre com outra grade.**

Não é "refutada": refutar exigiria ter medido, e a camada 2 não mediu. Não é
"adiada por instrumento": mesmo com corpus sensível, a alavanca mexe no grupo
errado. O que fica medido e vale para o próximo pacote:

- o dano de nome em perguntas de reunião é **real** e vem de candidatos de
  **escritório** (11 contra 1, camada 1);
- a fatia `reunião` da camada 2 é **insensível** ao peso de nome, e continuará
  sendo enquanto os nomes gerados não casarem com as consultas;
- `PESO_NOME_POR_GRUPO` e `retrieve/fonte.py` ficam no código, exercitados por
  teste e **desligados por padrão** (`NOME_POR_FONTE = False`). São o mecanismo de
  um pacote futuro, não dívida: a definição única de grupo já paga o próprio custo
  servindo o recorte do harness.

**O que um pacote futuro teria de fazer**, para não repetir isto: declarar a
alavanca em termos do **candidato** e derivar o efeito mínimo de uma fatia definida
pelo **mesmo** eixo. "Perguntas cuja fonte é reunião" e "documentos candidatos de
escritório promovidos pelo nome" não são a mesma população.

## A classe, e o que passa a pegá-la (regra 12)

> **Δ zero tem duas causas — empate e insensibilidade — e a regra de encerramento
> só vale para uma delas.** Quando os dois braços devolvem o mesmo ranking em toda
> pergunta da fatia, não houve medição: registrar "hipótese refutada" é concluir do
> que o dado não diz.

Entregue em `eval/comparar.py::_insensivel`, na suíte padrão. O relatório passa a
marcar a célula com `∅` em vez de `➖`, e imprime, em texto:

> `∅` — fatia insensível, e isto não é empate. […] A regra de encerramento **não se
> aplica** aqui — não houve medição do efeito […]. O que falta é instrumento, não
> veredito.

E quando **nenhum** recorte é sensível, um bloco em destaque: *"esta comparação não
mediu nada"*. Conferido contra a fatia real: `docs/metricas-f4p1-fatia-reuniao.md`
sai com `∅` em todas as células.

A checagem é sobre o **ranking recuperado**, não sobre o Δ, de propósito: dois
braços podem trocar documentos fora do alcance da fonte esperada e não mover
métrica nenhuma. Isso é empate de verdade, e a regra de encerramento vale nele.

## Três defeitos achados no caminho, todos generalizados

Nenhum deles era o assunto do pacote; todos apareceram porque a medição foi
conferida antes de ser reportada.

**1. O relatório se explicava com um fato que deixara de ser verdade.** Todo
relatório de `--entregue` imprimia *"o `RanqueadorDeNome` **não participa** deste
caminho"*. Era verdade até a `F4-P` criar `BuscaHibrida._nome_por_chunk`, em
25/08 — dois dias. A `F4-P.1`, cujo assunto **é** o peso do nome nesse caminho,
teria saído com um parágrafo dizendo ao leitor que a medição não media nada. O
comportamento tinha teste; a prosa não tinha. Porta:
`eval/test_entregue.py::test_a_prosa_do_relatorio_nao_pode_contradizer_o_codigo`,
que lê o fonte de `rodar._montar` e reprova se ele negar o que o código faz.

**2. `--entregue` com os defaults quebrava no meio da passada.** `--antes` tem
default `baseline`, que não tem `buscar_chunks`: a passada carregava índice e
modelo, corria até a primeira consulta e morria com `AttributeError`, sem dizer que
o problema era a combinação de bandeiras. `CaminhoEntregue.__post_init__` passa a
recusar na montagem e a nomear o conserto. Classe: **combinação de bandeiras que
não pode funcionar falha na montagem, não no meio da passada.**

**3. O indexador vaza nome de usuário para arquivo versionado.** Indexar a base
`e1` acrescentou ao `.mcp.json` — rastreado, repositório público — uma entrada com
o caminho absoluto do interpretador, contendo o nome de usuário da máquina. Nada
avisa: o arquivo aparece modificado e um `git add -A` o leva. Revertido; guarda
estrutural em `tests/test_saneamento.py`. A guarda que existia depende de uma lista
local e é **pulada** quando ela está vazia — num clone limpo não havia guarda
nenhuma. A nova é de forma, não de vocabulário, e aceita `SEU_USUARIO`, `você`,
`alguém` e `...` como placeholders.

## O recorte que faltava

O contrato exigia a célula `reunião ∩ cross-lingual` e ela não existia: o relatório
trazia os dois eixos como margens separadas. As margens escondem compensação — o
pacote zera o peso do nome no grupo e o nome é justamente a ponte PT↔EN de parte
dele. `Resultado.por_grupo_e_fatia` passa a emitir a interseção, para todo grupo não
vazio, com a célula vazia à mostra dentro de grupo que existe.

## Ressalva de procedência

O arquivo `docs/metricas-f4p1-camada2.md` foi gerado **antes** do conserto (1) e
carrega a frase obsoleta sobre o ranqueador de nome. Os números não dependem dela.
Os relatórios são gitignorados (`docs/metricas-*.md`); o que vale como registro é
este documento.
