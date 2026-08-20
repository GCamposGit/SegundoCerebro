# Usar o Segundo Cérebro pelo MCP

Estado em 13/08/2026: **superfície mínima de pé**, duas ferramentas, provada
ponta a ponta por stdio contra o índice real.

## Ligar no Claude Code

O `.mcp.json` na raiz do projeto já traz a configuração. Abrindo o Claude Code
nesta pasta, ele oferece aprovar o servidor `segundocerebro` na primeira vez.

Para usar de outra pasta, ou em outro cliente, o comando é:

```bash
py -m segundocerebro.mcp.server --indice index
```

com `PYTHONPATH=src` e o diretório de trabalho na raiz do projeto. O transporte é
stdio; não há porta de rede, e o servidor só lê o índice.

### Várias bases

Desde 15/08/2026 uma instalação atende N acervos, cada um com índice e servidor
próprios — pessoal e trabalho sem se misturarem. Com `config.toml` no lugar:

```bash
py -m segundocerebro.mcp.server --base trabalho
```

O nome do servidor vira `segundocerebro-trabalho`, e índice, modelo e pesos saem
da base. Sem `config.toml` nada muda: o comando acima continua valendo e o
servidor continua se chamando `segundocerebro`.

Para não editar JSON à mão, o trecho de registro sai pronto:

```bash
py -m segundocerebro.mcp.registrar --base trabalho
```

Imprime na tela; com `--out .mcp.json` grava **mesclando**, preservando os outros
servidores MCP que já estiverem lá. `--todas` registra todas as bases de uma vez
— o que é conveniência, não isolamento.

**O controle de acesso é qual servidor você registra naquele cliente.** Registrar
só a base pessoal num projeto é fronteira dura — a ferramenta não existe na
sessão do agente. Registrar as duas e contar que o modelo escolha pela descrição
é conveniência, não garantia; para isso a descrição de cada base precisa dizer
de verdade o que ela cobre, porque é o único sinal que o modelo tem.

A **primeira consulta demora ~80 s**: é o `e5-large` carregando. Depois disso as
buscas respondem em frações de segundo. O modelo é carregado sob demanda de
propósito — carregar na importação estoura o handshake do cliente MCP, e o modo
de falha seria "servidor não conecta", que não diz nada sobre a causa.

## Ligar no Claude Desktop — o segundo cliente

Um comando, sem editar JSON:

```bash
py -m segundocerebro.mcp.registrar --cliente claude-desktop --instalar
```

Grava em `%APPDATA%\Claude\claude_desktop_config.json`, **mesclando**: os outros
servidores MCP e as preferências do app ficam intactos, e o que mudou é relatado
na saída. Depois, fechar e reabrir o Claude Desktop — ele lê a configuração no
início, não recarrega em quente.

Sem `--instalar` o comando imprime o trecho e diz onde colar, que é o caminho
para qualquer outro cliente MCP por stdio (`--cliente generico`).

Duas diferenças em relação ao Claude Code, e são as duas que fazem o registro
manual falhar:

- **Os caminhos saem absolutos.** O Claude Desktop nasce em
  `C:\Windows\system32`, e ali `PYTHONPATH=src` não aponta para nada. O servidor
  subiria com `ModuleNotFoundError`, que o cliente mostra como "servidor não
  conecta" — silencioso quanto à causa. Por isso o trecho fixa `PYTHONPATH`,
  `--config` e `cwd`.
- **A primeira consulta ainda demora ~80 s.** No Claude Desktop isso aparece
  depois do servidor já ter conectado, na primeira `search` — não no início. Se o
  servidor aparecer como conectado e a primeira busca parecer travada, é a carga
  do modelo.

Sobre o `--instalar`: ele só existe para cliente cujo caminho **e** formato foram
conferidos. O VS Code fica fora de propósito — o `mcp.json` dele chama a seção
`servers`, não `mcpServers`, e o trecho gerado aqui não serve para ele.

## As duas ferramentas

**`search(consulta, k=8)`** — trechos por significado e por termo exato, fundidos
por RRF. Devolve, para cada trecho: `id`, `arquivo`, `secao`, `onde`, `texto`,
`score` e `achado_por` (qual ranqueador o encontrou: denso, lexical ou os dois).

**`read_note(id, janela=1)`** — o trecho pedido mais os vizinhos do mesmo
documento, para ler o contexto em volta. O `id` é o que veio da `search`.

São duas, e não as cinco do ROADMAP, porque `search` e `read_note` já fecham o
laço: "onde está X" e "me mostra o que tem em volta". `neighbors` e `list_recent`
continuam hipóteses — o uso real responde isso melhor que o palpite.

