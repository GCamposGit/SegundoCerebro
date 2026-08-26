# Duas falhas silenciosas — 26/08/2026

Achadas durante o `F4-P.1`, fora do escopo dele. **Corpus**: `corpus-e1` gerado
por `eval.gerador --seed 42 --n-por-fatia 100 --so-texto` (3.833 arquivos).
**Máquina**: notebook corporativo, i7-1355U (10 núcleos / 12 threads), 15,7 GB de
RAM, Windows 11, `fastembed` 0.8.0 / `onnxruntime` 1.28.0, e5-large na CPU com
`threads=6` e perfil `normal`. **Data das medições**: 26/08/2026.

As duas são da mesma classe, e é por isso que estão no mesmo documento: **o
mecanismo não devolveu erro nenhum, e o resultado pareceu certo**. Uma passada
com menos arquivos é o que se pediu; uma barra que diz "indexando" é o que se
espera. Nos dois casos o único jeito de descobrir era medir por fora, e ninguém
mede por fora.

---

## 1. O indexador não avançava e a barra dizia "indexando", com ETA

### O que aconteceu

Indexando `corpus-e1`, o processo parou de progredir às 06:17:38 com 800
documentos feitos e ficou **3 h 22 min** sem fazer nada: último log às 06:17:38,
52 threads todas em `Wait`, **0,0 s de CPU** numa janela medida de 241 s, trava
`index-e1/indexacao.lock` na mão. O `progresso.json` continuou dizendo
`"status": "indexando"` com `"restante": "9 h 31 min"`.

O congelamento caiu exatamente na pasta `16. Anexos volumosos` — as fatias
`chunk_hostil` do gerador. Antes dela o ritmo era de ~1.500 docs/h em documentos
de **1 chunk**.

### Não era deadlock

Reproduzido em 26/08/2026 às 10:14, com `faulthandler.dump_traceback_later`
ligado. A pilha de todas as threads, ao cabo de 150 s no primeiro documento
daquela pasta:

```
Thread principal (most recent call first):
  onnxruntime/capi/onnxruntime_inference_collection.py:326 in run
  fastembed/text/onnx_text_model.py:96 in onnx_embed
  fastembed/text/onnx_embedding.py:284 in embed
  segundocerebro/index/embeddings.py:272 in embed_passagens
  segundocerebro/index/indexer.py:841 in aplicar
```

Uma única chamada `session.run` do ONNX, com um lote de 32 trechos. Não há espera
mútua, não há fila cheia entre o parse worker e o embed, não há nada com o
`gpu_pool` (a passada era de CPU, `fila is None`). O parse worker estava ocioso.
**O processo estava dentro de uma chamada só, e ela não voltava.**

O gatilho é a mudança de forma do corpus, não a pasta. Medido: os documentos das
pastas anteriores rendem **1 chunk** cada; os de `16. Anexos volumosos` rendem
**52 chunks de janela cheia** (1.800 caracteres, até 418 tokens contra um
orçamento de 488). Ou seja, o lote de embed saltou de 1 sequência curta para 32
sequências quase no máximo — de um passo para o outro, sem nada no meio.

### O custo do lote, medido

52 trechos do mesmo documento (`Encaminhamento CT-CK-003.txt`), e5-large,
`threads=6`, RSS de 1.755 MB só com o modelo carregado:

| `lote` | tempo total | por trecho | pico de working set |
|-------:|------------:|-----------:|--------------------:|
| 1  |  46,4 s | 0,89 s | 1.807 MB |
| 4  |  64,6 s | 1,24 s | 1.946 MB |
| 8  |  75,4 s | 1,45 s | 2.131 MB |
| 16 |  86,9 s | 1,67 s | 2.500 MB |
| 32 | 150,1 s | 2,89 s | 2.642 MB |

O padrão do produto é `lote = 32`. Nesta CPU ele é **3,2× mais lento por trecho
e 835 MB mais pesado no pico** que `lote = 1`. Durante a medição a máquina tinha
**1,1 GB de 15,7 GB livres** — as 3 h 22 min com 0,0 s de CPU e 52 threads em
`Wait` são o que sobra quando um lote desses tenta crescer sem memória livre: o
processo fica esperando página, e esperar página não gasta CPU.

E o lote **não muda o vetor**. Mesmos 52 trechos, `lote=1` contra `lote=32`:

```
max|diferença| = 0,000e+00    cosseno mínimo = 0,999999702
```

Bit a bit idênticos. Pelo critério do `ARCHITECTURE.md` §4 — hardware muda
velocidade, nunca conteúdo — **`lote` é escolha de velocidade, não de conteúdo**,
e mexer nele não passa pelo eval.

### O que foi corrigido: o silêncio

Um indexador parado não pode reportar que está indexando, e **não pode depender
da thread travada para dizer isso**. Era o defeito de arquitetura por baixo do
sintoma: `publicar()` só era chamado pela thread principal, então o único momento
em que o arquivo não é atualizado é justamente aquele em que ele precisaria ser.

`Publicador` ganhou um **vigia**: thread daemon que republica sozinha a cada 30 s
e, se nada avançar por `LIMITE_SEM_AVANCO` (10 min de tempo de parede), troca o
status para `travada`, grava `sem_avanco_segundos` e grita no log com o PID a
conferir. "Avançar" é documento **ou** trecho **ou** arquivo em voo — sem o
trecho, um PDF legítimo de 800 trechos cairia como travado.

