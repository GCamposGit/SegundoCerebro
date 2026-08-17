# Painel de ajuste

> **Status: aprovado em 14/08/2026.** É a **F3.5** do ROADMAP. As invariantes 6
> e 7 do `CLAUDE.md` e a seção de bases do `ARCHITECTURE.md` §2 saíram daqui.
>
> Mudança de escopo no mesmo dia, também por decisão do usuário: a fase deixou de
> ser só a tela e passou a ser **bases + tela**. As duas se apoiam no mesmo
> artefato — um arquivo de configuração lido pelo servidor, pelo indexador e pelo
> eval — e escrevê-lo duas vezes era o desperdício.

Tela de configuração para o usuário final ajustar a recuperação ao seu acervo
**sem escrever código e sem abrir terminal**. Fora do caminho de consulta: o
painel lê e grava um arquivo de configuração, não fica entre o cliente e a
busca.

E, desde a mudança de escopo, o lugar onde se cria e se separa uma **base**:
pessoal e trabalho com índices distintos, servidores MCP distintos, e o controle
de acesso sendo *qual servidor está registrado naquele cliente*. A decisão de
arquitetura — separação física, nunca filtro — está no `ARCHITECTURE.md` §2 e
não se repete aqui. O que interessa a este documento é o que ela impõe à tela.

---

## 1. O que isso muda no que já está escrito

Duas linhas dizem hoje que isso não existe:

| Onde | O que diz | Por que não contradiz esta proposta |
|------|-----------|-------------------------------------|
| ROADMAP, fora de escopo | "UI própria — redundante com o cliente MCP na fase pessoal" | Aquela linha é sobre **UI de consulta** — caixa de busca, lista de resultados, chat. Continua fora, e por motivo mais forte que "redundante": uma UI de consulta que resumisse resultado quebraria a invariante 2 |
| ARCHITECTURE §5, limites | "Sem UI própria … insuficiente para usuário final não-técnico" | É exatamente o limite que esta fase remove, e só ele |

A distinção é o que mantém as invariantes de pé, e por isso vale escrever nos
dois documentos em vez de só apagar a linha: **UI de consulta continua fora; UI
de configuração entra.** O painel não recupera, não ranqueia e não gera texto —
ele escreve um TOML e mostra números do eval.

## 2. O pré-requisito: hoje não existe o que configurar

O painel não é a primeira metade do trabalho. A primeira metade é que **nenhum
parâmetro de recuperação é configurável hoje** — são constantes de módulo e
`argparse`:

| Parâmetro | Onde vive hoje | Valor |
|-----------|----------------|------:|
| `peso_denso` | constante em `retrieve/hybrid.py` | 1,0 |
| `peso_lexical` | idem | 0,25 |
| `peso_nome` | idem | 0,5 |
| `k_rrf` | idem | 60 |
| `candidatos` | idem | 200 |
| `k` padrão / máximo | constantes em `mcp/server.py` | 8 / 50 |
| `janela` de `read_note` | idem | 1 / 5 |
| modelo de embedding | `--modelo` do indexador e do servidor | `e5-large` |
| `max_chars` / `min_chars` / `overlap_chars` | `ChunkConfig` | 1800 / 250 / 200 |
| `threads` | `--threads` | 10 |
| raízes e exclusões | `census.toml` | — |

Trocar o peso do denso hoje é editar um `.py`. Isso significa que o item mais
valioso desta fase **não é a tela**: é um `config.toml` único com ordem de
resolução declarada (padrão do código → arquivo → variável de ambiente → flag de
CLI), lido pelo servidor MCP, pelo indexador e pelo eval. Com isso pronto,
`eval.varredura` para de instanciar `BuscaHibrida` à mão e passa a variar o mesmo
objeto de configuração que o painel grava — o que é o que garante que o número
medido é o número que vai valer em produção.

