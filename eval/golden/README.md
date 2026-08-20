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
