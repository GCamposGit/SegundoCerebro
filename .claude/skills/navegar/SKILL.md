---
name: navegar
description: >
  Mapa barato deste repositório — onde cada coisa mora, o que ler para responder
  cada tipo de pergunta, e o que NÃO ler. Use no começo de qualquer investigação
  neste projeto, ao procurar onde algo está implementado, ao retomar contexto, ou
  antes de abrir muitos arquivos. Gatilhos: onde fica, onde está implementado,
  como funciona X aqui, retomar contexto, explorar, entender o código, achar,
  procurar, qual arquivo.
---

# Onde as coisas moram

O repositório tem **45 mil linhas de Python** e **1,3 MB de documentação**. Ler
por varredura queima o contexto antes de chegar à pergunta. Este mapa existe para
você abrir três arquivos em vez de trinta.

## O caminho de consulta — o que o cliente MCP executa

```
mcp/server.py  →  retrieve/hybrid.py::buscar_chunks  →  index/store.py
```

| Pergunta | Arquivo |
|---|---|
| Que ferramentas o cliente vê, e com que limites | `src/segundocerebro/mcp/server.py` |
| Como os quatro sinais se fundem, e por que cada peso é o que é | `src/segundocerebro/retrieve/hybrid.py` |
| Denso, bm25/FTS5, chunk, vizinho, menções | `src/segundocerebro/index/store.py` |
| Ranqueador de nome de arquivo | `src/segundocerebro/retrieve/nomes.py` |
| Famílias de versão (qual cópia é a vigente) | `src/segundocerebro/retrieve/familias.py` |
| Glossário de siglas por base | `src/segundocerebro/retrieve/glossario.py` |
| Grafo derivado e `neighbors` | `src/segundocerebro/retrieve/grafo.py` |
| Classificação de fonte (reunião, e-mail, escritório) | `src/segundocerebro/retrieve/fonte.py` |
| Contrato `Hit`/`Retriever` entre produto e eval | `src/segundocerebro/retrieve/contrato.py` |

**`search` e `buscar_chunks` medem coisas diferentes.** `search` é a série
histórica (nível de documento); `buscar_chunks` é o que o cliente roda. Essa
diferença já custou cinco fases de peso inerte.

## Indexação

| Pergunta | Arquivo |
|---|---|
| O laço inteiro | `src/segundocerebro/index/indexer.py` |
| Trava do índice | `src/segundocerebro/index/travas.py`, `index/trava*.py` |
| Ler arquivo sem hidratar nuvem, converter legado | `src/segundocerebro/ingest/reader.py` |
| Parsers por formato | `src/segundocerebro/ingest/parsers/` |
| Corte em chunks | `src/segundocerebro/ingest/chunking.py` |
| Enumerar o corpus sem abrir conteúdo | `src/segundocerebro/census.py` |
| Previsão de tempo e calibragem de máquina | `src/segundocerebro/index/calibracao.py`, `estimativa.py` |
| Orçamento de RAM/CPU, perfis, GPU | `src/segundocerebro/index/orcamento.py`, `esforco.py`, `gpu_pool.py` |

## Configuração e painel

`src/segundocerebro/config.py` é o esquema; `config.example.toml` é a referência
publicável. O painel é `src/segundocerebro/painel/` e está **fora** do caminho de
consulta (invariante 6) — nos dois sentidos.

## Documentação — o que ler para cada tipo de pergunta

| Pergunta | Leia |
|---|---|
| O que decide prioridade | [`docs/regra-de-ouro.md`](../../../docs/regra-de-ouro.md) — precedência sobre tudo |
| Quem mexe em quê, e as doze regras | [`docs/colaboracao.md`](../../../docs/colaboracao.md) — a única fonte |
| Por que este número é este número | [`docs/historico-decisoes.md`](../../../docs/historico-decisoes.md) |
| O que está aberto | [`ROADMAP.md`](../../../ROADMAP.md) |
| Como se mede, e o que invalida | [`docs/rigor-estatistico.md`](../../../docs/rigor-estatistico.md) |
| Índice de tudo | [`docs/README.md`](../../../docs/README.md) |

**Metade de `docs/` não está no Git.** 57 dos 104 arquivos — quase todos
`metricas-*.md` e algumas `ablacao-*.md` — citam nome de arquivo do acervo real e
ficam de fora por regra. Um link para eles resolve nesta máquina e dá 404 num
clone. `docs/README.md` marca quais são.

## O que NÃO ler

- **`docs/historico-decisoes.md` como aquecimento.** Ele saiu do `CLAUDE.md` em
  25/08/2026 porque era 79% do arquivo, e porque *quem abre a sessão lendo a
  crônica continua a crônica*. Consulte-o quando a pergunta for sobre aquele
  número específico.
- **Os dossiês** (`dossie-melhorias.md`, `dossie-complemento-update-devs.md`) —
  auditoria de 24/08 já conferida contra o código e absorvida pelo `ROADMAP.md`.
- **`docs/arquivo/`** — relatório de fase encerrada. Verdadeiro, e sobre o passado.
- **Arquivos inteiros quando você quer um símbolo.** `grep -n` primeiro.

## Comandos que respondem rápido

```bash
py -m pytest tests/ eval/ -q
```

| Quero saber | Comando |
|---|---|
| A suíte passa | `py -m pytest tests/ eval/ -q` |
| Lint e tipos como no CI | `py -m ruff check src tests eval` · `py -m pyright src` |
| Quanto do índice o dourado cobre | `py -m eval.cobertura --base <id>` |
| Onde um símbolo é usado | `grep -rn "nome" src/ tests/ eval/ --include='*.py'` |
| Em que branch estou **agora** | `git status -sb` — o usuário funde PRs em paralelo |

Caminho absoluto em todo comando entregue ao usuário. Ele roda o Claude Code pelo
**aplicativo de Windows**, não pelo terminal.
