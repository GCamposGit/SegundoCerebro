# Segundo Cérebro Factory Rules

Estas regras valem para qualquer agente ou harness que opere neste repositório.

1. Leia `MISSION.md`, `AGENTS.md`, `docs/regra-de-ouro.md` e a seção vigente de donos em `docs/colaboracao.md` antes de alterar código.
2. Preserve a finalidade para base desconhecida. Evidência de um único acervo não autoriza mudança no padrão, salvo a exceção registrada na regra de ouro.
3. Respeite ownership e paths “um de cada vez”. Mudanças de ranking e do laço do indexador são pacotes e PRs separados.
4. Nunca trabalhe nem faça commit em `main`. Use uma branch `codex/<pacote>` criada de uma referência limpa e preserve alterações de terceiros.
5. Nunca leia índices, corpus ou configurações reais durante testes. Use `tmp_path`, fixtures sintéticas e dados publicáveis.
6. Nunca versione segredos, `config.toml`, índices, pesos, caches, perguntas ou relatórios privados. Falhas externas devem produzir erro estruturado sem vazar credenciais.
7. A validação padrão é `python core/harness/runner.py --quick`. Antes da entrega, execute também `python -m pytest tests/ eval/ -q`, `python -m ruff check src tests eval` e `python -m pyright src`.
8. Um harness só pode declarar sucesso com `[HARNESS_PASS]`, ao menos uma checagem executada e nenhum marcador de falha.
9. Preserve domínio e I/O separados. O caminho MCP e o painel consomem serviços testáveis; regras de negócio não ficam presas a handlers de UI.
10. `MISSION.md`, `FACTORY_RULES.md`, `AGENTS.md`, a regra de ouro, o harness e os workflows são governança protegida. Mudanças exigem pacote explícito e revisão humana.
11. Auto-merge, agendador, deploy e gastos externos permanecem desativados durante o nível 2. Ativação exige primeira volta manual verde e autorização explícita.
12. `.agents/skills/` é o catálogo canônico da Dark Factory. `.claude/skills/` mantém a cópia compatível, sem substituir as skills próprias do SegundoCerebro.
13. O runtime e as skills da Dark Factory são snapshots. Atualizações só entram por novo commit revisado, atualização de `.factory/darkfac.lock.json` e validação completa; symlink ou dependência no checkout `C:\dev\DarkFac` é proibido.
14. Operar o SegundoCerebro nunca autoriza modificar o repositório DarkFac. O commit de origem registrado no lock é somente leitura.

