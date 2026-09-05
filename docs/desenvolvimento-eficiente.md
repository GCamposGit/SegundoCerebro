# Desenvolvimento eficiente e verificável

Este procedimento complementa `colaboracao.md`; a regra de ouro continua definindo prioridade. Autorização explícita do usuário prevalece sobre convenções locais. Escopo: desenvolvimento deste repositório, sem alterar configurações pessoais ou skills de plugins.

## Entrada e contexto mínimo

1. Leia `git status -sb`, `git log -1 --oneline` e `git diff --stat`. Registre SHA e alterações preexistentes. Não leia configurações privadas para conhecer o projeto.
2. Leia a regra de ouro, a seção de donos em `colaboracao.md` e apenas a seção do pacote ativo. Consulte história somente para uma decisão específica.
3. Confira o Python disponível: prefira `.venv/Scripts/python.exe` no Windows; use `py` somente depois de verificar versão e dependências. Comandos abaixo partem da raiz do checkout.
4. Use `rg -n` para símbolos e `rg --files` para inventário. Leia produtor, consumidor e teste da fronteira modificada. Uma busca sem resultado não prova ausência: confira nomes alternativos e roadmap.
5. Registre: resultado esperado para usuário, paths, dependências, teste que distingue certo/errado, orçamento de investigação e condição de parada. Correção determinística usa caso reproduzível; não exige inventar MRR ou IC.

## Trabalho concorrente

Um checkout por escritor. Worktree é isolamento de edição, não de índice: testes sempre usam diretórios temporários. Antes de qualquer alteração, confira se há dono ativo dos paths na seção vigente de colaboração. Não inferir dono a partir do nome do modelo ou de ter GPU.

Não executar `git pull origin main` indiscriminadamente dentro de uma branch: primeiro verificar limpeza, branch e operação em andamento. Atualização de referências é leitura remota; integração é operação separada. Em árvore limpa, criar branch `codex/<pacote>` da referência escolhida; em árvore com trabalho alheio, isolar sem carregar nem descartar essas alterações.

Agentes paralelos só quando autorizados e quando houver tarefas independentes. Cada tarefa recebe contrato de entrada/saída, SHA, paths exclusivos, testes e limite de esforço. Um integrador resolve interfaces compartilhadas. Revisão somente leitura não precisa de reserva de edição. Não enviar mensagens a terceiros por inferência.

Handoff mínimo: objetivo; SHA/branch; paths alterados; resultado dos comandos; riscos; próximo passo exato; estado do processo em background (PID, log, comando, início, código final). Nunca incluir corpus, tokens ou configurações privadas.

## Escada de validação

- Durante edição: teste do comportamento afetado. Repetir só após alteração, falha ou suspeita fundamentada de intermitência.
- Antes da entrega: uma suíte padrão final `python -m pytest tests/ eval/ -q`, `python -m ruff check src tests eval` e `python -m pyright src`, com o Python verificado. As skills de revisão e entrega reutilizam essa evidência se SHA e diff não mudaram.
- Docs/skills: verificar frontmatter, destinos de links e scripts; rodar os testes de documentação e saneamento. A suíte final continua sendo a porta de entrega do projeto; não rodar benchmark de ranking em edição de texto.
- `modelo`, `cuda`, `ocr` e `arquivo` ficam fora da suíte padrão por configuração. Rodar somente quando a mudança ou a operação exigir; não chamar ausência de hardware de aprovação.
- Falhas preexistentes: registrar node IDs e mensagens resumidas, comparar identidades de falha e não apenas contagens. Falha nova reprova mesmo se uma antiga sumiu. Nunca enfraquecer teste ou limite para fechar o pacote.
- Type checker verde com diagnósticos desligados é evidência parcial. Não afirmar que todos os tipos foram verificados.

Uma validação guarda comando, SHA, diff, ambiente, duração, código de saída, aprovados/falhas/skips e motivo dos skips. Processo sem resultado final não passou. Verifique PID e avanço do log; PID sozinho pode ser reutilizado. Se morreu, registre interrupção e só reexecute após identificar uma forma de preservar a execução. Não deixe indexação ou benchmark caro órfão.

## Economia e escalonamento

Pacote pequeno e determinístico pode ir para agente mais simples. Arquitetura de identidade, migração de dados, correção estatística e falha sem reprodução exigem revisão experiente. Após duas tentativas de correção sem nova evidência, faça handoff com reprodução e hipóteses descartadas; não reescreva o subsistema por tentativa.

Uma medição por hipótese; insensibilidade não é empate. Meça tempo de execução e retrabalho por pacote; tokens e custo somente quando o provedor expuser valores reais. Menos palavras nas skills é redução de contexto potencial, não prova de economia financeira.

## Entrega e autorização

Confira novamente branch e diff antes de stage. Liste paths explicitamente; inspecione `git diff --cached --stat` e `git diff --cached --check`. Não inclua trabalho alheio. Commit nunca em main. Não invente coautoria ou nome de modelo.

Use os recursos autenticados disponíveis para PR quando publicação estiver autorizada. `gh` ausente não implica API ou navegador ausentes. URL de compare não é PR. Informe separadamente: validado, commit local, publicado, PR aberto, checks e mergeabilidade. Não fazer merge ou apagar branches por rotina sem autorização aplicável. Restrições de permissão devem identificar a ação e a origem; não pedir confirmação de novo para ação já autorizada.