Com as bases, esse arquivo tem duas camadas: `[padrao]`, herdado, e `[[base]]`,
que sobrescreve. A herança não é conveniência de digitação — é o que mantém
honesta a comparação entre bases, porque deixa explícito no arquivo **onde** duas
bases diferem.

```toml
[padrao]
modelo = "e5-large"

[padrao.pesos]
denso = 1.0
lexical = 0.25
nome = 0.5

[[base]]
id = "pessoal"
nome = "Base pessoal"
descricao = "Documentos pessoais..."   # vira a instructions do servidor MCP
indice = "index/pessoal"
modelo = "minilm"                      # base pequena, reindexa muito mais rápido
raizes = [{ nome = "documentos", caminho = 'C:\Users\...\Documentos' }]

[[base]]
id = "trabalho"
nome = "Acme Holding"
descricao = "Contratos, propostas e atas da Acme Holding..."
indice = "index"                       # o índice que já existe — sem reindexar
raizes = [{ nome = "trabalho", caminho = 'C:\...\07. Acme Holding' }]

[base.pesos]                           # este acervo tem código de contrato
lexical = 0.5
```

Sem `config.toml`, o carregador sintetiza **uma** base a partir do `census.toml`
atual, apontando para o `index/` que já existe. Ninguém reindexa por causa desta
fase — o que importa hoje, com uma indexação de horas em curso.

Esse pedaço tem valor com painel ou sem painel, e é pré-condição da F2: o
reranking chega com seus próprios botões (ligado/desligado, quantos candidatos
reranquear, limiar de corte) e é mais barato entregá-los numa superfície que já
existe do que retrofitar constantes depois.

## 3. As três classes de custo — a decisão de UX que importa

Um painel que trate todos os parâmetros como iguais deixa um usuário
não-técnico disparar uma reindexação de 35 horas mexendo num dropdown. Os
parâmetros se dividem pelo **custo de mudar**, e a tela tem que mostrar isso
antes de o clique acontecer:

| Classe | Parâmetros | Custo de mudar | Como aparece na tela |
|--------|-----------|----------------|----------------------|
| **Grátis** | os três pesos, `k_rrf`, `candidatos`, `k`, `janela` | zero — recarrega sem reindexar | Controles diretos. Medir custa segundos na subárvore de dev |
| **Cara** | modelo de embedding, `max_chars`, `min_chars`, `overlap_chars` | **reindexação completa**: ~31 h (MiniLM) a ~114 h (`e5-large`) no corpus real, medido em 15/08/2026 | Seção separada, com a estimativa em horas no próprio botão e confirmação explícita. Nunca aplica sozinho |
| **De instalação** | raízes, exclusões, política de placeholders, `threads` | nova varredura de disco; placeholders podem **baixar conteúdo** | Assistente de primeira execução, não painel de ajuste |

Trocar `max_chars` muda o `CHUNKER_VERSION` na prática: todos os ids mudam, e
comparar uma medição de antes com uma de depois deixa de ser legítimo. O painel
tem que dizer isso na hora, com essas palavras.

**A estimativa em horas se calcula, não se tabela.** Em 15/08/2026 os números
desta seção estavam errados por ~3×, porque vinham de um banco de ensaio do
encoder isolado sobre uma contagem de chunks tirada do corpus estreito. O painel
faz a conta com o que a máquina e a base sabem: chunks daquela base × (segundos
por chunk do encoder + custo de parse medido), com a vazão real do último run
quando houver uma. Número herdado de tabela envelhece em silêncio, e este é
justamente o número em que a tela pede confiança antes de um compromisso de dias.

## 4. A regra que desenha a tela: nada é salvo sem medida

A invariante 4 diz que toda mudança em chunking, embedding ou ranking passa pelo
eval. Um painel de controles soltos violaria a própria regra do projeto. Então o
fluxo não é *arrastar → salvar*, é:

```
ajustar → Medir (roda o conjunto dourado) → ver o antes/depois por pergunta → Salvar
```