O painel passa a mostrar `sem avanço há X` em vez de `faltam 9 h 31 min`, e um
aviso que diz o que olhar: *CPU perto de zero é falta de memória, não trabalho
lento*.

Ainda no mesmo módulo: `_gravar` passou a retentar a troca atômica. No Windows,
`replace` recusa com "acesso negado" enquanto outro processo tem o
`progresso.json` aberto — a leitura do painel basta —, e uma publicação que falha
em silêncio devolve exatamente o sintoma que o módulo existe para eliminar.

### O que **não** foi corrigido, e por quê

O padrão `lote = 32`. A medida acima é de **uma** máquina, **um** modelo e
**uma** forma de documento, e o lote grande é justamente o que enche uma GPU — é
a premissa do `gpu_pool`. Trocar o padrão é decisão de produto com contrapartida
de hardware, e pela regra 11 precisa de fatia declarada antes da varredura. Fica
registrado o número e a recomendação: **na CPU, orçar o lote por tokens e não por
contagem de trechos** — 32 trechos de 12 caracteres e 32 trechos de 1.800 não são
a mesma carga, e hoje o código trata os dois igual.

---

## 2. Regra de exclusão que não casa com nada

### O que aconteceu

`config.e1.toml` declarava:

```toml
[[base.exclude.papel]]
dirs = ["16. Anexos volumosos"]
globs = ["*"]
```

`dirs` são **prefixos de caminho relativos à raiz**, e o gerador escreve em
`<out>/corpus/`. O caminho real era `corpus/16. Anexos volumosos`. A regra casou
com **zero** arquivos — e a passada correu inteira como se a exclusão existisse.
Não houve aviso, não houve contagem, não houve nada. Custou 3 h 22 min de máquina
e uma medição contaminada com 312 chunks patológicos.

É a mesma classe que a auditoria de 20/08/2026 já nomeou para o `.gitignore`: a
lista por nome falha em silêncio no arquivo seguinte, e quatro `metricas-f2-*`
foram commitados. Lá a lição virou padrão (`docs/metricas-*.md`); aqui vira
mecanismo.

### O que foi corrigido

Contagem **por regra**, e conferência antes de abrir o primeiro arquivo:

- `Census.excluded_by_rule` conta, por rótulo de regra, quantas entradas cada uma
  tirou. Total sozinho não distingue "463 fora por papel" de "regra inerte e zero
  fora";
- `Census.role_scope_dirs` conta quantas pastas o escopo `dirs` de cada regra de
  papel alcançou. Isso separa os **dois** motivos de uma regra não casar nada, que
  pedem correções diferentes: prefixo apontando para pasta nenhuma, ou pasta certa
  e glob que não casa. O aviso diz qual dos dois é;
- `census.check_exclusions()` devolve o aviso para cada regra **declarada** que
  não tirou nada. Só as declaradas: `.git` e `~$*` casarem zero é o esperado num
  acervo de escritório, e vinte avisos por passada é como um aviso morre. Daí o
  campo `Config.declared` / `Base.exclude_declarado`, que separa o que o arquivo
  pediu do padrão técnico;
- o indexador confere na **pré-passada de enumeração** — antes de qualquer parse —,
  loga o aviso, e publica a contagem inteira em `progresso.json` sob `exclusoes`;
- o relatório do censo ganhou a seção `## Exclusões declaradas`, com a contagem por
  regra e os avisos;
- `--exigir-exclusoes` recusa a passada quando alguma regra declarada é inerte.
  Opt-in, não padrão: escopo legitimamente vazio existe (pasta que este acervo
  ainda não tem), e recusar por padrão quebraria configuração correta.

Medido depois da correção do prefixo, no mesmo corpus: 200 excluídos, 0
escapando, 3.635 ficam. Antes: 0 excluídos, e nenhum sinal disso em lugar nenhum.

---

## O que passa a pegar a classe sozinho

O que importa não é o caso consertado; é o teste que reprova a próxima instância.

| Teste | O que trava |
|---|---|
| `test_prefixo_errado_de_papel_vira_aviso_e_nao_silencio` | o defeito de 26/08 exatamente como foi escrito |
| `test_pasta_certa_e_glob_que_nao_casa_avisa_o_outro_motivo` | o aviso diz qual dos dois erros é |
| `test_exclusao_tecnica_padrao_nunca_vira_aviso` | o aviso não afoga em ruído do padrão técnico |
| `test_contagem_por_regra_separa_duas_regras` | total não pode esconder regra inerte ao lado de regra que funciona |
| `test_exigir_exclusoes_recusa_antes_de_abrir_arquivo` | recusa antes do custo: zero documento, zero byte |
| `test_regra_inerte_sai_como_aviso_no_progresso` | a passada que paga o custo é a que confere |
| `test_vigia_publica_sozinho_com_a_thread_principal_presa` | o vigia não depende de quem travou |
| `test_status_troca_para_travada_e_a_estimativa_deixa_de_valer` | "indexando" com ETA enquanto nada anda |
| `test_trecho_dentro_do_arquivo_conta_como_avanco` | documento grande legítimo não cai como travado |
| `test_vigia_nao_derruba_a_indexacao_quando_a_batida_falha` | progresso é conveniência; indexação é o trabalho |
