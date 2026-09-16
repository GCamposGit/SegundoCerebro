# Pacote: bootstrap isolado da Dark Factory

## Problema

O SegundoCerebro precisa consumir os workflows e skills estáveis da Dark Factory sem depender do checkout vivo em `C:\dev\DarkFac`, que continua em desenvolvimento paralelo.

## Respostas à regra de ouro

1. **Defeito corrigido para uma base desconhecida:** o processo de desenvolvimento passa a ter gates reproduzíveis e orientação única sem ler o acervo real.
2. **Efeito mínimo observável:** o harness executa pelo menos uma checagem, emite `[HARNESS_PASS]` apenas com todos os passos verdes e a suíte existente mantém o mesmo resultado.
3. **Empate ou falha:** a implantação permanece em nível 2; auto-merge e agendador não são ativados. A falha é registrada e o pacote encerra sem enfraquecer gates.

## Contrato

- **Base:** `e9d283756e962487090ac45228685cf3132d3fe6`.
- **Branch:** `codex/factory-notebook-bootstrap`.
- **Origem pinada:** DarkFac `de6442408427adaaf336a122c6dd7c4dbe2e9311` (`origin/main`).
- **Paths permitidos:** `MISSION.md`, `FACTORY_RULES.md`, `AGENTS.md`, `harness.config.json`, `.gitignore`, `.factory/**`, `.agents/**`, `core/**`, os três documentos Dark Factory em `docs/`, `docs/pacote-dark-factory.md`, `docs/pacotes-ativos.toml`, `.github/workflows/dark-factory.yml`, `tests/test_dark_factory_bootstrap.py` e `tests/test_pacotes_ativos.py`. As skills `00`–`16` ficam só em `.agents/skills/`; `.claude/skills/` conserva as skills do produto.
- **Dependências:** dependências do produto continuam em `requirements.txt`; dependências opcionais do runtime ficam em `.factory/darkfac-requirements.txt`.
- **Teste negativo:** saída vazia não é aprovação e alteração futura de path protegido deve ser detectada pelo guardrail.
- **Recuperação:** reverter o commit deste pacote remove integralmente a integração; o checkout `C:\dev\DarkFac` não participa da execução.

## Primeira volta manual

1. Cadastrar uma tarefa sintética em `.factory/state.json` como `TRIAGED`.
2. Planejar com `02-plan-product-architecture` e promover para `PLANNED`.
3. Implementar uma mudança documental ou fixture sem dados reais com `04-autonomous-piv-loop`.
4. Executar `python core/harness/runner.py --quick`.
5. Revisar com `06-adversarial-review` e executar o guardrail.
6. Manter merge manual. Só propor nível 3 em um pacote posterior, com todos os gates verdes.

## Condição de aceite

- Nenhum arquivo do DarkFac é modificado.
- Não existe symlink ou dependência do checkout irmão.
- O snapshot copiado corresponde ao commit do lock.
- Harness, suíte padrão, lint e tipos ficam verdes.
- Auto-merge e agendador permanecem desligados.

