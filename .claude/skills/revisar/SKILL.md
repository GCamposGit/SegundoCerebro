---
name: revisar
description: >
  Revisar um diff neste repositório contra os sete invariantes, as camadas, as
  classes de defeito já medidas aqui e as regras de saneamento. Use antes de
  abrir PR, ao revisar mudança de outro agente, ao conferir código pronto, ou
  quando o usuário pedir revisão. Gatilhos: revisar, review, conferir o diff,
  antes do PR, está pronto?, checar, auditar mudança, invariante, camada,
  vazamento, saneamento.
---

# Revisar aqui

Procure nesta ordem. As três primeiras seções reprovam sozinhas; o resto é
qualidade.

## 1. Vazamento — reprova e não se discute

Repositório **público**, acervo **real**. O vazamento aconteceu três vezes em
dois dias, sempre igual: um nome de cliente numa fixture, num exemplo de CLI ou
num id de teste, invisível no meio de um diff grande.

- Nenhuma sigla, razão social, nome de arquivo ou caminho do acervo em arquivo
  versionado. Vocabulário de teste vem da **VCE**, a empresa fictícia de
  `eval/sintetico/`; o dicionário publicável é `eval/glossario.example.toml`.
- Relatório por pergunta **sempre** cita nome de arquivo do acervo — é o que ele
  é. Por isso `docs/metricas-*.md` é padrão de `.gitignore`, e não lista por nome:
  lista por nome **falha em silêncio no arquivo seguinte** (quatro `metricas-f2-*`
  foram commitados assim).
- `tests/test_saneamento.py` confere contra `nomes-proibidos.txt`, que é local e
  fora do Git. **Lista magra não produz suíte incompleta: produz suíte verde**, e
  já produziu — 8 nomes reais em 4 arquivos com a suíte no verde.
- Ao sanear, `\bSIGLA\b` **não** casa dentro de literal como `'\nRDE = ...'`: o
  caractere antes do `R` é o `n` da escapada, que é caractere de palavra. Auditar
  com o padrão **e** com o caso escapado.

## 2. Os sete invariantes — `ARCHITECTURE.md`

1. Nenhuma chamada a API paga no caminho de consulta
2. Nenhuma ferramenta que gere texto na superfície MCP (`answer`, `summarize`…)
3. Multi-hop é do cliente — nada de orquestrador de retrieval
4. Toda mudança em chunking, embedding ou ranking passa pelo eval
5. Todo retorno de ferramenta carrega procedência (arquivo + seção) e id estável
6. O painel está fora do caminho de consulta — **e o caminho de consulta está
   fora do painel**: `tests/test_painel.py` prova as duas direções
7. Isolamento entre bases é físico (um diretório por base), nunca filtro de
   metadado numa consulta compartilhada

## 3. Camadas e fronteira de empacotamento

Ordem: `logger`/`config`/`repositorio` → `ingest` → `index` → `retrieve` →
`mcp`/`painel`. Import de baixo para cima é violação.

- **`src/` não importa `eval/`.** `eval` é o único diretório fora do pacote;
  todo import dele a partir do produto é `ModuleNotFoundError` esperando o
  primeiro usuário que instalou com `pip`. `tests/test_pacote.py` varre o AST —
  inclusive imports dentro de função, que é onde o caso real se escondia.
- **Nada deduz a raiz do repositório à mão.** `repositorio.raiz()` e
  `repositorio.em_checkout()`.
- **Import dentro de função** só se for dependência opcional de verdade (CUDA,
  RapidOCR, LibreOffice, olefile) ou quebra de ciclo declarada. "Localidade" não é
  motivo.
- **Ninguém importa módulo pesado para ler constante.** Abrir o painel carregava
  o encoder inteiro (1,08 s) por causa de duas linhas que liam o nome de um
  arquivo de trava.

## 4. As classes de defeito medidas aqui

Para cada uma, pergunte se o diff a reintroduz. A contagem é do histórico real.

| Classe | ×  | O que procurar no diff |
|---|:-:|---|
| Regra que não casa com nada falha em silêncio | 4 | glob, filtro, exclusão, chave de config, regex — **contagem por regra conferida contra zero** antes de pagar o custo |
| Instrumento de avaliação com defeito próprio | 5 | mudou o harness? o instrumento foi medido antes do braço? a fatia tem n>0? |
| Guarda que cobre metade da superfície | 2 | o teste novo cobre o caminho que o produto executa, ou só o mais fácil de escrever? |
| Número escrito à mão envelhece calado | — | número copiado para documento em vez de recalculado pelo relatório |
| Estado global escrito e não desfeito | 1 | `os.environ[...] =`, variável de módulo mutável, cache de processo |
| Commit grande demais para revisar | 34 | acima de ~500 linhas, quebre em dois |
| Causa errada por medir em blocos sequenciais | 1 | braços de velocidade intercalados, não em blocos |

## 5. Qualidade

- **Docstring de decisão se preserva verbatim.** Elas têm número e data e são o
  ativo mais raro do repositório: são ADR embutida que não descola do código.
  Refactor que apaga histórico de decisão é reprovação, mesmo verde.
- **Teto de arquivo: ~500 linhas.** Arquivo grande é o pior caso para edição por
  agente — mais contexto queimado por edição, mais conflito entre os dois setups,
  diff mais difícil de revisar. Módulo novo acima disso não entra.
- **Função acima de ~60 linhas** quer justificativa.
- **`except Exception` só nas três bordas:** subprocesso/arquivo hostil, laço de
  onda que não pode morrer, probe de hardware. Sempre com log da exceção real, e
  **nunca** no caminho de consulta MCP sem re-raise tipado. Todo `noqa: BLE001`
  com motivo escrito depois do código.
- **Sem `print()`** — `logger.get_logger("modulo")`. `stdout` é do protocolo MCP.
- **Teste isolado**: `tmp_path` e `monkeypatch`; nunca o índice nem as pastas
  reais. E lembre que `monkeypatch` só desfaz o que **ele** fez.
- **Caminho longo**: `\\?\` ao **abrir** arquivo no Windows. `os.scandir` enumera
  sem problema; o erro só aparece na abertura, como "arquivo não encontrado".
- **Nuvem**: nunca abrir conteúdo sem checar `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`
  / `FILE_ATTRIBUTE_OFFLINE` — ler um placeholder do SharePoint dispara download.
- Código e comentário em **inglês**; documentação e string de usuário em
  **português**.

## 6. Antes de aprovar

- [ ] `py -m pytest tests/ eval/ -q` — mesma contagem de falhas de antes, ou menos
- [ ] `py -m ruff check src tests eval` e `py -m pyright src` limpos
- [ ] A linha "classe generalizada" existe e aponta para um teste que passa a
      pegar a classe sozinho
- [ ] Se mexeu em ranking, tem número antes e depois, com cobertura ao lado
