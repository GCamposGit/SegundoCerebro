---
name: entregar
description: >
  Fechar o trabalho neste repositório — commit atômico, branch, e o PR como link
  de compare (não há `gh` no notebook). Use ao terminar uma mudança, ao pedir
  commit, ao abrir PR, ou antes de entregar. Gatilhos: commit, commitar, PR, pull
  request, abrir PR, fechar o pacote, entregar, subir, push, branch, merge.
---

# Entregar

## Antes de tocar em `git`

1. **Confira a branch agora.** `git status -sb`. O usuário funde PRs em paralelo e
   deixa a árvore em `main`; a branch em que a sessão começou pode não ser a de
   agora.
2. **Commite só os seus paths.** Pode haver outra sessão editando esta mesma
   árvore. Nada de `git add -A` e nada de `git commit -a` — liste os arquivos.
3. **Confira o que foi de fato preparado** contra a lista que você pretendia:
   `git status --short | grep -v '^??'`. Arquivo esquecido no `git add` produz um
   commit que descreve mudança que ele não contém.
4. **Nunca em `main`.** Cada lado trabalha na sua branch e entra por PR.

## O commit

Um commit por mudança lógica. **34 commits deste repositório passam de 500
linhas** — commit grande é PR que ninguém revisou de verdade, e é uma das oito
classes de erro recorrente medidas aqui.

A mensagem diz **o quê** e **por quê**, e 29% das mensagens amostradas do
histórico só diziam o porquê — obrigando a abrir o diff para saber o raio de
alcance. Escreva as duas coisas:

```
<area>: <o que mudou, em uma linha, no imperativo ou no presente>

<o defeito ou o motivo, com numero e data quando houver>

- <mudanca 1, com arquivo>
- <mudanca 2>

Classe generalizada: <que teste ou metodo passa a pegar a classe sozinho>

Suite: <antes> -> <depois>.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

Nunca `--no-verify`, nunca `--no-gpg-sign`. Se um hook reprova, o hook está certo
até prova em contrário.

## Antes do commit final

- [ ] `py -m pytest tests/ eval/ -q` — mesma contagem de falhas de antes, ou menos
- [ ] `py -m ruff check src tests eval` e `py -m pyright src` limpos
- [ ] Nenhum nome real do acervo em arquivo versionado (`tests/test_saneamento.py`
      confere, mas a lista dele é local e pode estar magra — olhe o diff)
- [ ] Nenhum `docs/metricas-*.md` ou `docs/censo*.md` novo entrando no Git

## O PR

**Não há `gh` CLI neste notebook.** O PR se entrega como **link de compare
pré-preenchido**, nunca como `gh pr create`:

```
https://github.com/GCamposGit/SegundoCerebro/compare/main...<branch>?expand=1
```

O corpo segue `.github/PULL_REQUEST_TEMPLATE.md`, e os campos que reprovam são os
mesmos do contrato de pacote: **Serve base desconhecida**, **Hipótese**, **Efeito
mínimo**, **Orçamento**, **Critério de encerramento**, **Classe generalizada**.
Sem a última linha o PR não fecha.

Se a mudança mexeu em ranking, o corpo traz número **antes e depois**, com corpus,
máquina e data — e a cobertura do dourado ao lado da tabela.

## Push e merge

- Push só quando o usuário pedir. Se estiver em `main`, crie a branch antes.
- Merge é do usuário. Você entrega o link.
- **Depois de um merge, releia a árvore.** A classe "merge paralelo reintroduz API
  antiga" apareceu duas vezes aqui, a segunda **sete minutos** depois da primeira:
  o outro lado trouxe um call site com a assinatura velha e a guarda cobria só
  metade da superfície.

## Branch

Nome curto que diz o pacote: `f4-d-cobertura-no-relatorio`, `q1-ci-lint`. Um
pacote, uma branch, uma lista de paths fechada.

**Não deixe ramo órfão.** Há quatro no repositório, restos de reescrita de
história com backup manual antes de cada rebase. Se precisar de backup antes de um
rebase, diga ao usuário — não crie a branch e a esqueça.
