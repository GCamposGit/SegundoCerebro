# A afinidade de CPU não custa 12× — o estado da máquina custa 22×

**Data:** 27/08/2026 · **Máquina:** notebook corporativo, i7-1355U (2 P-cores com
SMT + 8 E-cores = 10 físicos / 12 lógicos), Windows 11 · **Modelo:** `e5-large`,
`threads=6`, `ritmo=1.0`, chunk de 31 tokens, lote=1 · **Corpus:** nenhum — texto
fixo de vocabulário VCE, é medição de encoder, não de acervo.

Este documento **retrata** a conclusão causal do achado 16.1 de
[`spec-estimativa-v2.md`](spec-estimativa-v2.md) §16. O número que ele reportou
existe; a causa que ele atribuiu, não. E a minha primeira hipótese substituta
também foi refutada — está registrada abaixo porque foi refutada, não apesar
disso.

---

## O que o 16.1 afirmou, e o que sobra dele

Afirmou: a máscara de afinidade do perfil `normal` (`[0,1,2,3,4,5]`) custa **12×**
contra máscara nenhuma, e a causa suspeita era a ONNX Runtime fixar a afinidade
das próprias threads intra-op e várias caírem no mesmo processador lógico. Daí a
recomendação implícita: consertar a máscara, ganhar ~12× de vazão.

Sobra o **número**, e nada da causa. A mesma máscara, no mesmo braço, com o mesmo
comando, mede **0,141 s/chunk e 3,19 s/chunk** conforme um estado da máquina que o
indexador não observa e a tabela `medicoes` não registra.

## O protocolo, porque sem ele não haveria achado

Um braço por processo (a threadpool do ORT e a afinidade são fixadas na criação
da sessão), braços **intercalados** A/B/A/B dentro de cada janela, e estado de
energia gravado antes e depois de cada braço. Nenhum arquivo do produto foi
tocado para medir; o harness está versionado em `eval/regime.py`, e é ele que
**recusa** contraste com menos de duas réplicas por braço em vez de devolver um
número plausível.

Foi o intercalado que pegou o erro, não o raciocínio. Rodando os braços em
sequência — um bloco de `pre`, depois um bloco de `pos` — eu já tinha uma tabela
coerente e uma causa plausível. Ela era artefato da ordem dos blocos.

## As quatro janelas

`livre` = 12 lógicos, sem máscara. `contiguo6` = `[0..5]`, o que o perfil `normal`
aplica hoje. Medianas de 8–10 chunks, s/chunk.

| janela | energia | `livre` | `contiguo6` |
|---|---|---:|---:|
| 1 | tomada | 0,198 | 0,180 |
| 2 | bateria | 0,409 · 0,370 | **3,170 · 3,097** |
| 3 | tomada | 0,142 · 0,135 | 0,141 · 0,165 |
| 4 | bateria | 0,170 · 0,189 | 0,182 · 0,177 |

Na janela 2 os dois braços **alternam** — `livre` rápido, `contiguo6` lento, duas
vezes cada. Deriva monotônica (térmica, bateria descarregando, carga crescente)
não produz isso. Dentro daquela janela o efeito da máscara é real e vale **8,0×**.

Fora dela, o efeito da máscara é **zero**: 0,141 contra 0,142 na janela 3.

## Três hipóteses refutadas

**(a) A ordem da chamada.** `esforco.aplicar()` é chamado em dois lugares: no
arranque (`indexer.py:1665`, antes do `Embedder`, que é `lazy=True` — a sessão do
ORT nasce depois da máscara) e **entre lotes** (`indexer.py:925`, com a sessão
quente). O segundo dispara quando `ajustar_ao_vivo` muda o perfil **ou só o
`lote_embed`**, o que num run longo acontece. Hipótese: reaplicar máscara sobre
threadpool viva apaga o pinning que o ORT instalou.

Refutada. Intercalado, na mesma janela: `pre` 3,087 · 3,128 contra `pos` 2,769 ·
2,665 — o `pos` é ligeiramente **mais rápido**. Reaplicar a mesma máscara também
não muda nada. A ordem não é a alavanca.

**(b) Bateria contra tomada.** A janela 2 era bateria e a 3 tomada, o que fechava
bem — e a energia é a variável que este repositório já sabe que importa
(`na_bateria()` existe por isso). Refutada pela janela 4: bateria, e os dois
braços empatam em 0,18.

**(c) Térmico.** Carga sustentada de 200 s em `contiguo6`, dez blocos: 3,19 ·
3,23 · 3,00 · 3,06 · 3,04 · 3,09 · 3,24 · 3,16 · 3,29 · 3,14. Não degrada — já
**começa** lento. E sessenta segundos depois, mesma máquina, mesma bateria, mesmo
braço: 0,19. Não há rampa; há um estado que liga e desliga em minutos.

