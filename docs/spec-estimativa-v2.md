# Especificação — estimativa de tempo de indexação, v2

> **Status**: **implementada** em 27/08/2026, fatias 1 a 5. A §15 registra as
> oito coisas que a implementação corrigiu desta especificação — vale mais que
> o resto do documento, porque foram achadas contra código rodando.
>
> **Base empírica**: notebook corporativo, 12 núcleos lógicos, sem GPU,
> 26/08/2026, `corpus-e1` semente 42, `e5-large`, máquina ociosa. Os números
> centrais foram medidos duas vezes com divergência abaixo de 3%.
>
> Substitui a tabela de coeficientes de
> [`estimativa-de-indexacao.md`](estimativa-de-indexacao.md); **mantém** os
> quatro modos de errar que aquele documento estabeleceu — eles seguem válidos e
> a v2 não os reintroduz.

---

## 1. Por que a v1 erra — cinco defeitos, cada um com número

A v1 modela `t = SEGUNDOS_POR_DOCUMENTO + s_por_MB[ext] · MB`, com constantes
fixas e **um** fator global de correção `medido/previsto`.

**D1 — O intercepto por documento está ~350× alto e absorve custo de chunk.**
`SEGUNDOS_POR_DOCUMENTO = 15.0`. O custo fixo real por documento, medido
isolado, é **42 ms** (`tabela.add` ~40 ms + `commit` ~2 ms). Os 15 s foram
medidos no acervo corporativo, que tem 45,6 chunks por documento — o intercepto
absorveu o custo *por chunk* e virou constante que só vale naquela mistura. No
`corpus-e1` (1,32 chunk/doc) ele prevê 15 s para uma nota de 52 bytes que custa
0,18 s: **83× alto**. Em 3.530 documentos são 14,7 h de previsão contra 2,1 h
de execução.

**D2 — O fator global faz o trabalho que coeficientes por tipo deveriam fazer.**
Porque D1 infla tudo por igual, `_fator` converge para ~0,33–0,58 — foi o que os
três `progresso.json` registraram (0,3798 · 0,3317 · 0,5833). Um escalar não
corrige um erro que é **diferente por tipo**: acerta a média e erra cada tipo,
e o erro reaparece quando a mistura da pasta muda.

**D3 — `CLIP_OUTLIER = 6.0` torna o estimador estruturalmente cego ao pior
caso.** `base_fornecedores_01.csv`: 269 KB, 345 chunks, custo real ~700–884 s.
A v1 prevê `15 + 496 × 0,269 = 148 s`. A razão medido/previsto é **6,0** — em
cima da fronteira de rejeição. A observação mais informativa do acervo é
descartada da calibragem. Não é azar: um tipo cujo coeficiente está N× errado
produz razão N, e o clipe rejeita exatamente os tipos que mais precisam
aprender.

**D4 — A calibragem consome tempo de parede, e o carrega entre execuções.**
`registrar()` recebe `time.perf_counter() - comeco`, não o tempo ativo do
`Relogio`. Documento atravessado por suspensão ou por disputa de CPU entra como
custo do documento. Pior: `restaurar()` traz `previsto/medido` da execução
anterior, então a contaminação é permanente. Medido: a execução de 26/08 fechou
com `parado_segundos` 33.855 e 24 suspensões, e anunciava *"entre 4 h 8 min e
2 h 13 min"* quando faltavam **51 min**.

**D5 — `p50` e `p90` são calculados em bases diferentes, e a faixa inverte.**
Em `restante()`, `p50` sai do EMA `_p50_exibido` (amortecido, com memória) e
`p90` sai de `falta` fresco. Quando `falta` cai rápido, `p90` acompanha e `p50`
atrasa: **p50 > p90**. Foi a faixa invertida observada. A classe do defeito é
"duas estimativas da mesma grandeza calculadas sobre bases diferentes, uma
suavizada e a outra não".

---

## 2. A medição que fundamenta a v2

### 2.1 O custo do encoder é linear em tokens e não depende do tipo de arquivo

Chunks reais do índice, um por vez, `ritmo=1.0`:

| tokens | s/chunk | s/token |
|---:|---:|---:|
| 13 | 0,095 | 0,0073 |
| 63 | 0,189 | 0,0030 |
| 64 | 0,193 | 0,0030 |
| 228 | 0,629 | 0,0028 |
| 262 | 0,668 | 0,0026 |
| 465 | 1,271 | 0,0027 |

**`s/token` é constante em 0,0027 de 63 a 465 tokens.** O ajuste
`t = 0,019 + 0,00269 · tokens` fecha em 0,6% em 228 tokens e 8% em 262. Abaixo
de ~32 tokens há um piso de ~0,09 s (custo fixo da chamada; bate com os
0,050 s/chunk marginais medidos em lote de 64).

Consequência: **não existe "s/MB do PDF".** Existe s/token do encoder — uma
propriedade da máquina e do modelo — e tokens/MB do formato.

