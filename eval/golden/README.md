# Conjunto dourado

Pares pergunta → fonte(s) esperada(s), escritos à mão a partir do acervo real.
É a régua de toda a F1 em diante: **nenhuma mudança de chunking, embedding ou
ranking entra sem número antes e depois** (invariante 4 do CLAUDE.md).

## Formato — `perguntas.jsonl`

Uma pergunta por linha, JSON:

```json
{"id": "g001", "tipo": "exato", "pergunta": "...", "fontes": ["pasta/arquivo.pdf"],
 "validada": true, "notas": "..."}
```

| Campo | Significado |
|-------|-------------|
| `id` | Estável. Nunca reaproveitar um id apagado — as métricas históricas o referenciam |
| `tipo` | `exato` · `semantica` · `temporal` · `multihop` |
| `fontes` | Caminhos **relativos à raiz**, com `/` como separador. O harness normaliza para o separador do sistema |
| `validada` | `true` quando o usuário confirmou pergunta **e** fonte. Rascunho meu = `false` |
| `notas` | Por que a pergunta existe e que armadilha ela cobre |
| `idioma` | Idioma da **pergunta**: `pt` · `en`. Ausente = detectar do texto |
| `idioma_fonte` | Idioma da(s) **fonte(s)**: `pt` · `en` · `misto` · `indefinido`. Ausente = fora da fatia |

