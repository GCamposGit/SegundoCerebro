# F4 — `Meetings/`: 1.009 documentos, 169 reuniões

> **Estado: levantamento do corpus, sem medição ainda.** A passada de indexação
> está em curso e as métricas entram aqui quando ela fechar. As tabelas por
> pergunta ficarão nos `docs/metricas-f4-meetings-*.md`, que não vão para o Git
> porque relatório por pergunta cita nome de arquivo do acervo.

Este é o número que o fechamento do email deixou pendurado: `iter_files` enumera
2.617 documentos, o registro tinha 1.608, e **os 1.009 que faltavam estavam todos
em `Meetings/`** — nem um único documento de outra pasta fora do índice. Depois
desta passada, índice e corpus enumerado são o mesmo conjunto, e a frase "o
corpus é 63% maior que o índice" deixa de valer.

## O que `Meetings/` é

Não é uma pasta de documentos. É a **saída do projeto irmão** de gravação de
reuniões, e cada reunião deixa lá entre cinco e sete arquivos. Contar arquivos
sem olhar o papel de cada um foi o que fez a estimativa da fase parecer "mais
mil documentos de conhecimento".

| Papel | n | formato | o que é |
|---|---:|---|---|
| conteúdo | 539 | `.txt` | transcrição, diarizada e conciliada — **três renderizações do mesmo áudio** |
| andaime | 280 | `.txt` | `context` e `context_prompt`: o prompt que o aplicativo monta, não a reunião |
| relatório | 177 | `.pdf` | o relatório renderizado da reunião — 381 MB |
| notas | 11 | `.pdf` | notas pessoais |
| banco | 2 | `.db` | banco do próprio aplicativo, sem parser |

**169 reuniões distintas**, 1.009 arquivos: 6,0 arquivos por reunião.

## Três medidas de redundância, todas antes de gastar a passada

**1. 263 duplicatas exatas.** Há duas pastas de reuniões, `Meetings/` e
`09. Meetings/`, e 263 arquivos aparecem nas duas com o mesmo nome e o mesmo
tamanho — 186 MB. Não é o caso de "arquivo movido" que a reconciliação trata por
sha256: as duas cópias existem ao mesmo tempo, e cada uma vira documento próprio
competindo na fusão com a outra.

**2. Três renderizações por reunião.** `transcript`, `diarized` e `reconciled`
(ou `Transcricao`, `Diarizada`, `Conciliada` — o aplicativo mudou a convenção de
nome no meio do acervo) são o mesmo áudio escrito de três formas. Para uma
pergunta sobre o que se decidiu numa reunião, as três respondem, e as três
ocupam lugar no top-10.

**3. Os 177 PDFs são 100% redundantes com um `.txt` já do conjunto.** Isto foi
verificado, não presumido: casando pelo identificador de reunião que o nome do
arquivo carrega, **188 de 188** PDFs pertencem a uma reunião cuja transcrição
está entre os 539 `.txt`. E são 381 MB dos 397 MB da pasta, o que em coeficiente
medido dá **entre 5 h e 11 h** de indexação contra **13 min** dos 819 `.txt`.

Daí a ordem da passada, que é a mesma lição da entrega anterior: partir por custo
e medir no meio. O caro deste bloco não é 96% do trabalho por 96% do valor — é
96% do trabalho por conteúdo que o barato já traz.

## O que a passada mediu de custo, e corrige a estimativa

A semente do estimador dá 50 s/MB para extensão sem coeficiente medido, o que
prometia 13 min para os 819 `.txt`. **Medido: 496 s/MB** — praticamente o
coeficiente do DOCX (522), porque um megabyte de transcrição é texto puro e vira
centenas de trechos. São **31 trechos por transcrição**, o que projeta ~25.000
trechos novos: +27% no índice para 169 reuniões.

