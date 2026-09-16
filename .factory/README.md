# Runtime local da Dark Factory

Este diretório mantém o estado e a proveniência da fábrica do SegundoCerebro.

- `darkfac.lock.json` fixa o snapshot consumido. Não há symlink nem leitura automática do checkout irmão.
- `state.json` é a fila local da máquina de estados (template vazio versionado).
- Ledgers, benchmarks e relatórios de máquina ficam gitignorados; nenhum aprendizado do DarkFac foi importado.
- `darkfac-requirements.txt` registra as dependências do runtime separadamente das dependências do produto.
- Skills `00`–`16` ficam em `.agents/skills/`. `.claude/skills/` conserva as skills próprias do Segundo Cérebro.

O projeto opera em nível 2 até a primeira volta manual descrita em `docs/pacote-dark-factory.md` ficar verde. Auto-merge e agendador estão desligados.

