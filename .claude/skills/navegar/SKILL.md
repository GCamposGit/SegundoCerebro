---
name: navegar
description: Localizar implementações, testes e decisões do Segundo Cérebro com contexto mínimo; usar ao investigar ou retomar uma tarefa.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Mapa de entrada

Use `rg -n "simbolo" src tests eval` e leia as linhas relevantes. Comece pelo consumidor entregue e acompanhe até o produtor.

- Ferramentas e transporte: `src/segundocerebro/mcp/server.py`; recuperação em `mcp/busca.py`; mapa em `mcp/leitura.py`; leitura integral em `mcp/documento.py`; visão geral em `mcp/overview.py`.
- Ranking entregue: `retrieve/hybrid.py::buscar_chunks`. `search` interno é a série por documento; não confundir com a tool MCP de mesmo nome.
- Persistência: `index/store.py`, `index/esquema.py`, `ingest/parse_store.py`. Identidade e leitura: `acesso/identidade.py`, `registro.py`, `documento.py`, `empacote.py`.
- Ingestão: `ingest/reader.py`, `ingest/parsers/`, `ingest/chunking.py`. Execução: `index/indexer.py`, `isolamento.py`, `reconciliar.py`, `watcher.py`.
- Configuração: `config.py`, `config_leitura.py`, `config_escrita.py`. Painel: `painel/app.py`, `sessao.py`, `exportar.py`, `index.html`.
- Dublês: `tests/falsos.py` e `eval/falsos.py`; fixtures em `tests/conftest.py`; isolamento de ambiente no `conftest.py` da raiz.
- Prioridades: regra de ouro; estado e donos: colaboração; planejamento: roadmap e plano fundamental. Decisões antigas: `docs/historico-decisoes.md`, apenas por necessidade.

Verifique se um documento está versionado antes de vinculá-lo. Não abra índices, modelos, configs locais ou relatórios privados para descobrir código. Não carregar todos os dossiês ou todas as skills para uma edição pequena.
