# Primeira volta manual — nível 2

Tarefa sintética `DF-LAP-1`. Sem acervo real, sem ranking e sem promoção de autonomia.

## Problema

O bootstrap da Dark Factory (PR #113) entrou em `main`. Faltava uma volta completa, humana no merge, para provar o ciclo TRIAGED → PLANNED → implementação documental → harness → revisão → merge manual.

## Non-goals

- Promover para nível 3, auto-merge ou agendador.
- Alterar ranking, indexador, OCR ou `[padrao]`.
- Substituir skills do Segundo Cérebro em `.claude/skills/`.
- Modificar o repositório DarkFac ou criar symlink para `C:\dev\DarkFac`.
- Enfraquecer o job pytest com retry.

## Plano

1. Registrar `DF-LAP-1` em `.factory/state.json` como `TRIAGED` e promover a `PLANNED`.
2. Marcar `DF-BOOTSTRAP` entregue com PR #113 e SHA `0d055ff`.
3. Versionar este registro. Teste da fila recusa bootstrap ainda `em_execucao`.
4. `python core/harness/runner.py --quick`.
5. `python core/orchestrator/guard.py HEAD` — este pacote não toca governança protegida.
6. Merge manual. Nível 2 permanece.

## Driver de teste

Biblioteca/CLI: `python scripts/verificar_pacotes.py` e `python -m pytest tests/test_pacotes_ativos.py -q`.

## Resultado

Harness `--quick` e o guardrail desta volta ficam no PR. Auto-merge continua desligado.
