---
name: pacote
description: >
  Abrir um pacote de trabalho neste repositório — as três perguntas da regra de
  ouro, efeito mínimo, critério de encerramento e classe generalizada, antes de
  criar a branch. Use quando for começar qualquer trabalho novo: pacote, ideia de
  melhoria, "vamos otimizar X", varredura de peso, parser novo, hipótese de
  ranking, ou quando o usuário pedir o próximo passo. Gatilhos: novo pacote,
  próximo passo, começar, hipótese, varredura, otimizar, melhorar recall, ajustar
  peso, abrir branch, F4, F6, E1, Q1.
---

# Antes de abrir a branch

Este repositório tem uma coisa rara: um histórico de trinta ablações datadas e
uma cultura de "sem número não entra". E tem um custo medido: **34 commits acima
de 500 linhas**, quatro ramos órfãos de reescrita, e uma latência de detecção de
defeito que já foi de **nove dias e 58 commits**. Os dois lados vêm da mesma
causa — pacote que começa antes de estar definido cresce até virar o que couber.

Não escreva código antes de responder o que segue. Responder "não sei" é resposta
válida: ela **adia** o pacote, não o libera.

## 1. As três perguntas — [`docs/regra-de-ouro.md`](../../../docs/regra-de-ouro.md)

Elas têm precedência sobre a fila do `ROADMAP.md`, sobre os dossiês e sobre o
guia de engenharia. Em conflito, elas vencem, e quem discordar muda **aquele**
arquivo primeiro.

1. **Que defeito isto conserta para quem instala amanhã, numa base que nunca
   vimos?** Se a resposta só existe em termos do nosso acervo ("sobe o MRR de
   reunião"), o pacote é **de laboratório**: pode entrar, declarado como tal,
   atrás de qualquer item de produto.
2. **Qual é o efeito mínimo que faria valer, e o instrumento vê esse efeito nessa
   fatia?** Número e fatia declarados **antes** de olhar a tabela. Efeito esperado
   menor que o ruído medido da fatia ⇒ **não se mede**: registra-se a conta e
   encerra.
3. **Se der empate, o que a gente faz?** A única resposta aceita é *encerra e
   registra*. "Meça mais" é a fase inteira outra vez.

## 2. O contrato, preenchido no cabeçalho do pacote e no corpo do PR

O formato está no `ROADMAP.md`, seção "Pacotes". Os campos que mais reprovam:

| Campo | O que reprova |
|---|---|
| **Paths** | lista fechada. Dois pacotes só voam juntos se as listas não se intersectam |
| **Efeito mínimo** | declarado antes. Sem ele não há varredura — regra 11 |
| **Orçamento** | uma medição por hipótese. Segunda passada precisa de instrumento novo ou acervo novo, **não** de outra grade |
| **Critério de encerramento** | empate encerra, com "hipótese refutada" no doc |
| **Classe generalizada** | qual teste ou método passa a pegar a **classe** sozinho. Sem esta linha o PR não fecha — regra 12 |

## 3. As armadilhas que já custaram um pacote aqui

Cada uma é um erro real, com o arquivo onde ficou o laudo. Leia a linha que
descreve o seu caso antes de decidir que ele é diferente.

- **A alavanca age sobre uma população e o efeito foi medido em outra.** O dano de
  nome em reunião era real (−0,089); 11 dos 12 documentos que causavam o dano eram
  de escritório, e a alavanca zerava o peso nos **candidatos de reunião**, que são
  as vítimas. `F4-P.1` fechou como *hipótese mal especificada*, não como
  refutação. — [`docs/ablacao-f4p1-nome-por-fonte.md`](../../../docs/ablacao-f4p1-nome-por-fonte.md)
- **A fatia que decidiria o pacote tinha n=0 e ninguém conferiu.** `retrieve/fonte.py`
  classificava `.vtt` como reunião enquanto `.vtt` estava fora de
  `supported_extensions()`. A declaração dizia n≈100. A medição teria fechado o
  pacote cumprindo todas as regras. — [`docs/fatia-reuniao-invisivel.md`](../../../docs/fatia-reuniao-invisivel.md)
- **Ganho medido num acervo só não vira `[padrao]`.** Vira `[[base]]` desligada por
  padrão, prior do autotune, ou espera o segundo acervo. Exceção declarada: custo
  zero por consulta **e** estruturalmente independente de acervo — foi o caso de
  famílias e glossário, e não é o caso de reranking, que custa 6,9×.
- **Porta refutada não volta.** A porta 3 já foi varrida três vezes (13/08, tabela
  da F2, `C3.a`). A quarta precisa de acervo novo, não de outra grade.

## 4. Antes de escrever a primeira linha

- [ ] `docs/regra-de-ouro.md` lido, e as três perguntas respondidas por escrito
- [ ] `docs/colaboracao.md` §1 conferido: os paths que vou tocar são meus
- [ ] `git log --oneline -5` e a branch conferida **agora** — o usuário funde PRs
      em paralelo e a árvore muda no meio da sessão
- [ ] Efeito mínimo e fatia escritos **antes** de rodar qualquer coisa
- [ ] A linha de "classe generalizada" já esboçada: se eu não sei que teste vai
      pegar a classe, ainda não entendi o defeito

Se o pacote é de refatoração ou de qualidade e não mede recuperação, os campos de
efeito mínimo e encerramento não se aplicam — mas **a classe generalizada sim**, e
a régua passa a ser a suíte: mesma contagem de falhas antes e depois, e o que
mudou de estrutura tem de estar provado por um teste que não existia.
