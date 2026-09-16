# Segundo Cérebro — entrada para agentes

O produto recupera documentos de pastas desconhecidas por MCP, sem geração no servidor e sem API paga por consulta. Cada base tem índice físico próprio.

Leia `MISSION.md`, `FACTORY_RULES.md`, `docs/regra-de-ouro.md`, a seção vigente de donos em `docs/colaboracao.md` e `docs/desenvolvimento-eficiente.md`. Use `CLAUDE.md` como mapa complementar, conferindo estado no código e no Git. Não presumir hardware, identidade de agente ou fase ativa a partir de texto histórico.

Skills próprias do Segundo Cérebro ficam em `.claude/skills/*/SKILL.md` e `.grok/skills/segundo-cerebro-desktop/SKILL.md`. Abra apenas a necessária: `navegar`, `pacote`, `depurar`, `medir`, `revisar`, `entregar`; skills de setup apenas quando esse setup for pertinente. O catálogo pinado da Dark Factory mora em `.agents/skills/` e não substitui as skills do produto. Runtime em `core/` e proveniência em `.factory/darkfac.lock.json`. Nível 2: merge e agendador permanecem humanos.

Revisão e novos pacotes: `docs/revisao-fundamentos-2026-09-04.md` e `docs/plano-fundamentos-execucao.md`. Confira o estado antes de executar; propostas não são funcionalidades entregues.

Nunca ler ou modificar índices/acervo reais em teste; usar fixtures sintéticas e `tmp_path`. Repositório público: não versionar configurações, nomes ou relatórios privados. Nenhum commit em main. Preservar alterações de terceiros.