A `glossary` que o ROADMAP previa **não virou ferramenta**, e por decisão: o
glossário de siglas entrou como expansão de consulta dentro da `search`, invisível
para o cliente. Uma ferramenta de glossário obrigaria o modelo a saber que precisa
consultá-la antes de buscar — mais uma chamada por consulta e uma chance de ele
não fazer. Expandir por dentro sempre funciona.

## O que o servidor não faz, e por quê

Não existe ferramenta que gere texto. Nada de `answer`, `summarize` ou `explain`.
Isso não é omissão: é a invariante 2 do `ARCHITECTURE.md`. Uma etapa de geração
no servidor reintroduziria custo por consulta e amarraria o projeto a um
fornecedor, que é exatamente o que a arquitetura existe para evitar. Quem gera
texto é o cliente; o servidor recupera e devolve procedência.

Multi-hop também é do cliente. As duas ferramentas são primitivas componíveis, e
o laço de agente é quem compõe.

## O que esperar, honestamente

Medido em 18/08/2026 sobre o **corpus completo** — 1.601 documentos, 92.137
chunks — contra o baseline de busca por nome de arquivo, em 45 perguntas do
conjunto dourado (`docs/ablacao-f2.md`). A coluna "atual" é sem reranking, com
famílias de versão e com um glossário de 10 siglas:

| | baseline | atual |
|---|---:|---:|
| recall@1 | 0,467 | **0,667** |
| recall@5 | — | **0,885** |
| recall@10 | 0,800 | **0,930** |
| MRR@10 | 0,592 | **0,787** |
| nDCG@5 | — | **0,793** |
| perguntas do usuário: MRR | 0,557 | **0,724** |
| perguntas do usuário: recall@10 | 0,833 | **1,000** |

Com `rerank = 0.25` na base, o recall@1 vai a **0,678** e a consulta fica ~8×
mais lenta. É troca, não melhoria pura — e nessa métrica o glossário, que é de
graça, rende mais que o reranking.

As seis perguntas escritas de memória pelo usuário — o subconjunto sem viés de
construção — são **todas** encontradas dentro do top-10.

E o que ele **ainda erra**, para você não descobrir sozinho:

- **Famílias de versão — resolvido em 16/08/2026.** Perguntar "qual a versão
  vigente" passou a trazer a vigente e citar as anteriores; os casos-armadilha
  foram de 4 para **5 de 6** (`ablacao-familias.md`). O que ainda erra é
  discriminar propostas irmãs na mesma pasta quando o nome tem erro de digitação —
  caso nomeado, não resolvido pelo reranking.
- **Multi-hop: 1 de 5.** Ele acha *uma* das fontes bem — o MRR saltou de 0,117
  para 0,600 — mas juntar **todas** as fontes no top-10 só acontece numa das
  cinco. É o ponto mais fraco e o mais sensível à escala, exatamente como
  `escala-f0.md` previu.
- **Email e PDF digitalizado não estão indexados**, por decisão de escopo
  registrada. `search` nunca vai encontrá-los. A fila está no registro:
  `SELECT path FROM documentos WHERE digitalizado = 1`.
- **5 planilhas gigantes foram adiadas** com `--pular-planilha-acima-de 40`.
  `SELECT path, detalhe FROM documentos WHERE status = 'adiado'` lista quais.

## Ensinar as siglas da sua casa

O ganho mais barato do sistema, e o único que ele não tem como adivinhar. Quando
você pergunta "o acordo de proteção de dados" e o contrato diz "DPA", nada liga as
duas formas; o contrário também.

No painel, seção **Siglas da sua casa**: a sigla como aparece nos arquivos, o que
ela significa, e pronto. As buscas passam a achar os dois jeitos, **sem custo
nenhum no tempo de resposta** — é consulta a dicionário antes de qualquer
ranqueador.

Medido em 18/08/2026 (`ablacao-glossario.md`) com 10 siglas: recall@1 0,644 →
**0,667**, nDCG@5 0,760 → **0,793**, e **0,571 → 0,724 de MRR nas perguntas
escritas de memória** — o subconjunto que mais se parece com o uso real, porque no
uso real ninguém consulta o nome do arquivo antes de perguntar. Zero regressões.

O dicionário **nasce vazio**, e isso é resultado de medição, não economia de
trabalho: a metade genérica do dicionário de teste — mês abreviado, que serviria a
qualquer acervo — deu **zero**, e as siglas da empresa deram o ganho inteiro. Não
há dicionário embutido porque um dicionário embutido não ajudaria ninguém.

## O que fazer com o que você encontrar

Anotar a pergunta que falhou, com o arquivo que deveria ter respondido. É isso
que vira o conjunto dourado v2 — o atual tem **39 das 45 perguntas escritas a
partir de nomes de arquivo**, viés conhecido e registrado, e perguntas reais são
o que corrige isso.
