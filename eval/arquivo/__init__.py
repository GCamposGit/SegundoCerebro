"""Instrumentos de pacote encerrado — reproduzíveis, fora do custo de toda sessão.

O que está aqui mediu uma decisão que **já foi tomada** e não serve a nenhuma
aberta. Não é código morto: `docs/` cita cada um pelo número que ele produziu, e
alguém pode precisar refazer a conta. É código que parou de render leitura, lint
e CI a cada passada.

| Módulo | Pacote | Decisão que ele fechou |
|---|---|---|
| `varredura.py` | F1 | a varredura de 37 pontos que escolheu os pesos da fusão |
| `varredura_fts.py` | `C3.a` | peso da coluna `caminho` no bm25 — hipótese refutada |
| `custo_miracl.py` | `C5.a` | porta de custo do MIRACL — o `pt` não existe no dataset |
| `alarme_externo.py` | `C5.c` | o sucessor da camada 3: `quati-50k` |

`varredura.py` já não tinha **nenhum importador e nenhum teste** — 301 linhas que
o `ruff` e o `pyright` liam a cada PR para guardar um número de 13/08/2026.

**Como rodar mesmo assim:**

```bash
py -m pytest -m arquivo          # os testes daqui
py -m eval.arquivo.varredura_fts --base <id> --out <md>
```

O marcador `arquivo` sai da suíte padrão pelo `addopts` do `pyproject.toml`, no
mesmo desenho de `modelo`, `cuda` e `ocr`: o que exige um recurso que a passada
comum não tem — ali um modelo ou uma placa, aqui uma decisão já encerrada — fica
fora por declaração, não por esquecimento.

**O que não entra aqui.** Instrumento de pacote aberto, mesmo que não rode há
semanas; e instrumento cujo número ainda é citado como piso ou porta. `E5`,
`E1`, `entregue.py`, `com_grafo.py` e `memo.py` continuam em `eval/`.
"""

from __future__ import annotations