O backend já existe: `eval.harness` mede, `eval.varredura` varre a grade e
`eval.comparar --antes X --depois Y` lista o movimento de cada pergunta. O painel
é uma cara nova para três coisas que já rodam, e o botão **Salvar fica desligado
até existir medição da configuração exibida**. Isso transforma o painel de risco
em mecanismo de garantia da invariante 4 — que hoje depende de disciplina minha.

O antes/depois é por pergunta, não por média, porque a porta 5 do ROADMAP é
orçamento de regressão e duas médias não dizem *quais* perguntas se moveram.

## 5. A tela, em três estágios

Tudo abaixo é **por base**. O seletor de base é o primeiro elemento da tela, e
não um filtro no canto: trocar de base troca as raízes, o índice, o modelo, os
pesos, as métricas e o conjunto dourado. Duas bases nunca aparecem no mesmo
número.

### Estágio 0 — criar e conectar uma base

O caminho que hoje não existe para quem não abre terminal:

1. Nomear a base e escrever a descrição — que **não é enfeite**: é a
   `instructions` do servidor MCP, o único sinal pelo qual o modelo escolhe entre
   duas bases registradas no mesmo cliente (`ARCHITECTURE.md` §2)
2. Escolher as pastas, com o censo rodando em cima da escolha **antes** de
   indexar: quantos arquivos, quais formatos, quantos placeholders de nuvem. É
   barato (só metadados) e responde "isso vai demorar quanto" antes do
   compromisso, não depois
3. Indexar, com a estimativa em horas à mostra e retomada se parar
4. **Conectar** — o painel mostra o trecho de `.mcp.json` daquela base e oferece
   gravá-lo. A geração já existe desde o bloco B
   (`py -m segundocerebro.mcp.registrar --base X`), e mescla em vez de
   substituir — o painel chama, não reimplementa

A tela precisa dizer, em uma linha e sem jargão, o que a separação garante e o
que ela não garante: registrar só a base pessoal num cliente é fronteira dura;
registrar as duas e confiar que o modelo escolhe certo é conveniência. A
diferença importa quando o acervo é de um cliente corporativo.

### Estágio 1 — perfis medidos, não controles crus

O mais amigável não é três controles deslizantes: é **escolher entre
configurações já medidas**. A varredura de 13/08 produziu 37 pontos com
recall@1, MRR, armadilhas e multi-hop de cada um (`docs/varredura-pesos-f1.md`).
Esses dados viram cartões com nome em português e os números ao lado:

| Perfil | pesos (denso / bm25 / nome) | Para quem |
|--------|------------------------------|-----------|
| Equilibrado (atual) | 1 / 0,25 / 0,5 | Padrão. Escolhido pela regra da varredura |
| Código e contrato | peso maior no bm25 | Acervo cheio de sigla, número de processo, código |
| Significado | bm25 baixo ou zero | Perguntas em linguagem natural, nomes de arquivo ruins |
| Nome de arquivo | peso maior no nome | Acervo muito bem organizado, como este |

Cada cartão mostra o que ele **custa**, não só o que ganha — o perfil
"Significado" sobe o MRR para 0,769 e derruba as armadilhas de 4 para 3 de 6.
Esconder o trade-off seria a versão desonesta desta tela.

Ressalva que a tela tem que carregar, e não escondir numa nota de rodapé: **esses
números foram medidos em outro acervo** — a subárvore de dev, com as 45 perguntas
do conjunto dourado. Numa base nova eles são ponto de partida, não previsão. O
cartão mostra "medido em: base X" até a base ter conjunto dourado próprio, e aí
passa a mostrar o número dela. É o estágio 3 que fecha esse laço, e é por isso
que ele não é um extra.

Controles deslizantes existem, numa gaveta "Avançado", com a grade inteira
disponível.

### Estágio 2 — diagnóstico de uma consulta