E há um segundo erro de modelo embaixo do primeiro, que é o que faz a barra pedir
"67 dias": com 819 arquivos de ~19 kB, o custo é dominado por **overhead por
documento** (24,5 s cada), não por byte. Byte ponderado é o preditor certo para
um acervo de PDF e DOCX grandes; não é para uma pasta de milhares de arquivos
pequenos, e as duas contas divergem por um fator de quatro.

> Achado para `docs/estimativa-de-indexacao.md`, que é do outro setup
> (`docs/colaboracao.md` §1) — registrado aqui, não corrigido lá.

---

# O corte por papel, medido em 24/08/2026

A passada de `.txt` ficou pausada em **234 de 833** documentos, e o próximo passo
não era continuar: era cortar a fila por papel. O corte está medido abaixo, e a
medição desfez a regra óbvia.

Chaves das contagens, porque elas divergem das do levantamento acima e a
divergência é informação: **193 pastas** de reunião nas duas árvores, mas
**147 identificadores** `AAMMDD_HHMMSS` distintos no nome dos arquivos. A mesma
reunião aparece em mais de uma pasta — é a duplicata entre as duas árvores vista
por outro ângulo. As contagens por reunião abaixo usam o identificador; as de
arquivo, a enumeração de `iter_files`.

## O que a distribuição por reunião desfez

A regra óbvia era "das três renderizações do mesmo áudio, guardar a conciliada e
descartar as outras duas". Ela perde reunião inteira:

| Papéis presentes na reunião | reuniões |
|---|---:|
| andaime + transcript + diarized + reconciled + relatório | 126 |
| enhanced + transcript + relatório | 20 |
| transcript + relatório | 14 |
| andaime + transcript + diarized + reconciled | 13 |
| os anteriores + notas pessoais | 11 |
| só andaime | 3 |
| cauda (7 combinações, ≤ 2 reuniões cada) | 9 |

- **144** reuniões têm algum `.txt` de conteúdo.
- **32** delas não têm `reconciled`/`Conciliada` — o aplicativo mudou de
  convenção duas vezes, e há uma quarta renderização (`enhanced`) que o
  levantamento anterior não separava.
- **15** têm exatamente **uma** renderização, e é `transcript`.

Cortar `transcript` e `diarized` por padrão de nome apagaria essas 15 reuniões do
acervo. É a mesma classe de erro do teto de 25 documentos por identificador na
entrega do grafo: limite escolhido no abstrato que exclui justamente o caso
motivador. **Só olhar a distribuição real acha.**

Consequência: a escolha entre renderizações **não é** exclusão por nome. É
preferência por reunião — `reconciled` > `enhanced` > `diarized` > `transcript`,
a melhor que existir.

> **Retratado em 24/08/2026.** Essa ordem de preferência está **errada**, e o
> pressuposto de "três renderizações do mesmo áudio" também. Medido em
> [`docs/dourado-cobertura.md`](dourado-cobertura.md): a `transcript` tem mais
> texto em 128 de 144 reuniões, a preferida por nome fica abaixo de 60% do texto
> da mais completa em 56 delas — e ainda assim **4 de 11 perguntas novas só são
> respondíveis pela conciliada**, porque ela é outra passada de transcrição, mais
> fiel, não um resumo. Nenhuma renderização pode ser descartada por regra. A
> família continua valendo; o mecanismo é **colapsar irmãs no ranking**, com
> todas no índice. Isso é a forma de uma **família de versão**, que já existe
em `retrieve/familias.py` e custa zero por consulta; entra como braço medido no
dourado corporativo, não como corte de indexação. As três renderizações ficam
indexadas: são 540 arquivos de texto puro, o barato desta pasta.

## O corte que entra, e por que não precisa de código novo

Sobram dois papéis que são exclusão por nome de verdade, porque nenhum deles é
conteúdo de reunião:

| Papel | arquivos | tamanho | por que sai |
|---|---:|---:|---|
| andaime (`context`, `context_prompt`, `Contexto`, `PromptContexto`) | 282 | 3 MB | é o prompt que o aplicativo monta, não a reunião |
| relatório renderizado (`_relatorio.pdf`) | 178 | 381 MB | **130 de 130** reuniões com relatório têm `.txt` de conteúdo — medido |
| banco do aplicativo (`meeting_database.db`) | 3 | 2,6 MB | não é documento, e não tem parser |

São 463 arquivos e 381 dos 400 MB da pasta — as 5 h a 11 h de PDF que o
levantamento projetou.

E a proposta que a §6 de `docs/colaboracao.md` marcava "a validar" — que a
exclusão morasse na configuração da base e não em código do indexador — **já
está implementada**: `[base.exclude].globs` é casado com `fnmatch` contra o
**nome** do arquivo, dentro do único `iter_files` que censo, baseline e indexador
compartilham. Não falta mecanismo; faltava a medição de quais padrões são
seguros. Nenhuma linha de `index/indexer.py` muda, o que também resolve o
conflito de donos.

```toml
[base.exclude]
globs = ["*_context.txt", "*_context_prompt.txt", "*_relatorio.pdf"]
```

O casamento é por nome e insensível a caixa, então `_Relatorio.pdf` e
`_relatorio.pdf` caem no mesmo padrão.

## Duas correções no que a §6 registrava

**A repescagem do legado não vem da versão de parser.** A §6 dizia que os
`.doc`/`.xls` entrariam sozinhos porque `_precisa_indexar` repesca por
`estado.parser != parser`. Medido no registro: **todas** as extensões têm versão
de parser igual à declarada hoje — `.doc`, `.xls`, `.ppt` e `.rtf` foram
registrados com `VERSAO_INICIAL`, o mesmo valor que já estava gravado, e
`.msg`/`.eml` estão em 2 dos dois lados. Quem repesca é o **status**:
`sem_parser` está em `STATUS_PARA_REPESCAR`. O mecanismo funciona, mas é outro,
e a diferença importa porque um parser *corrigido* (não *novo*) precisaria da
versão — e a versão não foi mexida.

**São 7 arquivos, não 10:** 4 `.doc` e 3 `.xls`, todos `sem_parser`. Nenhum
`.ppt` e nenhum `.rtf` no acervo. Os 3 `.xlsb` que aparecem ao lado deles
continuam fora: `.xlsb` não tem parser e não é Office 97–2003.

## O que já está no índice e sai na próxima passada completa

Os 234 documentos da passada pausada deixaram **225** linhas de `Meetings/` no
registro, com 5.417 trechos:

| Papel | docs | trechos |
|---|---:|---:|
| andaime | 79 | 984 |
| reconciled | 57 | 1.243 |
| transcript | 44 | 1.589 |
| diarized | 43 (40 `ok`, 3 `vazio`) | 1.529 |
| relatório | 1 | 72 |
| banco | 1 (`sem_parser`) | 0 |

Os 79 de andaime, o relatório e o banco saem na primeira passada **completa**,
porque `--so-extensao` desliga a reconciliação de propósito e a passada pausada
usava o recorte. São 81 remoções em 1.828 documentos — 4,4%, abaixo da trava de
20%, sem precisar de `--forcar-reconciliacao`.

## O número de antes, e o que ele já mostra

Condição C, acervo corporativo, 24/08/2026. Índice com 1.828 documentos e 97.981
trechos, dos quais 225 documentos e 5.417 trechos são de `Meetings/`.
`hibrido`, sem reranking, com o glossário de teste, 48 perguntas no escopo —
mesma configuração e mesmo `n` da linha de fechamento do email, para poder
comparar. Relatório em `docs/metricas-f4-meetings-antes.md` (gitignorado).

| Passada | recall@1 | recall@5 | recall@10 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| fechamento do email (1.608 docs) | 0,635 | 0,872 | 0,913 | 0,774 | 0,782 |
| com 225 documentos de `Meetings/` | 0,635 | **0,833** | **0,927** | 0,765 | **0,759** |

