---
name: segundo-cerebro-notebook
description: Aplicar as responsabilidades do notebook ao trabalhar com o acervo corporativo e avaliações locais; não deduzir hardware pelo nome do agente.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Responsabilidades do notebook

Confirme setup, branch e pacote pela sessão e pela seção vigente de `docs/colaboracao.md`. O nome Claude/Codex não determina a máquina. Não afirmar ausência de GPU sem diagnóstico.

Leia primeiro a regra de ouro. Use a tabela de donos vigente para ranking, eval e dados corporativos; CUDA e pipeline não mudam de dono porque a máquina tem placa. Mudança conjunta de ranking e pipeline se divide em contratos e PRs.

Não executar pull automático; siga o procedimento compartilhado para inspecionar e isolar a branch. Escolha apenas a skill operacional necessária. Estado, métricas e fila não são copiados para esta skill.

Dourado corporativo é regressão, não autoridade única para novos padrões. Relatórios detalhados, configs e vocabulário real nunca entram no Git. Dê ao outro executor fixtures sintéticas e agregados saneados, nunca dados privados.

Saída inicial: setup confirmado ou ainda desconhecido, branch, escopo e benefício ao usuário. Handoff: SHA, paths, testes, pendências e próxima ação. Não comunicar a terceiros sem autorização.
