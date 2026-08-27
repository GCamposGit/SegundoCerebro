# Começar — do zero à primeira pergunta

O Segundo Cérebro procura dentro dos **seus** documentos e devolve o trecho com o
nome do arquivo e a seção de onde ele saiu. Ele não escreve resposta: quem escreve
é o assistente que você já usa (Claude, Grok). Nada sai da sua máquina, e não há
cobrança por pergunta.

No fim desta página você pergunta *"o que o contrato CT-VCE-2024-0142 diz sobre
reajuste?"* no seu assistente e recebe o parágrafo, com o arquivo em que ele está.

Se travar em algum passo, pule para [Quando não funciona](#quando-não-funciona).
Nada aqui apaga, move ou altera os seus documentos — o programa só lê.

---

## O que você precisa antes

- **Windows** (o resto também funciona, mas foi aqui que se mediu).
- **Python 3.12 ou mais novo.** Baixe em [python.org](https://www.python.org/downloads/)
  e, no instalador, marque **"Add python.exe to PATH"**. Para conferir, abra o
  PowerShell e digite:

  ```bash
  py --version
  ```

  Tem de aparecer `Python 3.12` ou maior. Se aparecer uma tela da Microsoft Store,
  o Python não está instalado — instale pelo site.
- **Um assistente com suporte a MCP**: Claude Desktop, Claude Code ou Grok.
- **Espaço em disco**: o programa é pequeno; o que ocupa é o modelo de busca,
  baixado uma vez. Medido nesta máquina: **2,1 GB** o modelo padrão (`e5-large`)
  e **241 MB** o pequeno (`minilm`). Mais o índice, que cresce com o seu acervo —
  o painel não estima disco, então deixe folga.

---

## 1. Instalar

Baixe o projeto e instale as dependências. No PowerShell, na pasta onde você quer
que ele fique:

```bash
git clone https://github.com/GCamposGit/SegundoCerebro.git
```

```bash
cd SegundoCerebro
```

```bash
py -m pip install -e .
```

O último comando demora alguns minutos: ele traz as bibliotecas de leitura de PDF
e de busca. Sem `git` instalado, use o botão **Code → Download ZIP** na página do
projeto e descompacte.

Os modelos de busca **não** vêm nesse download: eles são baixados na primeira
indexação, uma vez só, e ficam guardados na pasta `models/`.

---

## 2. Abrir o painel

```bash
py -m segundocerebro.painel
```

Ele abre o navegador em `127.0.0.1` — um endereço que só existe dentro do seu
computador. A URL vem com uma chave; não é preciso decorá-la, e ninguém de fora
alcança essa página.

> **Se aparecer "o termo 'segundocerebro-painel' não é reconhecido"**
>
> Há um atalho de mesmo nome, e em muitas instalações do Windows ele **não
> funciona** — o `pip` põe o atalho numa pasta que o PowerShell não procura.
> Isto foi medido, não é teoria: nesta máquina os quatro atalhos existem e
> nenhum é encontrado pelo nome.
>
> **A solução é usar sempre a forma `py -m ...`**, que é a que está nesta página
> e funciona de qualquer pasta. Não é gambiarra e não perde nada: é o mesmo
> programa. Se você prefere o atalho curto, acrescente ao PATH a pasta que este
> comando imprime:
>
> ```bash
> py -c "import sysconfig; print(sysconfig.get_path('scripts'))"
> ```

---

## 3. Dizer onde estão os seus documentos

No painel, clique em **Nova base**. Uma "base" é um acervo: um conjunto de pastas
com índice próprio, separado dos outros. Preencha:

| Campo | O que escrever | Exemplo |
|---|---|---|
| Identificador | um apelido curto, sem espaço nem acento | `trabalho` |
| Nome | como você chama esse acervo | `Várzea Clara Energia` |
| Descrição | **o que tem aí dentro** | `Contratos, propostas e atas da VCE` |
| Pastas | os caminhos completos, separados por `;` | `C:\Users\voce\VCE\Documentos` |

A **descrição não é enfeite.** É o que o assistente lê para decidir se vale
procurar nesta base. Se você ligar duas bases no mesmo assistente — uma do
trabalho e uma pessoal —, a descrição é o único sinal que ele tem para escolher.
Escreva o que um colega precisaria ouvir para saber quando perguntar aqui.

Clique em **Ver o que tem nas pastas**. Isso é rápido, só olha nomes e tamanhos, e
responde a pergunta que importa antes do compromisso: quantos arquivos há, de quais
tipos, e quanto tempo a indexação vai levar. Depois, **Criar base**.

**Duas bases, não uma só com tudo dentro**, se o acervo do trabalho e o pessoal
não devem se misturar. A separação é física — pastas de índice diferentes — e é o
único jeito de garantir que uma pergunta em um contexto não alcance o outro.

---

## 4. Indexar, e esperar a barra

Clique em **Indexar**. Agora é hora de fazer outra coisa: o programa abre cada
documento, corta em trechos e calcula a representação de busca de cada trecho.

O painel mostra a barra, o documento em curso e a estimativa que falta. Pode
**Pausar** e **Continuar** sem perder o andado, e pode fechar o painel — a
indexação segue, e ao reabrir a barra está onde parou. Se o computador desligar no
meio, o próximo comando retoma de onde parou em vez de começar de novo.

Da segunda vez em diante é rápido: só entra o que mudou. **Não existe** vigilância
automática ainda — quando você acrescentar documentos, rode **Indexar** outra vez.

Quem preferir o terminal:

```bash
py -m segundocerebro.index.indexer --base trabalho
```

Uma referência de tamanho, medida nesta máquina: 11 documentos e 18 trechos em
31 segundos, com o modelo pequeno. Acervo de milhares de arquivos com PDF grande
se mede em horas, e o painel diz quantas antes de você começar.

---

## 5. Ligar no seu assistente

Quando a indexação termina, o programa **já registra a base** no arquivo
`.mcp.json` da pasta do projeto. Isso basta para o **Claude Code** e para o
**Grok** abertos nessa pasta: recarregue o cliente e a busca aparece.

Para o **Claude Desktop**, que abre em outro lugar, um comando:

```bash
py -m segundocerebro.mcp.registrar --cliente claude-desktop --instalar
```

Ele grava no arquivo de configuração do Claude Desktop **somando**, sem apagar os
outros serviços que você já tenha lá, e diz na tela o que mudou. Depois **feche e
reabra o Claude Desktop** — ele lê essa configuração só ao abrir.

Sem `--instalar`, o comando imprime o trecho na tela para você colar em qualquer
outro cliente.

**Ligue em cada assistente só a base que aquele contexto deve alcançar.** Registrar
apenas a base pessoal num projeto é uma fronteira de verdade: a ferramenta não
existe naquela sessão. Registrar as duas e confiar que o assistente escolhe certo é
comodidade, não garantia.

---

## 6. Perguntar

No assistente, pergunte em português comum:

> *O que o contrato CT-VCE-2024-0142 diz sobre reajuste?*

**A primeira pergunta demora** — meio minuto com o modelo pequeno, cerca de um
minuto e meio com o padrão, porque ele está sendo carregado na memória. As
seguintes respondem em fração de segundo. Se o assistente aparecer conectado e a
primeira busca parecer travada, é isso; espere.

Toda resposta traz **de onde veio**: o nome do arquivo e a seção. Confira. É a
diferença entre uma citação e um palpite bem escrito — e o motivo pelo qual você
pode abrir o documento e checar.

Três coisas que vale saber pedir:

- **"me mostra o que tem em volta desse trecho"** — quando o parágrafo parece
  cortado no meio.
- **"que outros documentos citam essa norma?"** — puxa documentos ligados pelo
  mesmo código de contrato, norma ou processo, mesmo quando eles não têm nenhuma
  palavra em comum com a sua pergunta.
- **"não achou; procura por outro termo"** — o assistente refaz a busca. Ele tem as
  peças; o raciocínio é dele.

---

## Quando não funciona

| O que você vê | O que é | O que fazer |
|---|---|---|
| `'segundocerebro-painel' não é reconhecido` | o atalho não está no PATH | use `py -m segundocerebro.painel` (veja o passo 2) |
| tela da Microsoft Store ao digitar `py` ou `python` | o Python não está instalado | instale pelo [python.org](https://www.python.org/downloads/), marcando "Add python.exe to PATH" |
| `ModuleNotFoundError: segundocerebro` | o `pip install -e .` não rodou, ou rodou noutro Python | repita o passo 1 dentro da pasta do projeto |
| o assistente diz **"servidor não conecta"** | quase sempre é o caso de cima | rode `py -m segundocerebro.mcp.server --base trabalho` no PowerShell: a mensagem de erro real aparece ali |
| a base não aparece no Claude Desktop | ele lê a configuração só ao abrir | feche e reabra o aplicativo inteiro |
| a primeira pergunta parece travada | é o modelo carregando | espere até um minuto e meio |
| a busca não acha um documento que você sabe que existe | ele pode ter ficado fora | veja abaixo |

**Documento que ficou de fora.** A indexação anota, por arquivo, o que aconteceu
com ele: lido, vazio, aberto em outro programa, ainda na nuvem, formato sem
leitor, ou erro. Nada entra no índice como se tivesse texto quando não tem. Se um
documento não aparece nas buscas, a causa está nesse registro — o painel mostra e
o motivo mais comum é o de baixo.

---

## O que ele ainda não faz

Preferimos dizer isto do que deixar você descobrir depois.

- **PDF digitalizado.** Sem o extra de OCR, a foto da página fica registrada
  como vazio — não some em silêncio. Com `pip install segundocerebro[ocr]` e
  `py -m segundocerebro.index.indexer --ocr`, o texto da imagem entra no
  índice **depois** dos documentos que já têm camada de texto. Sem o extra,
  o resto da indexação não muda.
- **Não vigia as pastas.** Documento novo só entra quando você rodar a indexação
  outra vez.
- **Só estes formatos:** PDF (`.pdf`), Word (`.docx`, `.docm`, `.doc`, `.rtf`),
  Excel (`.xlsx`, `.xlsm`, `.xls`), PowerPoint (`.pptx`, `.pptm`, `.ppt`), e-mail
  (`.msg`, `.eml`) e texto (`.txt`, `.md`, `.markdown`, `.csv`). O que está fora
  fica marcado como "sem leitor" — não desaparece sem aviso.
- **Não escreve texto, de propósito.** Não existe "resume isto" no servidor. Uma
  etapa de geração aqui passaria a custar dinheiro por pergunta e amarraria você a
  um fornecedor. Quem escreve é o assistente que você já paga.
- **Um usuário.** Não há login, não há vários usuários, não há servidor em rede.
  Ele roda na sua máquina e só ela o alcança.

---

## E depois

O painel tem mais do que a criação de base: dá para escolher entre precisão e
velocidade com medida na tela em vez de palpite, ver por que uma pergunta trouxe o
que trouxe, e **ensinar** — quando ele erra, você aponta o arquivo certo e a sigla
que faltava. Isso está em
[`painel-de-ajuste.md`](painel-de-ajuste.md).

Detalhes de como ligar em cada cliente, e o que cada ferramenta devolve, em
[`usar-o-mcp.md`](usar-o-mcp.md).