Os caminhos usam `/` mesmo no Windows para não precisar escapar `\` em JSON.

## Por que o campo `tipo` existe

Uma métrica única esconde o diagnóstico. A quebra por tipo diz *qual* componente
está falhando:

| Tipo | O que testa | Quem deve resolver |
|------|-------------|--------------------|
| `exato` | Código de contrato, sigla, número de processo | Componente **sparse** do BGE-M3 |
| `semantica` | Pergunta com vocabulário diferente do documento | Componente **dense** |
| `temporal` | Versão vigente, "depois de", recorte de período | Filtro por metadado + `mtime` |
| `multihop` | Exige dois ou mais saltos entre documentos | `neighbors` (F4) |

Mistura alvo em 50 perguntas: ~15 `exato`, ~20 `semantica`, ~8 `temporal`,
~7 `multihop`.

## Por que existem os dois campos de idioma

O acervo é bilíngue. Medido em 24/08/2026: **284 dos 1.900 documentos com
conteúdo estão em inglês**, e **12 das 62 perguntas** apontam para um deles a
partir de uma pergunta em português. A ponte entre os dois idiomas mora num
ranqueador só — o denso é multilíngue e alinhado, o bm25 é cego a idioma por
construção, porque FTS5 não casa `contrato` com `agreement`.

Sem o recorte, uma troca de modelo denso que quebrasse **só** essa ponte subiria
na média agregada e ninguém veria: a fatia mesma-língua é quatro vezes maior e a
esconderia. É a lacuna que `C4.5` fecha.

Os dois campos não funcionam igual, e a assimetria é deliberada:

- **`idioma`** tem detecção de reserva — o texto da pergunta está no arquivo.
  Anote à mão só o que o detector não decide: consulta curta feita de sigla e
  número. É 1 das 62 aqui.
- **`idioma_fonte`** **não** tem. Detectá-lo no relatório exigiria índice
  aberto, e o baseline por nome não abre índice — a fatia sumiria justamente do
  lado F0 da comparação entre fases, que é a razão de o harness existir. Quem
  preenche é o comando abaixo, uma vez, lendo o índice; depois disso a anotação
  é estática e conferível em diff, como `fora_de_escopo`.

```bash
py -m eval.idioma --base padrao              # só relata a fatia
py -m eval.idioma --base padrao --escrever   # grava a anotação
```

`eval.rodar` reconfere a anotação contra o índice a cada medição e reclama de
duas coisas: anotação faltando (contagem, porque numa base nova são dezenas) e
anotação **divergente** do que o índice mostra (uma a uma, porque cada uma é uma
pergunta na fatia errada).

Fonte que não dá para decidir — PDF digitalizado sem texto, documento metade em
cada idioma — fica `indefinido` ou `misto`, e o par sai das duas fatias em vez
de entrar na errada. Aparece com o n na coluna `não declarado`.

**Para quem gera conjunto dourado sintético** (`R9.1`, perfil bilíngue): emitir
os dois campos já preenchidos é o que faz o perfil medir a ponte. Um corpus
bilíngue sem `idioma_fonte` produz uma fatia cross-lingual de tamanho zero e um
relatório que parece aprovado.

## Regras ao escrever perguntas

1. **Só pergunta que você faria de verdade.** Pergunta inventada mede um acervo
   imaginário.
2. **A fonte precisa ser conferida por quem conhece o conteúdo.** Palpite a
   partir do nome do arquivo entra como `"validada": false` até alguém abrir.
3. **Verificar que o caminho existe** antes de gravar. Fonte com erro de
   digitação nunca é recuperada e derruba a métrica em silêncio, parecendo falha
   do sistema de busca.
4. **Casos-armadilha valem mais que casos fáceis.** Ver `g010`: o arquivo com o
   maior `_vN` no nome não é o documento vigente.

## Aviso

Este arquivo contém **caminhos reais de documentos corporativos** — nomes de
contrato, fornecedor e projeto. **Decisão tomada em 17/08/2026: nunca publicar.**
`perguntas.jsonl` está no `.gitignore` e só existe no disco de quem indexou o
acervo real — é inútil em qualquer outra máquina, porque a fonte que ele aponta
não existe lá. O mesmo vale para os relatórios de ablação e métricas em `docs/`
que citam essas perguntas por conteúdo.

Isso deixa uma pendência para quem for instalar o sistema do zero: como validar
que a recuperação funciona sem um conjunto dourado pronto? Resolvida em
19/08/2026 — ver abaixo.

E deixa uma segunda, fechada em 31/08/2026 pelo `F4-D.2`: **se o conjunto não é
versionado, editar uma pergunta move a linha de base histórica sem deixar diff.**
As duas tabelas continuam parecendo comparáveis, e nada na tela avisa.

`dourado-v1.toml`, ao lado deste README, é o que fecha isso. Ele é **versionado**
e guarda, por pergunta, o `id` e uma impressão digital de 16 hex do que move a
métrica: o texto, o tipo e as fontes esperadas. Não guarda o texto e não guarda
nome de arquivo nenhum — impressão é de mão única, e o repositório é público.
`notas`, `autoria` e `validada` ficam de fora de propósito: editá-los não muda
número nenhum.

```bash
py -m eval.serie --base padrao              # confere, e diz qual pergunta mudou
py -m eval.serie --base padrao --congelar   # grava a série nova
```

Congelar é ato deliberado, com diff para revisar. `eval/test_serie.py` é a porta:
o conjunto desta máquina que divergir da série reprova, com o id na mensagem.

## Clone fresco — o exemplo sintético

`perguntas.example.jsonl` + `eval/sintetico/corpus/` + `config.sintetico.toml`.
Empresa fictícia (Várzea Clara Energia). Não mede o acervo de ninguém; demonstra
o formato e dá uma régua ao CI. Regras e fronteira em
[`docs/colaboracao.md`](../../docs/colaboracao.md) §5.

```bash
py -m eval.sintetico.gerar          # regenera os arquivos, se precisar
py -m eval.rodar --config config.sintetico.toml --base sintetico
```

`eval.rodar` sem `perguntas.jsonl` e sem `--golden` **avisa** e cai no exemplo.
Um caminho explícito que não existe continua sendo erro — substituir em
silêncio mediria o corpus errado.

## Escreva as primeiras 10 perguntas do *seu* acervo

O exemplo não substitui isto. Um conjunto dourado só funciona sobre os
arquivos de quem o escreveu.

1. Dez perguntas que você faria de verdade, não que soam bem.
2. Abra a fonte e confirme. Palpite a partir do nome entra como `"validada": false`.
3. Cubra os quatro tipos: uns 3 `exato` (código, sigla), 4 `semantica`
   (vocabulário diferente), 2 `temporal` / armadilha de versão, 1 `multihop`.
4. Grave em `eval/golden/perguntas.jsonl` (ou no `dourado` da base). Esse
   arquivo não se publica — já está no `.gitignore`.
5. Meça: `py -m eval.rodar --base SUA_BASE --retriever baseline`, depois
   `--retriever hibrido`. Sem os dois números, a mudança não entra.

## Antes de acreditar no número: quanto ele alcança

```bash
py -m eval.cobertura --base SUA_BASE
```

Segundos, sem abrir o modelo e sem rodar busca. Ele responde a pergunta que o
`recall@1` **não** responde: que fração do seu acervo essas perguntas conseguem
tocar. O resto do índice entra na medição como distrator e nunca como resposta.

Duas consequências, e as duas são silenciosas até você medir:

- Dez perguntas escritas sobre uma pasta medem **aquela pasta**, não o seu
  acervo. O número é real e o rótulo é que está errado.
- Enquanto o conjunto não crescer junto, **indexar mais pastas baixa a métrica**
  sem que nada tenha piorado. Foi o que aconteceu aqui em 24/08/2026, e é o que
  originou este comando ([`docs/dourado-cobertura.md`](../../docs/dourado-cobertura.md)).

Cobertura baixa **não é erro** — no começo ela é baixa por construção. O erro é
não saber qual é. O bloco entra sozinho em todo relatório de `eval.rodar`,
`eval.comparar` e `eval.ablacao_f2`; quando ele diz "não medida", é porque o
relatório foi montado sem índice para medir contra.