Um terço da pasta indexado já move a métrica, e move na direção que o
levantamento previu: **recall@1 não muda**, recall@10 sobe 0,014, e o meio da
lista cai — recall@5 −0,039 e nDCG@5 −0,023. É a assinatura de fonte verdadeira
empurrada de ≤5 para ≤10 por vizinhos que respondem igual, que é exatamente o que
três renderizações do mesmo áudio fazem na fusão.

Isso não é motivo para não indexar a pasta: é o número que a regra de família
tem de recuperar, e ele agora existe antes da mudança em vez de depois.

**O corte é neutro para o baseline.** O universo do ranqueador por nome vai de
2.619 para 2.156 documentos e as métricas ficam idênticas — recall@1 0,49, MRR
0,618, nDCG 0,663 na raiz completa. Nenhum dos 463 arquivos cortados vencia
alguma pergunta, o que é a confirmação mais simples de que eles não eram fonte de
nada.

## O depois: a passada fechou

24/08/2026, 02:07. Passada completa, com a regra de papel ligada e
`--pular-planilha-acima-de 40`. **2.129 documentos vistos, 248 processados, 81
removidos pela reconciliação** (1.056 trechos de andaime, relatório e banco), e o
índice em **2.156 documentos, 98.326 trechos** depois da repescagem do legado
(98.154 antes dela).

A reconciliação removeu exatamente o que a previsão dizia — 81 de 1.828, 4,4%,
sem `--forcar-reconciliacao`. Vale registrar que a previsão foi feita antes, com
o mesmo `iter_files` e o mesmo `_precisa_indexar` que a passada usa: 81 remoções,
409 nunca indexados e 16 repescados, contra 81 e 248 processados medidos. A
diferença de 409+16 para 248 é `duplicado`, que o registro conta como processado
sem reembeddar.

**Índice e corpus enumerado agora são o mesmo conjunto:** 2.156 dos dois lados,
zero documentos com parser fora do registro e zero linhas do registro fora da
enumeração. A frase "o corpus é 63% maior que o índice", que veio do fechamento do
email, deixa de valer.

`Meetings/` no índice, depois do corte: **551 documentos, 5.598 trechos**, e só
conteúdo — 189 `transcript`, 179 `reconciled`, 152 `diarized`, 20 `enhanced`, 11
notas pessoais. Zero andaime, zero relatório. E **156 `duplicado`** por sha256
(106 em `09. Meetings/`, 50 em `Meetings/`): as cópias entre as duas árvores
entraram sem reembeddar, que é o que a fila em ondas prometia.

### O número

Condição C, corporativo, 24/08/2026. `hibrido`, sem reranking, glossário de teste,
48 perguntas no escopo. `docs/metricas-f4-meetings-depois.md` (gitignorado).

| Passada | docs | recall@1 | recall@3 | recall@5 | recall@10 | MRR@10 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fechamento do email | 1.608 | 0,635 | — | 0,872 | 0,913 | 0,774 | 0,782 |
| um terço de `Meetings/` | 1.828 | 0,635 | 0,802 | 0,833 | 0,927 | 0,765 | 0,759 |
| **`Meetings/` completo, cortado** | **2.156** | **0,656** | 0,792 | 0,833 | 0,927 | 0,771 | 0,764 |

A última linha foi medida **duas vezes**, antes e depois de a repescagem do legado
entrar com 172 trechos, e deu **exatamente igual** nas nove colunas. Não é
coincidência a favor: é a confirmação direta de que o dourado não alcança `.doc`
nem `.xls`, dito na seção seguinte.

Fechar a passada **desfez parte da queda do meio do caminho** e ainda ganhou o
topo: recall@1 sobe 0,635 → **0,656**, MRR 0,765 → 0,771, nDCG@5 0,759 → 0,764.
Contra o fechamento do email, o saldo de indexar a pasta inteira é recall@1
**+0,021** e recall@10 **+0,014**, contra recall@5 **−0,039** e nDCG@5 **−0,018**.

