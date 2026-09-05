---
name: entregar
description: Concluir uma alteração autorizada deste projeto com validação, commit de escopo e estado de publicação verificável; não confundir compare com PR.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Entregar com estado verificável

1. Confira branch, SHA, operação Git em andamento e diff agora. Nenhum commit em main. Preserve trabalho de terceiros.
2. Reuse a validação correspondente ao diff atual: comandos, saída final, falhas/skips e limitação de ambiente. Não use apenas mesma contagem de falhas; falha diferente é regressão nova.
3. Revise saneamento e links. Stage somente paths do pacote, usando `git add -- <paths>`. Confira `git diff --cached --stat` e `git diff --cached --check` antes de commit.
4. Mensagem informa problema, comportamento e validação. Não invente coautoria, versão de agente ou métrica. Não bypassar hooks ou proteção.
5. Publicação segue autorização vigente. Quando houver autorização, descubra CLI/API/navegador autenticado; não fixe que uma máquina tem ou não tem `gh`. Reuse PR existente da branch; novo PR segue o template do repositório.
6. Confirme SHA remoto, número e URL `/pull/N`, head/base e estado do PR por leitura real. Compare é apenas página de comparação. Informe checks pendentes sem declarar merge-ready.

Não fazer merge nem apagar branches por automatismo. Falta de credencial é bloqueio de publicação, não motivo para perder a entrega local. A resposta final distingue arquivos prontos, commit local, push, PR e checks; não promete um estágio que não foi executado.