## O mecanismo, que os dados já continham

Quatro braços da **mesma** janela lenta:

| máscara | lógicos | s/chunk |
|---|---:|---:|
| `pcores4` `[0,1,2,3]` — só P-core | 4 | **0,534** |
| `contiguo6` `[0..5]` — 4 de P-core + 2 de E-core | 6 | **2,758** |
| `ecores8` `[4..11]` — só E-core | 8 | 0,377 |
| `livre` — tudo | 12 | 0,390 |

Uma máscara com **mais** núcleos, que contém todos os do `pcores4`, é **5×** mais
lenta que ele. Isso fecha de um jeito só: **no estado lento o sistema operacional
só agenda este processo nos E-cores.** Com `[0..5]` sobram dois deles (LP 4 e 5) e
os quatro lógicos de P-core ficam ociosos. O `pcores4` é imune porque não tem
E-core para onde ir — a máscara vence e o processo fica nos P-cores. E `livre`
mede igual a `ecores8` (0,390 contra 0,377) porque é isso que ele recebe na
prática.

É a assinatura de **Efficiency Mode / EcoQoS** do Windows 11, que agenda processo
de segundo plano em E-core. As bordas das janelas coincidem com o usuário mexendo
na máquina (ligar na tomada, responder pergunta) — o que é consistente, e **não é
prova**: o gatilho não foi isolado, e por isso o estado lento ainda **não é
reproduzível sob comando**. Essa é a lacuna, e é a primeira coisa do pacote.

## O que isto muda para quem instala amanhã

Direto, e não é do nosso acervo: **num notebook Windows — que é a máquina do
leigo — a indexação varia 22× por um estado do sistema operacional que o produto
não observa, e o perfil padrão `normal` é o que converte esse estado de 2× em
16×.** Sem máscara o mesmo estado custa ~2× (0,19 → 0,39); com a máscara de hoje,
~16× (0,18 → 3,1).

E a máscara não está pagando por isso: no estado benigno ela não dá ganho nenhum
que apareça no número, e `ritmo` (ciclo de trabalho) e prioridade já existem para
o mesmo fim — deixar a máquina usável.

## Consequência para a passada de calibragem — ela não pode rodar ainda

A `Calibracao` aprende `s/chunk` por formato e por perfil a partir de observações
de run real. Se o estado da máquina muda o custo por 22× e não entra na chave da
observação, a calibragem **agrupa observações incomparáveis** e o coeficiente que
sai não descreve nem um regime nem o outro. Não é ruído que o encolhimento
resolve: é viés, com milhares de observações a favor.

A precedência que o plano de 27/08 dava à afinidade sobre a calibragem estava
certa. A razão era outra: não é que a máquina esteja "artificialmente 12× lenta" e
o conserto a acelere — é que **a máquina tem dois regimes e a `medicoes` não sabe
em qual deles estava**.

## O pacote, em ordem, e o que não fazer

1. **Tornar o estado observável e reproduzível.** Registrar em toda observação:
   tomada/bateria, e a classe de eficiência efetiva do processo. Achar o gatilho
   do EcoQoS (foco de janela? processo pai em segundo plano? `nice`?) até o estado
   lento poder ser ligado sob comando. **Sem isso nada abaixo é mensurável.**
2. **Não agrupar observações de regimes diferentes** na `Calibracao` — regime
   entra na chave, ou a observação do regime lento é descartada e declarada.
3. **Só então escolher a máscara.** O candidato que os números sugerem e que
   **não foi medido** é uma máscara que preserve E-cores em vez dos primeiros
   lógicos — para 6 de 12, algo como `[0,2,4,5,6,7]` (2 de P-core + 4 de E-core)
   em vez de `[0..5]`. Ele deve ficar perto do ótimo nos dois regimes, e é
   exatamente isso que falta provar. `alternado6` `[0,2,4,6,8,10]` **não** serve:
   1,236 no estado lento, 3× pior que `livre`.
4. **Efeito mínimo, declarado antes:** a máscara escolhida tem de ficar em ≤1,5×
   do `livre` **no estado lento** e ≤1,1× do `contiguo6` no estado benigno. Não
   atingindo os dois, a decisão passa a ser remover a máscara e deixar a
   usabilidade com `ritmo` + prioridade — e aí o pacote precisa de uma medição de
   responsividade, que hoje não existe.
5. **Empate encerra.** Se a máscara candidata empatar com `[0..5]` no estado
   lento, registra-se "hipótese refutada" e o pacote vira só a remoção.

