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
