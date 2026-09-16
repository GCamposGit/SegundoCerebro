# Interoperabilidade entre harnesses

O repositório é independente do editor ou do agente. O contrato comum está em `MISSION.md`, `FACTORY_RULES.md` e `AGENTS.md`. Este repositório opera em nível 2: o harness valida; o merge continua humano.

## Clone

```bash
git clone <URL_DO_REPOSITORIO> SegundoCerebro
cd SegundoCerebro
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e . --no-deps
python core/harness/runner.py --quick
python -m pytest tests/ eval/ -q
```

O extra GPU permanece fora desta instalação. Dependências opcionais do runtime da fábrica estão em `.factory/darkfac-requirements.txt` e não entram no caminho de consulta do produto.

## Catálogo de skills

- Antigravity e Codex: `.agents/skills/` (Dark Factory, pinado).
- Claude Code: `.claude/skills/` (skills próprias do Segundo Cérebro). Não copiar as skills `00`–`16` por cima destas.
- Grok e outros harnesses: `AGENTS.md`, `FACTORY_RULES.md` e o harness determinístico.

## Proveniência

O snapshot consumido está em `.factory/darkfac.lock.json`. Não há symlink nem leitura do checkout `C:\dev\DarkFac`. Atualização só entra por commit revisado, novo lock e validação completa.
