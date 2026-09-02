# J.e — exportador de vault Markdown no Desktop

02/09/2026. View one-way do acervo; não inclui botão no painel, síntese,
ranking nem OCR novo. (O botão do painel entrou no `J.e.1`, PR #73.)

## Contrato e aceite

Defeito para base desconhecida: depois de enumerar e empacotar a pasta, o leigo
ainda não consegue *ver e navegar* o acervo como Markdown interligado. Escrever
`.md` dentro da pasta indexada polui a taxonomia, dispara sync e entra em loop
com o observador. O vault é a saída explícita — fora das raízes, descartável.

Aceite binário:

- export recusa destino dentro de raiz indexada, inclusive pasta ainda não criada;
- apagar o vault e re-exportar produz os mesmos bytes (sem timestamp de geração);
- re-export incremental só reescreve nota cujo conteúdo derivado mudou;
- a raiz indexada não ganha arquivo nenhum — foto de filesystem antes/depois.

Qualquer falha bloqueia o pacote. Não há hipótese de ganho de retrieval.

## O que o comando faz

```bash
py -m segundocerebro.acesso.exportar --base trabalho --destino D:\vault-obsidian
```

`--pasta Projetos/Gama` recorta; `--politica todos` inclui rascunhos de família;
`--completo` reescreve mesmo o que não mudou. Padrão: `canonicos`, árvore inteira.

Cada documento vira `.md` com frontmatter (`doc_id`, caminho original, hash,
rota de parse, tags da pasta, `view: one-way`) e corpo = Markdown canônico.
Identificadores citados em dois ou mais documentos do vault viram `[[wikilinks]]`
para uma nota-índice em `_grafo/`, derivada da tabela `mencoes`. Siglas do
glossário da base viram âncora em `glossario.md`. Não inventa aresta.

O manifesto `.segundocerebro-vault.json` guarda a chave de cada arquivo gravado
por este comando. Re-export compara a chave; arquivo que o usuário criou no
vault e que não está no manifesto não é apagado. Arquivo que este programa
gravou e que saiu da seleção é removido.

## O que não faz

Não é ferramenta MCP — escrever no disco é ação do usuário, não do agente.
Não resume, não ranqueia, não inicia OCR, não sincroniza de volta, não escreve
nas raízes. O painel ganhou o botão **Exportar vault** (`J.e.1`, 02/09/2026):
mesma recusa de destino, sem carregar encoder na abertura. A costura do `Q16`
tirou a sessão para `painel/sessao.py` para a rota caber.

## Reuso

Parse Store e os portões de `get_document`, `familias.py` (canônico), tabela
`mencoes`, `glossario.py`. Zero dependências novas. Validação manual no
Obsidian: abrir o destino, conferir o grafo das notas `_grafo/` — a suíte
confere a sintaxe; o aplicativo não está no CI.

## Validação

`tests/test_vault.py` cobre recusa de destino, foto da raiz, re-export idêntico,
incremental, famílias, `so_censo`, wikilinks, glossário, code fence e o CLI.
Nenhuma linha de `retrieve/hybrid.py`. O dourado privado segue indisponível
neste Desktop; não há Δ de ranking — e não pode haver.