Uma caixa de busca que **não é UI de consulta**: ela mostra, para uma pergunta
digitada, quais ranqueadores acharam cada trecho (`achado_por` já vem no retorno
do `search`), a posição em cada ranking antes da fusão e a contribuição RRF de
cada um. É a tela que responde "por que esse documento veio em primeiro" — que é
a pergunta que um usuário não-técnico realmente tem quando quer ajustar algo.
Sem geração de texto, sem resumo: só procedência e números.

### Estágio 3 — o conjunto dourado crescendo do uso real

"Otimizar para o meu caso" só é verdade se a medição usar **as perguntas dele**.
Um usuário não-técnico não escreve JSONL. Então: depois de uma busca ruim no
estágio 2, um botão "o certo era este arquivo" com um seletor de arquivo grava a
pergunta no conjunto dourado **daquela base**, com autoria marcada.

Isso é o item de maior valor da fase inteira, e é o único que faz o painel ser
mais que cosmética: a partir dele, os perfis do estágio 1 passam a ser medidos
contra o acervo e as perguntas de quem está usando, não contra as minhas 45. Uma
base de trabalho recém-criada é justamente o caso em que nenhum número anterior
vale, porque nem o acervo nem as perguntas são os mesmos.

Com poucas perguntas o número é ruidoso, e a tela diz isso em vez de exibir três
casas decimais sobre `n = 4`: abaixo de um mínimo declarado, mostra a contagem e
o aviso, não a média.

## 6. Stack — o mais simples que atende

**Starlette + um arquivo HTML, servido em `127.0.0.1`, aberto no navegador por
`py -m segundocerebro.painel`.** Sem npm, sem build, sem framework de front.
Controles nativos (`<input type=range>`), CSS moderno num arquivo, `fetch` puro
para as chamadas.

> **Correção de 15/08/2026: era FastAPI.** Ao conferir o ambiente antes de
> escrever, `starlette`, `uvicorn` e `httpx` já estavam instalados — vêm com o
> pacote `mcp`. O painel passa a custar **zero dependência nova** exceto o
> escritor de TOML, e a história de instalação continua sendo
> `pip install -r requirements.txt`. O que a FastAPI acrescentaria — validação
> por pydantic e OpenAPI — não paga dez dependências transitivas numa tela de
> configuração local de um usuário só.

Por que esta e não as alternativas:

| Opção | Por que não |
|-------|-------------|
| FastAPI | Traz pydantic e um punhado de dependências para dar validação e OpenAPI que esta superfície não usa. O Starlette que já está instalado entrega roteamento, JSON, arquivos estáticos, SSE e `TestClient` |
| Streamlit / Gradio | Mais rápido de escrever, e erra o alvo: são ferramentas de dashboard, com modelo de re-execução a cada interação que atrapalha justamente o fluxo ajustar → medir → salvar. Dependência pesada, aparência genérica, e o botão "Salvar desligado até medir" fica desconfortável |
| React/Vite + API | Acrescenta npm, build e um segundo ecossistema de teste a um repositório 100% Python, para uma tela de configuração de um usuário. Custo permanente, ganho estético |
| TUI (Textual) | O pedido é uma tela para quem não abre terminal |
| Tauri / Electron | Empacotamento de app desktop para resolver um formulário |

O que a escolha preserva: `pip install -r requirements.txt` continua sendo a
história de instalação inteira; os testes do painel entram no mesmo `pytest` dos
outros 200, via cliente de teste do FastAPI; e o painel morre sem afetar nada,
porque não está no caminho de consulta.

## 7. Onde entra no ROADMAP

*Escrito no ROADMAP em 14/08/2026 como **F3.5 — Bases e painel de ajuste**, com
os três blocos (A: núcleo de configuração, B: bases, C: painel) e cinco critérios
de saída. O que segue é o raciocínio da posição; a lista de entregas está lá.*

Depois de a F3 fechar o critério de saída (segundo cliente validado e traço
multi-hop registrado) e **antes da F2**.

Meia fase em vez de renumerar: F4 e F5 são citadas em `ARCHITECTURE.md`, no
`CLAUDE.md`, no conjunto dourado e em meia dúzia de docs de medição. Renumerar
custa mais do que informa.

