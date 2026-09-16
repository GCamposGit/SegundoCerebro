# Segundo Cérebro Mission

## Objetivo

Entregar um servidor MCP local que permita a uma pessoa leiga recuperar documentos de uma pasta desconhecida, no Windows dela, sem geração no servidor e sem API paga por consulta. Cada base mantém índice físico próprio, com procedência verificável em toda resposta.

## Escopo versionado

- `src/segundocerebro/`: domínio, ingestão, indexação, recuperação, MCP e painel local.
- `tests/` e `eval/`: validação determinística com fixtures públicas e corpus sintético.
- `docs/`, `AGENTS.md` e `FACTORY_RULES.md`: decisões, operação e limites da fábrica.
- `.agents/skills/`, `.claude/skills/`, `core/` e `.factory/`: workflows, skills e runtime pinados da Dark Factory.

## Fora do escopo

- Índices, acervo, perguntas, métricas ou configurações privadas da base real.
- Otimização para um único acervo tratada como padrão do produto.
- Geração de texto no servidor ou API paga no caminho de consulta.
- Mudanças de ownership entre Notebook e Desktop sem acordo explícito.
- Deploy, merge automático, agendador autônomo ou gasto externo antes da primeira volta manual validada e de autorização explícita.

## Critério de sucesso

Um clone limpo instala em Python 3.12, executa a suíte padrão sem GPU, modelos ou dados privados, inicia as superfícies públicas e preserva procedência, isolamento entre bases e comportamento seguro diante de pastas desconhecidas.

## Nível de autonomia

Nível 2 durante a calibração: planejamento, implementação, validação e revisão podem ser automatizados; merge e ativação de agendador permanecem humanos. A promoção ao nível 3 exige uma primeira volta manual completamente verde.
