---
name: medir
description: >
  Medir recuperação neste repositório sem produzir número plausível e errado —
  qual comando, qual caminho de código, cobertura obrigatória, IC pareado,
  insensibilidade, e o que invalida a medição. Use antes de rodar eval, ao ler uma
  tabela de métrica, ao comparar antes/depois, ao medir latência ou velocidade de
  indexação. Gatilhos: medir, eval, recall, MRR, nDCG, ablação, comparar,
  antes/depois, regressão, dourado, cobertura, latência, benchmark, IC, bootstrap,
  varredura, piso de regressão.
---

# Medir sem produzir número plausível e errado

A classe de defeito mais frequente deste projeto **não** é ranking ruim: é
**instrumento de avaliação com defeito próprio** — cinco ocorrências no histórico,
contra quatro de exclusão silenciosa. Um número errado é pior que número nenhum,
porque ele decide.

## Os comandos, e o que cada um mede

```bash
py -m eval.rodar --base <id> --retriever hibrido
```

| Comando | Mede |
|---|---|
| `py -m eval.rodar --base <id>` | `BuscaHibrida.search` — **a série histórica**, nível de documento |
| `py -m eval.rodar --base <id> --entregue` | `buscar_chunks` — **o que o cliente MCP executa** |
| `py -m eval.comparar --base <id> --antes <r> --depois <r>` | Δ pareado ± IC95, a porta de regressão |
| `py -m eval.cobertura --base <id>` | quanto do índice o dourado alcança |
| `py -m eval.idioma --base <id>` | fatia mesma-língua × cross-lingual |
| `py -m eval.latencia --base <id> --maquina <nome>` | p50/p95, exige nome de máquina |

**Os dois primeiros medem coisas diferentes, e essa diferença já custou cinco
fases.** O peso do nome de arquivo era inerte no caminho que o cliente executa e
ninguém sabia; o eval media um recuperador que o produto não roda (`F4-P.0`,
[`eval/entregue.py`](../../../eval/entregue.py)). Antes de afinar peso, confira em
qual caminho ele age.

## O que invalida a medição — confira antes de rodar, não depois

1. **Índice sendo escrito.** `eval/conftest.py` e `tests/conftest.py` recusam em
   milissegundos se houver indexação viva. Medir contra índice em reescrita mede
   alvo em movimento.
2. **Corpus, máquina e data não declarados.** Número sem os três é mentira
   (`docs/colaboracao.md` §4, regra 7). O relatório os imprime; não os apague.
3. **Cobertura ausente.** Nenhum relatório sem a cobertura que ele alcança —
   quantas pastas do índice as perguntas conseguem tocar. Cobertura baixa é
   limitação declarada, não reprovação; **omiti-la** é que faz a métrica de um
   canto do acervo ser lida como a do acervo inteiro. O número vivia escrito à mão
   em dois documentos e estava errado nos dois (18,2% e 25%; o real era 38,5%).
   Hoje `eval/cobertura.py` recalcula a cada passada e `render_markdown` sem
   cobertura imprime **"não medida"** em vez de omitir.
4. **Fatia com n=0.** Δ zero tem duas causas e a regra de encerramento só vale
   para uma. *Empate* é a mudança ter agido sem se separar do ruído;
   *insensibilidade* é a variável não tocar nenhum documento da fatia, e aí o zero
   é por construção. A porta é `eval/comparar.py::_insensivel`, que compara o
   **ranking recuperado** e marca a célula com `∅`. Se você vir `∅`, o pacote não
   foi refutado — ele não foi medido.

## Velocidade e latência têm regras próprias

- **Máquina nomeada e estado térmico gravados.** A mesma máquina entrega 1,6× de
  variação de latência conforme o estado térmico.
- **Braços intercalados dentro da janela, nunca blocos em sequência.** A mesma
  máscara de afinidade custa 0× num regime e 8× noutro, e a mesma máquina entrega
  0,141 e 3,19 s/chunk sem nada do produto mudar — **22×**. Blocos em sequência
  produzem tabela coerente e **causa falsa**, e foi exatamente o que aconteceu com
  o achado 16.1, refutado 2h16 depois pelo próprio autor
  ([`docs/afinidade-e-estado-de-maquina.md`](../../../docs/afinidade-e-estado-de-maquina.md)).
- **Medir com o instrumento real.** O tokenizador de verdade para chunk — o teste
  dizia 19 onde havia 1.850.

## Ler a tabela

- **IC95 pareado, sempre** ([`docs/rigor-estatistico.md`](../../../docs/rigor-estatistico.md)).
  Amplitude de 0,005–0,012 contra intervalo de 0,203 no agregado quer dizer que a
  grade inteira estava dentro do ruído — e o intervalo dizia isso **antes** da
  varredura.
- **Piso de regressão, não autoridade de arquitetura.** A linha de base do acervo
  corporativo bloqueia merge; ela **não** decide arquitetura sozinha. Quem decide
  sobre base desconhecida é a camada 2 (sintético, `E1`).
- **Três camadas, e o dourado real não é juiz:** 1 regressão · 2 decisão ·
  3 alarme de endogamia.

## Depois de medir

- [ ] O relatório traz corpus, máquina, data **e** cobertura
- [ ] O `∅` foi conferido: nenhuma célula decisiva é insensibilidade disfarçada de empate
- [ ] Se deu empate, o pacote **encerra** com "hipótese refutada" no doc
- [ ] O número novo foi escrito **num lugar só** — número que qualifica métrica é
      recalculado pelo relatório, não copiado para documento. Foi assim que 18,2%,
      25% e 38,5% conviveram por quatro dias