### 2.2 O que varia por formato é quanto texto um megabyte contém

Do índice `e1`, documentos `ok` com chunk:

| ext | n | chars/MB | chars/chunk | chunks/MB |
|---|---:|---:|---:|---:|
| csv | 4 | 1.211.533 | 900 | 1.346 |
| txt | 3.069 | 1.030.594 | 115 | 8.991 |
| eml | 101 | 662.035 | 234 | 2.828 |
| pdf | 1 | 136.165 | 127 | 1.072 |
| xlsx | 3 | 39.021 | 54 | 727 |
| pptx | 1 | 4.843 | 131 | 37 |
| docx | 1 | 3.688 | 129 | 29 |

**Amplitude de 331× em `chars/MB`**, de `.docx` (3.688 — XML comprimido) a
`.txt` (1.030.594 — texto puro).

*Ressalva: n=1 para a maioria dos formatos Office neste corpus. Servem para
mostrar a amplitude, não como coeficiente. Os valores de produção têm de vir do
acervo real.*

Nota lateral com efeito grande: o CSV combina **muitos chunks por MB** (1.346)
com **chunks longos** (900 chars ≈ 364 tokens), porque o chunker repete o
cabeçalho em cada chunk — 770 KB de arquivo produzem 932 KB de texto. É a
combinação que faz duas planilhas responderem por 49% dos chunks da última
perna da execução.

---

## 3. A ideia central — fatorar máquina × formato

A v1 tem **12 coeficientes por tipo**, todos inválidos quando a máquina muda e
todos precisando de histórico próprio. A v2 fatora:

```
t_doc = a_io[maq]                                  # gravar + commit + publicar
      + p_parse[maq, tipo] · MB                    # abrir e extrair texto
      + n_chunks · ( c0[maq, modelo] + c1[maq, modelo] · tokens_por_chunk )
```

e, **antes de abrir o arquivo**, as duas grandezas de conteúdo vêm do formato:

```
tokens_totais ≈ k_tok[tipo] · MB
n_chunks      ≈ tokens_totais / tok_por_chunk[tipo]
```

Substituindo, o modelo *ex ante* volta à forma linear que a instrução pediu:

```
t_doc(tipo, MB) = A[tipo] + B[tipo] · MB

A[tipo] = a_io
B[tipo] = p_parse[tipo] + c1 · k_tok[tipo] + c0 · k_tok[tipo] / tok_por_chunk[tipo]
```

**O ganho não é a forma — é de onde cada metade vem:**

| metade | parâmetros | propriedade de | transfere entre máquinas? | quantos |
|---|---|---|---|---|
| **máquina** | `a_io`, `c0`, `c1` | CPU/GPU + modelo + perfil | **não** | **3** |
| **formato** | `k_tok`, `tok_por_chunk`, `p_parse` | do formato do arquivo | `k_tok` e `tok_por_chunk` **sim**; `p_parse` não | 3 × n_tipos |

Uma máquina nova precisa aprender **três números**, e qualquer tipo de arquivo
os ensina — 60 `.txt` calibram o encoder tão bem quanto 60 PDFs. A metade de
formato viaja no repositório como prior medido e só é refinada por base.

Isso resolve o arranque frio sem caso especial, e explica por que a v1 precisa
de tanto histórico: ela mistura as duas metades num número por tipo, então nada
aprendido sobre `.txt` ajuda a prever `.pdf`.

---

## 4. A tabela master

Duas tabelas, porque as metades têm ciclos de vida diferentes.

### 4.1 Metade de máquina — `perfil_maquina`

Chave: `fingerprint` × `model_id` × `perfil`.

O `fingerprint` é o hash de tudo que invalida os coeficientes: modelo de CPU,
núcleos lógicos **totais**, lista de GPUs, `model_id` do encoder,
`CHUNKER_VERSION`. Trocar o encoder invalida `c0` e `c1` — a v1 diz isso em
prosa; a v2 põe na chave.

*Totais, e não os utilizáveis do perfil, como esta especificação dizia antes de
ser implementada: o perfil já é dimensão separada (`g`), e dobrá-lo aqui
partiria o histórico da máquina em três e não calibraria nenhum.*

| campo | tipo | significado |
|---|---|---|
| `fingerprint` | TEXT | hash de hardware + modelo + chunker |
| `model_id` | TEXT | encoder (redundante na chave, explícito para auditoria) |
| `perfil` | TEXT | `leve` / `normal` / `maximo` |
| `a_io` | REAL | s fixos por documento (gravar, commit, publicar) |
| `c0` | REAL | s fixos por chunk (chamada do encoder) |
| `c1` | REAL | s por token |
| `g` | REAL | fator do perfil (ver §7) |
| `n_obs`, `peso` | INT / REAL | amostras e peso efetivo (com esquecimento) |
| `s2_resid` | REAL | variância do resíduo em log, para a faixa |
| `atualizado_em` | TEXT | |

### 4.2 Metade de formato — `perfil_formato`