Antes da F2 pelo mesmo argumento que já inverteu F2 e F3 em 13/08: otimizar
precisão antes de saber se o gargalo é precisão contraria a regra de não
otimizar sem número. O painel é o instrumento que produz esse número no acervo
real — e a F2 chega numa superfície de configuração que já existe, em vez de
criar mais constantes para retrofitar.

Ordem interna: A antes de B antes de C, e cada bloco é útil sozinho. O `--base`
em linha de comando funciona antes de existir qualquer tela — o que permite ao
usuário separar pessoal e trabalho sem esperar o painel ficar pronto.

## 8. Invariantes novas, escritas no CLAUDE.md

> **6. O painel de ajuste está fora do caminho de consulta.** Ele lê e grava
> configuração; não recupera, não ranqueia, não gera texto e não é requisito de
> execução. O servidor MCP funciona com o painel desinstalado — e existe teste
> que prova isso.
>
> **7. Isolamento entre bases é físico, não filtro.** Cada base tem seu
> diretório de índice e seu processo de servidor. O campo `raiz` do registro é
> procedência, **não** fronteira de isolamento.

## 9. Armadilhas previstas

- **"Mexi no controle e nada mudou."** O servidor guarda `BuscaHibrida` em
  memória com os pesos fixados na construção. Sem releitura por mudança de
  `mtime` do arquivo de configuração, o painel mente. Pesos são floats: reler
  não custa nada. Os parâmetros de índice, obviamente, não recarregam — e a tela
  precisa dizer qual é qual
- **Porta local sem autenticação.** O painel mostra trecho de documento. Bind em
  `127.0.0.1` com token na URL de abertura; qualquer processo local alcança uma
  porta aberta
- **Log de trecho.** O painel não registra conteúdo de documento em log —
  mesmo motivo de LGPD que vale para o índice
- **Seletor de arquivo e caminho longo.** 34 arquivos do acervo passam de 260
  caracteres. O seletor tem que aceitá-los e gravar o caminho relativo
  canônico, ou a pergunta entra no conjunto dourado apontando para nada
- **Medir com o índice ocupado.** Reindexação e eval no mesmo índice ao mesmo
  tempo: o painel precisa ver a trava de indexação e desabilitar "Medir" com
  motivo à mostra, em vez de falhar
- **Base errada, silenciosamente.** `--base` ausente com duas bases
  configuradas não pode cair num padrão: tem que ser erro. Indexar a base
  pessoal por cima do índice de trabalho é caro de descobrir e caro de desfazer.
  Com uma base só, o padrão é ela — a ambiguidade é que é erro, não a omissão
- **Duas bases apontando para o mesmo diretório de índice.** Validação de
  carregamento, não descoberta em produção: dois `indice` iguais, ou um contido
  no outro, param o carregamento com mensagem que nomeia as duas bases
- **Raízes que se sobrepõem entre bases.** Legítimo (uma pasta pode estar nos
  dois acervos) e caro: o documento é indexado e embeddado duas vezes. O painel
  avisa quando detecta sobreposição, sem impedir
- **A descrição da base como enfeite.** Se o usuário escrever "minha base" nas
  duas, o roteamento por descrição vira sorteio. A tela pede a descrição com
  exemplo à vista, e avisa quando duas bases registradas têm descrições
  indistinguíveis

## 10. Fora de escopo desta fase, registrado

| Item | Motivo |
|------|--------|
| UI de consulta / chat | Invariantes 1 e 2. É o cliente MCP que consulta |
| Painel multiusuário ou remoto | F5, junto de ACL e auditoria |
| Ajuste automático de pesos | A varredura já existe em CLI. Automatizar a escolha sem olhar as armadilhas é comprar média entregando o subconjunto que a fase existe para resolver |
| Editar o conjunto dourado além de acrescentar | Apagar pergunta medida invalida comparação histórica |
