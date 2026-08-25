# A regra de ouro — o produto é para uma base desconhecida

**Decisão do usuário em 25/08/2026.** Este arquivo tem precedência sobre qualquer
prioridade herdada de dossiê, guia ou fila de pacotes. Em conflito, ele vence, e
quem discordar muda *este* arquivo primeiro.

> **O sistema é para um leigo, no Windows dele, apontando uma pasta que nós nunca
> vimos.** Não é para o nosso acervo corporativo, não é para o corpus da VCE e não
> é para o revisor sênior que clona o repositório.

A régua já estava escrita no plano — *"o alvo do produto é acervo genérico em
máquina desconhecida"* ([`ROADMAP.md`](../ROADMAP.md), decisão de 24/08) — e não
era ela que governava a fila. Este arquivo existe para que governe.

---

## Por que isto virou documento

Três mecanismos, medidos neste repositório, faziam o trabalho derivar para dentro
do acervo conhecido. Nenhum deles é falta de rigor; dois são rigor aplicado à
pergunta errada.

1. **O contexto era o viés.** O `CLAUDE.md` tinha 688 linhas e 79% delas eram
   crônica de pacote fechado no acervo corporativo. Quem abre a sessão lendo
   trinta blocos de ablação local **continua a crônica**. A crônica foi para
   [`historico-decisoes.md`](historico-decisoes.md), íntegra.
2. **Não havia regra de parada antes de medir.** O `E5` entregou o intervalo, mas
   ele era consultado *depois* da varredura. O `C3.a` pôs 18 braços na mesa para
   concluir "nada mudou de configuração", com amplitude medida (0,005–0,012) um
   décimo da largura do intervalo do agregado (0,203). O intervalo dizia isso
   antes.
3. **As portas eram do acervo, não do produto.** As cinco portas da F1, a porta 3
   e o alvo da `F4-P` saem todos do dourado corporativo — a base que, por decisão
   de 24/08, deixou de ser autoridade. Nenhuma porta reprovava "não instala em
   máquina desconhecida", "acervo com nomes tipo `Scan_001.pdf`" ou "base sem PDF
   legível".

---

## As três perguntas antes de abrir a branch

Vão no cabeçalho do pacote e no corpo do PR. Pacote que não as responde não
começa — e responder "não sei" é resposta válida que **adia** o pacote, não que o
libera.