Chave: `tipo` × `base_id`, com linha `base_id = '*'` como prior global.

**O `tipo` não é a extensão.** É a extensão mais o que de fato a distingue — e o
registro já carrega essas colunas: `digitalizado`, `tem_tabela`,
`tem_sumario_nativo`, `paginas`, `extensao_mente`.

- `pdf:texto` e `pdf:ocr` — a instrução pediu os dois separados, e está certa; a
  correção é que **a extensão não os separa**. Só se sabe depois do primeiro
  parse (`digitalizado`). Antes disso prevê-se com a *mistura* observada na base,
  e a incerteza reflete isso.
- `xlsx:tabela` contra `xlsx:texto`, idem.
- `doc` / `xls` / `ppt` legado herda do irmão moderno como prior, nunca como
  verdade — o `F4-L` existe porque o container OLE mente sobre o conteúdo.

| campo | tipo | significado |
|---|---|---|
| `tipo` | TEXT | `pdf:ocr`, `xlsx:tabela`, `txt`, … |
| `base_id` | TEXT | id da base, ou `*` para o prior do repositório |
| `k_tok` | REAL | tokens por MB |
| `tok_por_chunk` | REAL | tokens médios por chunk |
| `p_parse` | REAL | s por MB só de abrir e extrair |
| `p_ok` | REAL | fração que termina `ok` (o resto é pulo barato) |
| `n_obs`, `peso`, `s2_resid`, `atualizado_em` | | |

---

## 5. Diagnóstico da base — o mapa, sempre derivado

Antes de qualquer previsão, e a cada ciclo:

```
mapa[tipo] = (n_arquivos, MB_total, n_ja_indexados, MB_ja_indexados)
```

**Regra dura: o mapa restante é derivado por diferença, nunca decrementado.**

```
restante[tipo] = censo[tipo] − registro[tipo]
```

O censo vem do **mesmo `iter_files` que o indexador usa** — é o modo D1 do
documento v1 (denominador errado) e a razão pela qual `declarar()` existe. O
registro vem de um `GROUP BY` em `documentos`. Manter contador incremental é o
defeito que este repositório já pagou duas vezes: *recorte derivável não se
anota*. Contador erra em silêncio e produz número plausível.

O mapa distingue três situações, porque custam ordens de grandeza diferentes:

| situação | custo | como se sabe |
|---|---|---|
| **novo** | modelo completo | não está no registro |
| **mudado** | modelo completo | `mtime`/`tamanho` diferem, ou `model_id`/`chunker`/`parser` mudaram |
| **inalterado** | só `sha256` + I/O | tudo bate |

Revarredura de acervo indexado é quase toda "inalterado" e custa centésimos da
primeira passada — prever pelo modelo completo é o erro que faz a barra pedir
horas para uma revarredura de minutos.

**Saída do diagnóstico**, exibida sempre, mesmo sem previsão de tempo:

```
3.530 arquivos · 268,3 MB
  txt   3.069   0,34 MB   já: 3.069 (100%)
  csv       5   1,04 MB   já:     4  (80%)  ← 2 arquivos = 49% dos chunks
  eml     101   0,04 MB   já:   101 (100%)
  …
```

---

## 6. O ajuste online — RLS com esquecimento, sobre estatísticas suficientes

