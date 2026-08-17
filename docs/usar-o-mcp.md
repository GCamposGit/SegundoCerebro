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

## As duas ferramentas

**`search(consulta, k=8)`** — trechos por significado e por termo exato, fundidos
por RRF. Devolve, para cada trecho: `id`, `arquivo`, `secao`, `onde`, `texto`,
`score` e `achado_por` (qual ranqueador o encontrou: denso, lexical ou os dois).

**`read_note(id, janela=1)`** — o trecho pedido mais os vizinhos do mesmo
documento, para ler o contexto em volta. O `id` é o que veio da `search`.

São duas, e não as cinco do ROADMAP, porque `search` e `read_note` já fecham o
laço: "onde está X" e "me mostra o que tem em volta". `neighbors`, `list_recent`
e `glossary` são hipóteses sobre o que será necessário — o uso real responde isso
melhor que o palpite.

## O que o servidor não faz, e por quê

Não existe ferramenta que gere texto. Nada de `answer`, `summarize` ou `explain`.
Isso não é omissão: é a invariante 2 do `ARCHITECTURE.md`. Uma etapa de geração
no servidor reintroduziria custo por consulta e amarraria o projeto a um
fornecedor, que é exatamente o que a arquitetura existe para evitar. Quem gera
texto é o cliente; o servidor recupera e devolve procedência.

Multi-hop também é do cliente. As duas ferramentas são primitivas componíveis, e
o laço de agente é quem compõe.

## O que esperar, honestamente

Medido em 16/08/2026 sobre o **corpus completo** — 1.601 documentos, 92.125
chunks — contra o baseline de busca por nome de arquivo, em 45 perguntas do
conjunto dourado (`docs/ablacao-f1.md`):

| | baseline | atual |
|---|---:|---:|
| recall@1 | 0,467 | **0,600** |
| recall@10 | 0,800 | **0,907** |
| MRR@10 | 0,592 | **0,736** |
| perguntas do usuário: recall@10 | 0,833 | **1,000** |
| multi-hop MRR | 0,117 | **0,600** |

As seis perguntas escritas de memória pelo usuário — o subconjunto sem viés de
construção — são **todas** encontradas dentro do top-10.

E o que ele **ainda erra**, para você não descobrir sozinho:

- **Famílias de versão.** Perguntar "qual a versão vigente" traz `_v1`, `_v3`,
  `_v7` e não o vigente. São 4 de 6 casos-armadilha; a meta é 5, e o tratamento
  de famílias de versão é da F2. As duas que faltam são a `g010` (versão vigente
  da Política de IA) e a `g036` (qual empresa propôs implantação de IA).
- **Multi-hop: 1 de 5.** Ele acha *uma* das fontes bem — o MRR saltou de 0,117
  para 0,600 — mas juntar **todas** as fontes no top-10 só acontece numa das
  cinco. É o ponto mais fraco e o mais sensível à escala, exatamente como
  `escala-f0.md` previu.
- **Email e PDF digitalizado não estão indexados**, por decisão de escopo
  registrada. `search` nunca vai encontrá-los. A fila está no registro:
  `SELECT path FROM documentos WHERE digitalizado = 1`.
- **5 planilhas gigantes foram adiadas** com `--pular-planilha-acima-de 40`.
  `SELECT path, detalhe FROM documentos WHERE status = 'adiado'` lista quais.

## O que fazer com o que você encontrar

Anotar a pergunta que falhou, com o arquivo que deveria ter respondido. É isso
que vira o conjunto dourado v2 — o atual tem **39 das 45 perguntas escritas a
partir de nomes de arquivo**, viés conhecido e registrado, e perguntas reais são
o que corrige isso.