1. **Que defeito isto conserta para quem instala amanhã, numa base que não
   conhecemos?** Se a resposta só existe em termos do nosso acervo ("sobe o MRR de
   reunião"), o pacote é de laboratório: pode entrar, declarado como tal, atrás de
   qualquer item de produto.
2. **Qual é o efeito mínimo que faria valer, e o instrumento vê esse efeito nessa
   fatia?** Número declarado antes, com a fatia declarada antes
   ([`rigor-estatistico.md`](rigor-estatistico.md)). Se o efeito esperado é menor
   que o ruído medido da fatia, o pacote **não se mede**: registra-se a conta e
   encerra.
3. **Se der empate, o que a gente faz?** A única resposta aceita é *encerra e
   registra*. "Meça mais" não é resposta — é a fase inteira outra vez.

---

## As três regras que isto instala

Estão numeradas em [`colaboracao.md`](colaboracao.md) §4 como 10, 11 e 12, junto
das outras, porque é lá que o outro setup as lê.

### 10. Ganho de um acervo não vira `[padrao]`

Medido num acervo só, o ganho é **daquele** acervo. Ele entra como uma de três
coisas, nunca como fábrica:

- **`[[base]]` opcional**, desligada por padrão, documentada;
- **prior do autotune** (`R6.1`), que é onde peso por base é a arquitetura e não o
  remendo;
- **espera o segundo acervo** — o sintético do `E1`, o benchmark do `C5`, ou uma
  base real nova.

**Exceção declarada, e é a que explica a F2:** mudança de **custo zero por
consulta** e estruturalmente independente de acervo pode ir para o padrão com um
acervo só. Famílias de versão e glossário de siglas — os dois maiores ganhos da
F2, +0,044 e +0,033 — são exatamente desse tipo, e o reranking, que custa 6,8×,
não é. A regra não é nova: ela nomeia por que aqueles dois foram os certos.

### 11. Hipótese sem efeito mínimo declarado não gera varredura

Uma medição por hipótese. O veredito sai de `eval.comparar` (Δ pareado ± IC95), e
**empate encerra o pacote** com "hipótese refutada" no doc. Não se reabre sem
**instrumento novo** (fatia que não existia, n maior) ou **acervo novo** — nunca
por intuição de que "desta vez vai".

Porta refutada não volta: a porta 3 já foi varrida três vezes (13/08, tabela da
F2, `C3.a`). A quarta precisa de acervo novo, não de outra grade.

### 12. Defeito se generaliza, não se remenda

**Todo defeito achado em teste ou em medição tem de sair do pacote como classe, e
não como caso.** O conserto pontual entra junto, mas ele não é a entrega: a
entrega é a mudança de método que faz a classe inteira ser pega na próxima vez —
um teste que confere contrato, uma distribuição que se olha, um instrumento que
mede o que o produto executa.

O padrão está escrito no repositório, dos dois lados:

| Defeito achado | Remendo (insuficiente) | Generalização (a entrega) |
|---|---|---|
| `eval.comparar` quebrava por quatro campos faltando | completar a lista | `_CAMPOS_DE_MONTAGEM` conferido em teste contra o código-fonte de `rodar._montar` — a próxima fase quebra o teste, não a porta |
| cinco grafias de identificador não ligavam no grafo | corrigir as cinco | olhar a **distribuição real** de identificadores; nenhum dos cinco tinha sido pego por teste unitário |
| `schtasks` mockado passava contra comando que a máquina recusa | consertar o mock | **mock de utilitário do sistema não prova permissão** — rodar de verdade, de `C:\Windows\System32` |
| chunk de 82 caracteres em email com URL longa | tratar aquela URL | medir chunk com o **tokenizador real**; o teste dizia 19 onde havia 1.850 |
| o eval media `search`, o cliente executa `buscar_chunks` | medir os dois | **conferir qual caminho o produto executa antes de afinar peso nele** — virou `eval/entregue.py` |

A pergunta de fechamento de todo pacote passa a ser: *qual classe de defeito
ficou fechada, e qual teste ou método passa a pegá-la sozinho?* Sem essa linha o
PR não fecha. Defeito que só some no nosso acervo volta na base do usuário.

---

## A régua de prontidão — o que conta como evidência

Nenhum item abaixo é recall@1 do dourado corporativo. Este é o conjunto que
define "é produto"; o dourado real entra como o último item, e só como piso.

1. **Instala frio.** Máquina sem o nosso `config.toml`, `pip install`, sem
   `PYTHONPATH`, sem saber o que é `sm_52` (F6-A, F6-C).
2. **Sobrevive a pasta estranha.** Nome ruim, caminho acima de 260 caracteres,
   placeholder de nuvem, arquivo travado pelo Word, planilha sem cache de
   fórmula, PDF sem texto, Office legado. Falhar é aceitável; **travar ou mentir
   em silêncio, não**.
3. **Devolve procedência.** Arquivo + seção + id estável em todo retorno
   (invariante 5), no caminho que o cliente executa.
4. **Cabe no orçamento de latência** da máquina nomeada
   ([`porta-de-latencia.md`](porta-de-latencia.md)).
5. **Generaliza.** O ganho se repete em ≥2 acervos, ou é de custo zero e
   estruturalmente independente (regra 10).
6. **Não derruba o piso.** `dourado-v1` congelado como regressão — nunca como
   autoridade que escolhe arquitetura.

---

## O que isto **não** muda

O rigor não é o problema: é o que permite parar cedo. Seguem intocados o `E5` e a
regra de adoção por IC pareado, "sem número antes e depois a mudança não entra"
(invariante 4), o `dourado-v1` como piso, a procedência em todo retorno e as sete
invariantes do `CLAUDE.md`.

O que muda é **o que se mede, e quando se para de medir**.
