# Famílias de versão ≠ Grupos de formato — Decisão e Ablação C6

> Implementado em 05/09/2026. Pacote C6 (P0): reconciliação entre evolução temporal de versões e desduplicação de formatos alternativos.

## 1. Motivação e Diagnóstico

O projeto identificou uma colisão arquitetural entre deduplicação/near-dup (`R1.3`) e colapso de famílias (`retrieve/familias.py`):
- No caso **`g010`**, irmãos de versão com datas divergentes competiam pelo mesmo espaço; quem declara versão vence, e a data desempata.
- No caso **`g045`**, o mesmo deck existia como `.pptx` e `.pdf`. Se fundidos prematuramente na mesma família, o critério de vigência por data escolhia um formato ao acaso — fazendo com que a busca pelo deck retornasse o PDF e desabasse no ranking.

A decisão medida de manter a extensão em `chave_de_familia` protegeu `g045`, mas deixava múltiplos formatos do mesmo documento ocupando múltiplos slots no top-$k$.

## 2. A Solução em Dois Estágios (C6.c)

Separamos os dois conceitos com políticas distintas em cascata no ranqueamento:

1. **Estágio 1 — Família de versões** (conteúdo evolui; `_v1` → `_v2`):
   - Chave: `pasta + extensão + tronco sem marcadores`.
   - Política: representante por vigência (número declarado vence; data desempata); herda a melhor posição entre seus irmãos e acumula as anteriores.
2. **Estágio 2 — Grupo de formatos** (conteúdo equivalente em containers distintos: PPTX vs PDF, DOCX vs PDF):
   - Chave: `pasta + tronco sem marcadores` (sem extensão).
   - Política: **um slot único no top-k**, representante = **o mais bem ranqueado** pela fusão/reranker (não a data arbitrária de exportação). Os formatos alternativos são acumulados no campo `formatos`.

### Proteção a `g045`
Se a consulta do usuário indica preferência pelo deck ("apresentação", "slides"), o ranqueador de nome e o bm25 pontuam o PPTX melhor que o PDF. Como o representante do grupo de formatos é o mais bem ranqueado, o PPTX vence o slot e o PDF vai para a lista `formatos`. `g045` permanece verde.

## 3. Superfície MCP e Fluxo de Agente (C6.a)

A comparação de versões é tarefa do LLM cliente, nunca do servidor ("o servidor só recupera"):
- `search` expõe em cada trecho:
  - `versoes: int` — total de versões da família;
  - `anteriores: list[dict]` — versões anteriores colapsadas com `id`, `arquivo`, `caminho` e `data`;
  - `formatos: list[dict]` — formatos alternativos colapsados com `id`, `arquivo`, `formato` e `data`.
- O agente compara minutas históricas chamando `read_note(id=...)` para os IDs listados em `anteriores`.

## 4. Cobertura de Testes e Aceite

- `tests/test_familias.py`:
  - `test_chave_de_formato_ignora_extensao`
  - `test_colapso_de_formatos_mais_bem_ranqueado_vence_slot_g045`
  - `test_colapsar_dois_estagios_versoes_depois_formatos`
  - `test_superados_de_ranking`
- `tests/test_hybrid.py`:
  - `test_buscar_chunks_e_search_incluir_versoes_antigas` (com assertions para `anteriores` e `versoes`)
  - `test_buscar_chunks_e_search_com_colapso_de_formatos`
- `tests/test_mcp.py`:
  - `test_search_com_familias_e_formatos`
- Casos-guarda `g010` e `g045` preservados.