A instrução pede "regressão linear simples e eficiente" a cada ciclo, sobre todo
o histórico. Refazer OLS sobre n observações a cada documento é O(n) por
documento e O(n²) na execução. A forma certa é **mínimos quadrados recursivos
com fator de esquecimento**, que é o EWMA das estatísticas suficientes
([Luxenberg & Boyd, *Exponentially Weighted Moving Models*](https://web.stanford.edu/~boyd/papers/pdf/ewmm.pdf)).

Para o par `(c0, c1)` com regressores `x = (n_chunks, tokens_totais)` e alvo
`y = s_embed`, acumula-se por perfil:

```
S    ← λ·S + x xᵀ      (2×2 simétrica: 3 números)
u    ← λ·u + x·y       (2 números)
peso ← λ·peso + 1
```

e resolve-se `S θ = u` em forma fechada. **Custo constante por documento,
memória constante, todo o histórico presente com peso `λⁿ`.** `λ = 0,995` dá
meia-vida de ~140 documentos — recente o bastante para acompanhar estado
térmico, longo o bastante para não oscilar.

Quatro exigências que a regressão ingênua não atende:

**6.1 Não-negatividade.** Tempo não é negativo e nenhum coeficiente pode ser.
OLS sem restrição produz intercepto negativo com regressores correlacionados, e
a previsão de um arquivo pequeno fica negativa. Resolver com **NNLS**: em 2×2
basta resolver e, se algum `θ < 0`, fixá-lo em 0 e resolver o resto. A restrição
de sinal é a regularização natural do problema e não introduz parâmetro de
ajuste.

**6.2 Robustez sem descartar informação.** O `CLIP_OUTLIER` da v1 joga fora a
cauda (D3). A v2 **não descarta observação por ser lenta** — descarta apenas
observação com **relógio suspeito** (houve suspensão durante aquele documento; o
`Relogio` já sabe dizer). Para a dispersão genuína, ajusta-se em **log-tempo com
perda de Huber**: a cauda entra, com peso decrescente, em vez de ser excluída.
É o que permite aprender que CSV é caro.

**6.3 Encolhimento para o prior — o arranque frio.** Com `n_obs` pequeno, o
ajuste próprio é pior que o prior. Combinação empírico-bayesiana:

```
θ_usado = w · θ_local + (1 − w) · θ_prior,   w = n_obs / (n_obs + n₀)
```

`n₀ = 8`. Com 0 observações usa o prior puro; com 8 é meio a meio; com 80 é 91%
local. Um `pdf:ocr` novo herda o prior de `pdf` e migra sozinho conforme
aparecem exemplos — sem `if n < k` espalhado pelo código.

**6.4 Ajustar em tempo ativo, por etapa.** O alvo de `(c0, c1)` é o tempo do
**estágio de embed**, não do documento. Misturar etapas é o que faz um
coeficiente absorver o outro (D1). `a_io` e `p_parse` têm cada um seu alvo. Um
cronômetro por etapa por documento; três acumuladores.

---

## 7. O perfil de esforço — onde entra, e por que não é fator global

A instrução propõe fator de ajuste linear pelo nível de esforço, iniciado pelo %
de carga e corrigido com histórico real. A direção está certa; a correção é
**onde** ele se aplica.

**Medido:** de `ritmo=1.0` para `ritmo=0.5`, o **estágio de embed** foi de
0,081 s para 0,171 s por chunk — **2,1×**, medido duas vezes. Mas o documento
inteiro foi de 321 ms para 384 ms — **1,20×**.

Um fator global calibrado no documento (1,20) subestima o embed em 43%; um
calibrado no embed (2,1) superestima o documento em 75%. **Nenhum escalar global
serve, porque a proporção entre trabalho de encoder e trabalho de I/O muda com o
arquivo.**

A correção é estrutural e não custa nada: **o perfil multiplica só os
coeficientes do encoder.**

```
t_doc = a_io + p_parse·MB + n_chunks · ( c0 + c1·tokens ) · g[perfil]
```

`a_io` fica de fora — é I/O e SQLite, não encoder. A v1 já sabia disso para a
GPU (`SEGUNDOS_POR_DOCUMENTO` "não divide por `FATOR_GPU`"); a v2 generaliza
para o perfil. Com isso `g` é **identificável**: um número por
`(fingerprint, perfil)`, que explica 2,1× e 1,20× ao mesmo tempo, sem fudge.

Quatro regras a mais:

- **Semente, não verdade.** `g` começa em `1/duty` do perfil — o `dormir_ritmo`
  dorme proporcionalmente ao trabalho, então `1/0,5 = 2,0`, e o medido foi 2,1.
  Para GPU, semente pelo `FATOR_GPU` existente.
- **Aprendizado pareado.** `g` só é atualizado com observações do **mesmo tipo**
  em perfis diferentes na **mesma máquina** — foi o que a instrução pediu, e é a
  única forma de não confundir `g` com a composição do corpus.
- **Desconfundir antes de ajustar as inclinações.** Toda observação é
  normalizada para o perfil de referência (`maximo`) dividindo por `g` atual,
  *antes* de entrar nos acumuladores de `c0`/`c1`. Sem isso a inclinação absorve
  o perfil e os dois nunca se separam. Duas passadas alternadas por ciclo bastam.
- **O perfil muda no meio da execução** (o painel permite). Toda observação
  carrega o perfil vigente; nenhuma é atribuída ao perfil errado.

---

## 8. A faixa — soma de quantis está errada

A instrução manda somar por tipo: `Σ (fator·N + fator·Tamanho)`. Correto para o
**ponto**. Errado para a **faixa**: o quantil de uma soma não é a soma dos
quantis.

A distribuição é de cauda pesada (a própria v1 registra CV 4,6) e o restante é
dominado por poucos arquivos grandes. Então:

- **Ponto**: `Σ_tipo [ A·N_restante + B·MB_restante ]`, com os `θ` encolhidos.
- **Faixa**: **Monte Carlo sobre o mapa restante** — 200 sorteios, cada tipo
  amostrando seu resíduo empírico em log; devolve p50 e p90 da soma. 200
  sorteios sobre ~15 tipos é aritmética de milissegundos, roda uma vez por
  ciclo, e é correto por construção em vez de aproximadamente correto.
- Os **k maiores arquivos restantes** entram no sorteio **individualmente**, não
  pelo agregado do tipo: é onde a variância vive.

**Nunca suavizar a saída.** Suavizar `p50` e não `p90` é D5. A suavização entra
nos **coeficientes** (que já têm esquecimento, §6), e `p50`/`p90` saem do mesmo
modelo na mesma passada. Invariante: `p50 ≤ p90`, com asserção.

**Exibir decomposto**, porque a cauda domina e o usuário pode agir:

```
restam 41 min — 3.100 arquivos pequenos (~6 min) + 3 planilhas grandes (~35 min)
```

---

## 9. Quando exibir número — porta quantitativa, não contagem de ciclos

A instrução diz: não exibir previsão até ter rodado algum ciclo. A intenção está
certa — número sem base local é mentira. "Algum ciclo" é a unidade errada: um
ciclo de 3.000 `.txt` não ensina nada sobre os 40 PDFs que faltam.

A porta é de **cobertura do que falta**, não de quanto já passou:

| estado | condição | o que a tela mostra |
|---|---|---|
| **cego** | sem `perfil_maquina` local | mapa, contagem, `medindo…` — **nenhum tempo** |
| **calibrando** | tem máquina, mas < 80% do MB restante em tipos com `n_obs ≥ 8`, ou faixa com largura relativa > 1,5× | mapa, contagem, vazão observada, faixa **rotulada** `calibrando` |
| **calibrado** | ambas atendidas | faixa |

Assim uma pasta com formato nunca visto **derruba o estado para `calibrando`**
mesmo com meses de histórico — que é o comportamento certo para a "pasta que
nunca vimos" da regra de ouro, e o caso que uma contagem de ciclos deixaria
passar exibindo número confiante e errado.

---

## 10. Persistência — o que não existe hoje

**O histórico por documento não é persistido em lugar nenhum.** `documentos` tem
`tamanho`, `n_chunks`, `status`, `paginas`, `digitalizado` — e **nenhuma coluna
de tempo**. O passo "recalcule com base em todo o histórico" não tem de onde
ler. É a lacuna estrutural desta especificação.

**`medicoes`** — uma linha por documento processado, no `registro.db` da base:

| campo | por que |
|---|---|
| `path`, `tipo`, `mb`, `n_chunks`, `tokens` | regressores |
| `s_parse`, `s_chunk`, `s_embed`, `s_grava` | alvos, **por etapa** (§6.4) |
| `s_total_ativo` | tempo ativo do `Relogio`, não parede (D4) |
| `suspeito` | 1 se houve suspensão durante o documento — excluído do ajuste |
| `perfil`, `fingerprint`, `model_id`, `execucao` | procedência (invariante 5) |
| `situacao` | novo / mudado / inalterado |

**`calibracao.db`** — por máquina, fora de qualquer base
(`%LOCALAPPDATA%\segundocerebro\`), contendo `perfil_maquina` e
`perfil_formato`. Fica fora das bases porque a metade de máquina é **da
máquina**: o que uma base ensinou sobre o encoder serve à base seguinte, e é o
que faz a segunda base indexar já calibrada.

**Hierarquia entre bases.** A instrução diz "histórico daquela base"; o correto é
hierárquico. `c0`/`c1`/`a_io` **agrupam por máquina** (mais dados, calibragem
mais rápida); `k_tok`/`tok_por_chunk`/`p_parse` têm linha por base com
encolhimento para o prior global `*` — os PDFs de uma base podem ser todos
digitalizados e de outra todos nativos. §6.3 já é o mecanismo; só muda a chave.

**Retenção**: `medicoes` cresce como `documentos`. Poda por reservatório —
últimas 500 por tipo mais amostra aleatória do resto. Os acumuladores RLS não
precisam das linhas; elas existem para reajuste, auditoria e para o autoteste
de calibragem.

---

## 11. Correções à instrução, numeradas

| # | instrução | correção | evidência |
|---|---|---|---|
| C1 | tempo em função do **tamanho** por tipo | tamanho é o único preditor *antes* de abrir, e fica; mas o custo é de **tokens**, e a forma linear por tipo deve ser **derivada** da fatoração (§3), não ajustada como caixa preta | `s/token` constante 0,0027; `chars/MB` varia 331× |
| C2 | tipos `pdf`, `pdf OCR`, … | certo separar, mas **a extensão não separa** — `pdf:ocr` só se conhece após o parse. Chave é `(ext, natureza)`, e as colunas já existem (`digitalizado`, `tem_tabela`) | `F4-L`: container OLE mente sobre o conteúdo |
| C3 | recalcular por regressão linear a cada ciclo | **RLS com esquecimento sobre estatísticas suficientes** — O(1) por documento em vez de O(n); mais **NNLS**, **Huber em log** e **encolhimento** | refit O(n) por documento é O(n²) na execução |
| C4 | ajuste linear pelo nível de esforço | o fator multiplica **só o termo de encoder**, nunca `a_io` — é o que torna `g` identificável | embed 2,1× e documento 1,20× no mesmo par de execuções |
| C5 | não exibir previsão até rodar algum ciclo | porta por **cobertura do que falta** e largura da faixa, não por contagem de ciclos | 3.000 `.txt` não ensinam nada sobre 40 PDFs |
| C6 | manter atualizado o mapa de faltantes | **derivar por diferença** a cada ciclo, nunca decrementar | *recorte derivável não se anota* — já custou um número plausível e errado |
| C7 | somatória por tipo | correta para o ponto; para a faixa, **Monte Carlo** — quantil de soma ≠ soma de quantis | CV 4,6; 2 de 3.530 arquivos = 49% dos chunks |
| C8 | histórico "daquela base" | **hierárquico**: máquina agrupa o encoder, base refina o formato | a segunda base deve começar calibrada |
| C9 | — (ausente) | `medicoes` **não existe**; sem ela nada disto é implementável | nenhuma coluna de tempo em `documentos` |
| C10 | — (ausente) | prever a **situação** (novo/mudado/inalterado) e a mistura de `status`; revarredura custa centésimos | `duplicado` = 200 de 3.530 no `e1` |
| C11 | — (ausente) | `fingerprint` inclui `model_id` e `chunker`: trocar encoder **invalida** `c0`/`c1` | v1 diz em prosa; v2 põe na chave |
| C12 | — (ausente) | invariante `p50 ≤ p90` com asserção e teste | faixa invertida observada em produção |

---

## 12. Invariantes e testes

Cada um pega uma **classe** de defeito, não um caso — é o que a regra de ouro
exige de uma correção.

| # | invariante | teste |
|---|---|---|
| I1 | `p50 ≤ p90` sempre | propriedade sobre entradas sorteadas, incluindo `falta` caindo em degrau |
| I2 | nenhum coeficiente negativo, nenhuma previsão negativa | propriedade sobre a saída do NNLS |
| I3 | previsão monotônica: mapa restante encolhendo e coeficientes fixos, o tempo não cresce | sequência sintética de ciclos |
| I4 | tempo de parede **nunca** entra no ajuste | injeta suspensão, verifica `suspeito=1` e que os coeficientes não mudam |
| I5 | trocar `model_id` não reaproveita `c0`/`c1` | dois `fingerprint`, tabela isolada |
| I6 | sem histórico local não sai número | estado `cego` assertado |
| I7 | mapa restante = censo − registro, recalculado | corrompe um contador incremental e mostra que a derivação o ignora |
| I8 | a calibragem **aprende** a cauda | injeta 20 documentos 6× mais caros e verifica que o coeficiente do tipo sobe — **mataria a v1**, que os rejeitaria |

E um **autoteste de calibragem** em produção: ao fim de cada execução, comparar
o tempo real com a faixa prevista no início e gravar em `medicoes`. Se o real
cair fora da p90 em mais de ~10% das execuções, registrar aviso. A estimativa
passa a ter regressão medida, como o resto do projeto.

---

## 13. Implementação em fatias

Cada fatia entrega valor sozinha e é revisável em PR separado.

*Numeradas como "fatia N" e não `E1`–`E5`, que foi como esta especificação as
chamava antes de ser implementada: o `ROADMAP.md` já usa `E1`–`E6` para os
pacotes da arquitetura de avaliação, onde `E1` é o gerador de corpus
sintético. Duas coisas diferentes com o mesmo nome, num repositório com dois
computadores trabalhando em paralelo, é confusão barata de evitar agora e
caro de desfazer depois.*

| fatia | conteúdo | por que nesta ordem |
|---|---|---|
| **fatia 1** | `medicoes` + cronômetro por etapa + `suspeito`. **Sem mudar a estimativa.** | sem dados não há método; e uma execução do acervo real já popula a tabela |
| **fatia 2** | corrigir D4 e D5 na v1: tempo ativo no ajuste, `p50 ≤ p90`, parar de restaurar fator contaminado | três defeitos vivos em produção, correção pequena, não espera o resto |
| **fatia 3** | `calibracao.db`, `fingerprint`, RLS + NNLS + encolhimento; prior de formato medido no acervo real | o motor |
| **fatia 4** | mapa derivado + diagnóstico exibido + estados cego/calibrando/calibrado | é o que o usuário vê |
| **fatia 5** | Monte Carlo da faixa; `g[perfil]` pareado; autoteste de calibragem | refinamento sobre base já correta |

**A fatia 2 é independente e vale sozinha** — corrige a faixa invertida e a
contaminação por suspensão sem depender de nada acima.

Nada disto toca o caminho de consulta (invariante 6) nem a superfície MCP.
`peso_de` e `SEGUNDOS_POR_MB` continuam existindo como **prior de formato** até
a fatia 3 substituí-los.

---

## 14. O que esta especificação não resolve

- **`p_parse` de PDF com OCR** não tem nenhuma observação, e agora tem por que
  ter: o OCR entrou na `main` pelo PR #38 (`R1.2 / F4-O`) enquanto este pacote
  era escrito. O prior de `pdf:ocr` segue **ausente de propósito** — inventar
  coeficiente ali produziria confiança sobre trabalho que ninguém mediu — e
  `SEM_PRIOR` mantém o estado em `calibrando` quando aparecer um digitalizado.
  A primeira passada com OCR sobre acervo real é o que fecha isso, e o
  mecanismo para absorvê-la já está no lugar: `tipo_de(..., digitalizado=True)`
  devolve `pdf:ocr`, então a medição cai na chave certa sozinha.
- **O residual de ~0,12 s/doc** entre a soma das etapas medidas (~0,24 s) e o
  fim-a-fim (~0,365 s) não está atribuído. Suspeito principal:
  `publicador.publicar()` grava `progresso.json` com `replace` atômico **a cada
  documento**. Precisa de medição própria; até então o residual vive dentro de
  `a_io` e é aprendido, não assumido. Se confirmado, é ganho barato: publicar por
  tempo em vez de por documento.
- **Paralelismo.** O modelo é sequencial. Com parse em threads e embed em GPU as
  etapas se sobrepõem e a soma superestima. Enquanto o embed for na thread
  principal (CPU) o erro é pequeno; no desktop com duas 980 Ti, não. A v2 tem de
  ajustar sobre o **tempo do documento no pipeline**, não sobre a soma das
  etapas, quando `n_gpus > 0` — e é por isso que `fingerprint` inclui a lista de
  GPUs.

---

## 15. O que a implementação corrigiu desta especificação

Escrita em 27/08/2026, contra código rodando e 33 testes. Cada item foi achado
por um teste — sete deles pelos testes **antigos** da v1, que guardavam
intenções que eu havia perdido de vista ao especificar.

**15.1 — O encolhimento de §6.3 era indeterminado com uma observação.**
`θ = w·θ_local + (1−w)·θ_prior` encolhe uma resposta *arbitrária*: com uma só
observação, um ajuste de dois parâmetros é indeterminado, e a enumeração de
conjunto ativo da NNLS desempata por **ordem da lista de candidatos**. Encolher
o arbitrário continua arbitrário.

Substituído por **ridge de Tikhonov centrado no prior** — `(S + T)θ = u + T·prior`
com `T = diag(n0·escala_i²)`, que é regressão linear bayesiana. O sistema fica
positivo-definido desde zero observação, então não há o que desempatar.

E a **escala de referência importa mais que o ridge**: `n0` observações *na
escala do que apareceu* deixa uma medição de um arquivo de 2 KB (`x² ≈ 16`)
pesar como oito documentos e mandar no coeficiente de máquina — que depois
multiplica os 51 mil chunks de um PDF de 50 MB. O prior tem de valer `n0`
documentos de **tamanho típico** (40 chunks, 5.000 tokens, 1 MB). Pego por
`test_arquivo_miudo_nao_joga_a_estimativa`, teste da v1.

**15.2 — A dispersão emprestava o viés, não só a largura.**
A §8 diz "cada tipo amostrando seu resíduo empírico" e não diz o que fazer com
poucas amostras. Cair para o agregado global trazia o `mu` junto — e `mu` é o
erro sistemático de *outros* tipos. Quarenta `.txt` lentos multiplicavam o
restante de PDF por `exp(mu)`: o defeito "txt pequeno infla o restante de PDF",
que a fatoração resolvia no ponto, voltando **pelo canal da faixa**. Largura se
empresta; viés não. Pego por `test_txt_pequeno_nao_infla_o_restante_de_pdf`.

**15.3 — Peso de Huber só depois de quatro observações não protege nada.**
As quatro primeiras entravam cruas, e é justamente quando não há massa para
diluí-las. Não havia motivo para o guarda: **o prior é um ajuste**, então existe
referência desde a primeira observação.

**15.4 — `g` não é identificável numa execução de um só perfil.**
A §7 pede "aprendizado pareado" e a implementação natural atualiza `g` a cada
observação. Mas `g` e `(c0, c1)` explicam o mesmo dado: sem medição no perfil de
referência para ancorar, o **produto** `g·c` é identificável e a separação não é.
Mover `g` ali é escolher uma fatoração no escuro, e a escolha errada estraga a
previsão do outro perfil — que é para o que `g` existe.

Agora `g` só sai da semente com ≥5 observações em `maximo`. Sem âncora,
`(c0, c1)` absorve a velocidade da máquina — o que prevê **este** perfil
corretamente — e outro perfil usa a razão entre as sementes. Limite conhecido e
documentado: uma máquina que nunca rode em `maximo` nunca ancora.

**15.5 — "Inalterado custa sha256 + I/O" está errado, e são duas contas.**
Arquivo inalterado é filtrado da fila **antes de qualquer abertura**: custa
zero, e é o que faz revarredura fechar em minutos. Mas a **barra** tem de
contá-lo como trabalho **cheio**, senão uma retomada com 90% pronto abre em 0%
e salta para 100%. Tempo restante e barra respondem perguntas diferentes; a
especificação as tratava como uma.

**15.6 — Derivar a cada 15 s não basta nas duas pontas.**
Sem uma derivação **antes de o trabalho começar**, a primeira estimativa conta
como restante o acervo inteiro, inclusive o que a pré-passada acabou de pular.
E sem rederivar **no fim da fila**, a barra nunca chega a "terminando". As duas
são baratas: a primeira é uma consulta, a segunda só acontece com menos de 50
arquivos restando.

**15.7 — A fração da barra também precisava ser derivada, não acumulada.**
Acumular `previsto_feito` com coeficientes que aprendem, contra um
`previsto_total` congelado no prior, faz os dois divergirem: a barra parou em
**97,98%** no fim de uma passada completa. É a mesma regra do mapa —
numerador e denominador saem do mesmo modelo, na mesma passada. Pego por
`test_indexacao_publica_progresso_e_encerra`.

**15.8 — Cache com contador de versão é a mesma classe de defeito do contador
decrementado.** Pus um cache na faixa porque `instantaneo()` a pedia três vezes
por publicação, cada vez um Monte Carlo. Com chave por contador manual, quem
mexesse no mapa por fora esquecia de invalidar — e o primeiro teste que escrevi
fez exatamente isso, recebendo a faixa antiga. A chave passou a ser **derivada
das entradas**.

**Uma correção de medição, não de método**: `s_parse` tinha de ser cronometrado
**dentro** do worker. Medido da thread principal, mediria fila mais parse, e um
`p_parse` calibrado sobre tempo de fila mede o tamanho do pool.

---

## 16. Dois limites achados validando a implementação

**16.1 — A afinidade de CPU do perfil de esforço custa 12×, não 2×.**

> **Retratado em 27/08/2026.** O número existe; a causa atribuída aqui, não.
> A mesma máscara mede 0,141 e 3,19 s/chunk conforme um estado do sistema
> operacional que o produto não observa — e no estado benigno a máscara custa
> **zero**. A suspeita de colisão de threads intra-op do ORT está refutada, e
> com ela a leitura de que há "~12× de vazão" à espera de um conserto de
> máscara. Ler [`afinidade-e-estado-de-maquina.md`](afinidade-e-estado-de-maquina.md)
> antes de usar qualquer número deste bloco. O parágrafo abaixo fica como
> registro do que foi medido e de como foi concluído errado.
E isso **invalida um número que reportei antes**: eu disse que o perfil `normal`
custava 1,20× ponta a ponta. Aquela medição não aplicava a afinidade que a
produção aplica — foi exatamente o erro que este repositório já catalogou
("conferir qual caminho de código o produto executa vem antes de afinar peso
nele"), cometido por mim ao medir.

Notebook corporativo, CPU híbrida (10 núcleos físicos, 12 lógicos), `e5-large`,
chunk de 20 tokens, `threads=6`, `ritmo=1.0`, 27/08/2026:

| afinidade | s/chunk |
|---|---:|
| `[0,1,2,3,4,5]` — o que o perfil `normal` aplica | **1,936** |
| `[0,2,4,6,8,10]` — 6 lógicos alternados | 1,040 |
| sem restrição, 12 lógicos | **0,157** |

Com `ritmo=0.5` por cima, o custo em produção é **4,1 s por chunk pequeno** — e
é o que a tabela `medicoes` de um run real registrou, o que confirma que a
calibragem está medindo certo uma máquina que está lenta de verdade.

Suspeita principal: a ONNX Runtime fixa a afinidade das próprias threads
intra-op, e sob máscara de processo restrita várias caem no mesmo processador
lógico. **Não consertado aqui** — é outro subsistema
(`esforco.py` / `embeddings.py`), precisa de medição própria, e vale mais que
qualquer ajuste de estimativa: ~12× de vazão de indexação.

**16.2 — Extrapolar muito além do medido não é seguro, e regularizar o ajuste
não resolve.**
Sessenta documentos de **um** chunk determinam `c0 + 120·c1` com precisão, e
quase nada sobre a *separação* dos dois — que é justamente o que faz falta para
prever um CSV de 767 chunks. Num run real isso previa **2 d 12 h** para 3.471
arquivos pequenos mais 12 grandes, contra ~8 h plausíveis: o erro inteiro vinha
de `c0` aprendido em 1 chunk e multiplicado por 767.

O ajuste está **certo no ponto medido**; o problema é a distância. Então o
limite é separado do ajuste: acima de `FATOR_DE_EXTRAPOLACAO` (8×) vezes o maior
documento já medido, a previsão do encoder encolhe para a do prior,
proporcionalmente à distância. A mesma execução passou a prever **23 h**.

Segue alta em ~2–4×, e a causa restante é conhecida: o agregado por tipo usa o
MB **médio** do tipo, enquanto a fila de prioridade indexa os menores primeiro —
então `k_tok` aprendido nos arquivos de 52 bytes é aplicado a uma média 2,2×
maior. Corrige-se sozinho conforme a passada cobre o tipo, e o estado fica em
`calibrando` até lá. Aceito por ora; a alternativa é histograma de tamanho por
tipo em vez de média, e isso pede medição antes de código.