**A inspeção por pergunta diz de quem é o ganho, e ele é limpo:** os acertos em
primeira posição vão de 32 para 33, **`g001` ganha o 1º lugar e nenhuma pergunta
o perde**. `g036` continua sendo a única sem acerto no top 20, como antes — é o
caso já declarado "não é de ninguém" na §6.

Ou seja: a pasta paga em recall@1 e custa em recall@5, e o custo é o que a regra
de família tem de recuperar. O número de antes (0,872 de recall@5 antes de
qualquer transcrição) é o teto a perseguir, e agora ele está escrito.

### O que ainda não é medível

O corte por papel e a passada não movem o legado no dourado, e é melhor dizer
por quê do que apresentar um número vazio: **o conjunto dourado não tem nenhuma
fonte `.doc`, `.xls`, `.ppt` ou `.rtf`.** As 51 perguntas apontam para `.docx`
(29), `.pdf` (23), `.xlsx` (4), `.md` (3), `.msg` (2) e `.pptx` (2). A §6 pedia
"medir a repescagem do legado no dourado corporativo"; a resposta honesta é que
essa medição é vazia até existir pergunta cuja fonte seja um desses formatos —
e escrever a pergunta é o passo que falta, não rodar o eval.

## A repescagem do legado, medida em arquivo de verdade

A §6 dizia que os `.doc`/`.xls` "entram sozinhos na próxima passada". Entraram — e
o resultado é assimétrico de um jeito que só arquivo real mostra:

| Formato | arquivos | `ok` | trechos | resto |
|---|---:|---:|---:|---|
| `.doc` | 4 | **1** | 3 | 3 `vazio` ("nenhum texto extraível") |
| `.xls` | 3 | **2** | **172** | 1 `erro` |

O caminho de bytes puros do `.doc` extraiu 3 trechos de 1 de 4 arquivos; o `.xls`
por `xlrd` extraiu 172 trechos de 2 de 3.

> **Corrigido em 24/08/2026, depois de olhar o conteúdo:** os 3 trechos do `.doc`
> **não são texto**. São bytes decodificados como caracteres largos — mojibake
> CJK dentro do índice e do FTS. Contar trecho não é conferir extração, e a
> diferença é entre "extração fraca" e "ruído indexado". Ver
> [`docs/dourado-cobertura.md`](dourado-cobertura.md). Mesma família de formato, mesma decisão
de "sem COM", resultados a uma ordem de grandeza de distância. **Três de sete
arquivos de Office legado viraram conteúdo**, e é o primeiro número real que essa
prioridade tem.

> Achado para o dono de `ingest/parsers/ole_texto.py` e `sheets.py`
> (`docs/colaboracao.md` §1) — registrado aqui, não corrigido lá. Dois pontos:
> o `.doc` por bytes acerta 1 de 4 neste acervo, e `xlrd==1.2.0` levanta
> `AssertionError` **sem mensagem** num `.xls` real, o que é o pior diagnóstico
> possível para quem for depurar.

### E a lição operacional, que não é do parser

Os três `.xls` estavam como `erro: ModuleNotFoundError: No module named 'xlrd'`.
O `xlrd==1.2.0` **está** declarado no `requirements.txt` desde a entrega do legado
— só não estava instalado nesta máquina. O `import xlrd` é dentro da função, então
nada falha ao subir: o sintoma aparece um documento por vez, como `erro` no
registro, e a passada segue verde.

É a mesma forma da lição de 19/08 sobre `schtasks`: **o teste que passa não prova
que a máquina faz.** Aqui o teste nem chega perto — a suíte lista `.xls` entre as
extensões suportadas sem nunca abrir um. Um `pip install -r requirements.txt`
depois de puxar `main` resolveria; um teste marcado que abra um `.xls` mínimo de
verdade evitaria a próxima vez.