**Não** varrer grade de máscaras. **Não** trocar a máscara antes do item 1: sem o
estado reproduzível, qualquer braço mede a janela e não a máscara — que é
precisamente o erro que este documento retrata.

## A classe, e o que passa a pegá-la (regra 12)

O caso é a afinidade. A classe é maior:

> **Medição de velocidade cujo braço não fixa nem registra o regime de energia e
> de agendamento do sistema operacional mede a janela, não o braço.**

O remendo seria consertar a máscara. A generalização é o instrumento: **nenhum
número de velocidade sai deste projeto sem o estado gravado junto, e nenhum
contraste de velocidade vale sem braços intercalados dentro da janela.** É a
extensão natural da regra 7 da §4 de [`colaboracao.md`](colaboracao.md) — "número
sem corpus, sem máquina e sem data é mentira" — com **estado** ao lado de máquina;
e a lição de latência que já dizia "máquina nomeada e estado térmico" passa a
valer para **vazão**, onde a variação é 22× e não 1,6×.

Isto retrata também o meu próprio erro de método: a tabela coerente que eu tinha
depois de dois blocos sequenciais era artefato da ordem dos blocos, e ela
sobreviveria a qualquer revisão que olhasse só os números.

## R.1 — o gatilho isolado (02/09/2026, 14700HX)

**Máquina:** notebook, Intel 14700HX (8 P-cores com SMT + 12 E-cores = 20
físicos / 28 lógicos), Windows 11, **tomada**, bateria 100%. **Não** é o 1355U:
os 3,19 vs 0,141 s/chunk da tabela acima ficam lá. Aqui o efeito mínimo era
ligar e desligar o estado lento por comando, e o `contiguo6` reproduzir o par
nesta CPU.

### Topologia, porque copiar a máscara copiaria o erro

O Windows enumera os P-cores primeiro. Classificar por `EfficiencyClass` **mente
neste processador**: os P-cores reportam classe 1 e os E-cores classe 0, o
contrário do MSDN. A regra que sobrevive é o SMT — núcleo com dois lógicos é
P-core.

| classe | lógicos | o que é |
|---|---|---|
| P | 0–15 | 8 núcleos com SMT |
| E | 16–27 | 12 núcleos sem SMT |

`contiguo6` = `[0..5]` = **três P-cores, zero E-cores**. O perfil `normal` do
produto pega os primeiros 14 lógicos — ainda só P-core. A assinatura do 1355U
(máscara `[0..5]` com 4 lógicos de P + 2 de E, EcoQoS estacionando nos dois E)
**não existe nesta topologia**. Isolar o gatilho não é reproduzir aquele
número.

### O gatilho

`SetProcessInformation(ProcessPowerThrottling, EXECUTION_SPEED)` — EcoQoS /
Efficiency Mode. Liga e desliga neste processo. `GetProcessInformation` lê de
volta. Sem `argtypes` no ctypes, o HANDLE de 64 bits vira `c_int`, a chamada
falha em silêncio, `ecoqos` sai `None` e o contraste devolve 1,1× — número
plausível, gatilho morto. O instrumento **recusa** braço `contiguo_on` /
`contiguo_off` cujo estado não bate com o pedido.

### O par, intercalado, sob comando

```
py -m eval.regime --contraste-ecoqos --sonda --nucleos 6 --replicas 2 --chunks 3
```

`--sonda` é um laço de CPU (800 000 `sin`), sem encoder. O gatilho é do
agendador, não do ORT; carregar o `e5-large` mediria o mesmo eixo com 2 GB a
mais. Veredito `medido`, ressalva nenhuma, tomada o tempo todo:

| braço | réplica 1 | réplica 2 | mediana | razão |
|---|---:|---:|---:|---:|
| `contiguo_off` | 0,0365 | 0,0365 | **0,0365** | 1 |
| `contiguo_on` | 0,1361 | 0,1354 | **0,1357** | **3,72×** |

As duas réplicas lentas intercalam com as duas rápidas. Não é deriva. O estado
lento liga e desliga por comando nesta CPU.

Código: `src/segundocerebro/index/regime_maquina.py` (observar e aplicar),
`esforco.observar_regime()` (relato, sem crescer `aplicar`), `eval/regime.py`
(`--ecoqos`, `--contraste-ecoqos`, `--sonda`). Testes em
`tests/test_regime_maquina.py` e `eval/test_regime.py` — nenhum carrega modelo.

R.2 e R.3 destravam. R.3 **não** pode assumir que os primeiros N lógicos misturam
P e E: nesta máquina, não misturam.
