# Porta de custo do MIRACL — C5.a

**26/08/2026, desktop.** Duas GTX 980 Ti (`sm_52`), `e5-large`. Sem download do
MIRACL. Sem smoke de GPU nesta passada: a indexação do acervo privado estava
viva, e o C5.a recusa competir com ela. A taxa é a semente GPU de 19/08/2026
(`docs/estimativa-de-indexacao.md`): 7.873 chunks em 637 s ativos, *uma* 980 Ti,
parse de Office incluído.

Instrumento: `eval/custo_miracl.py`. A suíte padrão cobre a decisão; `--medir`
fica para quando a trava soltar, e substitui a semente pela taxa do encoder em
passagens sintéticas.

---

## As três perguntas (regra de ouro)

1. **Que defeito isto conserta para quem instala amanhã, numa base que não
   conhecemos?** Começar um índice de Wikipedia no meio da primeira indexação
   real — ou pior, baixar 16 GB para descobrir que o split que o dossiê nomeia
   **não existe**. O leigo aponta uma pasta; o alarme da camada 3 não pode
   sequestrar a GPU dela por uma noite, e muito menos por 19 dias, num recorte
   que o dataset publicado não tem.
2. **Efeito mínimo, fatia, instrumento.** Hipótese A: o MIRACL publicado tem
   split `pt`. Hipótese B: embeddar ~1M passagens nesta máquina cabe em ≤12 h
   por modelo; a fatia amostrada (~100k) é a que o C5.a autorizaria se A
   passasse. Instrumento: tabela congelada das 18 línguas (sem download) +
   `horas = n / taxa / 3600` com taxa desta máquina. Empate na porta (12 h
   exatas) **adota**; `>` descarta. Língua ausente descarta os dois recortes
   **antes** do custo, e não pede outra medição.
3. **Se der empate, o que a gente faz?** Encerra. Não se baixa o dump «para
   conferir a tabela». Não se mede de novo com outra grade de lote.

**Classe generalizada:** benchmark externo adotado pelo nome, sem conferir se a
língua existe e se a noite desta máquina chega. O que passa a pegá-la sozinho:
`eval/test_custo_miracl.py` (18 línguas, `pt` ausente, módulo sem
`load_dataset`, trava viva recusa o smoke, `>` 12 h descarta).

---

## Veredito

**MIRACL sai da ablação.** Motivo: `lingua_ausente`.

O dataset publicado (Zhang et al., TACL 2023, tabela 2; README de
[project-miracl/miracl](https://github.com/project-miracl/miracl)) tem 18
línguas — `ar bn de en es fa fi fr hi id ja ko ru sw te th yo zh` — e **não tem
`pt`**. As duas línguas-surpresa são alemão e iorubá. MIRACL é recuperação
*monolíngue* por split; não há o que amostrar em português nele.

A camada 3 do `E3` (alarme anti-endogamia) continua no protocolo. O artefato
não é este. Esta porta **não escolhe o sucessor** — mMARCO-pt, Wikipedia PT
fatiada, ou outro recorte público são pacote novo, e batem na mesma porta de
12 h.

Não se criou `[[base]]`. Não se gravou vetor. Não se baixou dataset.

---

## A conta, mesmo assim

A semente GPU é um **teto de horas**: inclui parse de Office. Wikipedia já
fatiada seria pelo menos tão rápida. Não dobra pelas duas placas — o run de
19/08 usou uma. Notebook, para escala: `ModelSpec` e5-large a 0,63 chunks/s ⇒
1M ≈ 18,4 d, o «~19 dias» do dossiê.

| Recorte | Passagens | h / modelo (semente, 1× 980 Ti) | ×3 modelos R3.1 | Veredito no MIRACL-PT |
|---|---:|---:|---:|---|
| completo (planejado) | 1 000 000 | **22,5 h** | 2,8 d | descartar — `lingua_ausente` (e, se existisse, `custo`: 22,5 > 12) |
| amostrado (C5.a) | 100 000 | **2,2 h** | 6,7 h | descartar — `lingua_ausente` (o custo **caberia**) |

Dois números que o próximo candidato herda:

- **1M passagens nesta máquina, uma 980 Ti, e5-large:** ~22,5 h. Estoura a
  porta mesmo no teto pessimista. Pool de duas placas não medido; `--medir`
  é o que mede, e só com a trava solta.
- **100k passagens:** ~2,2 h por modelo. Cabe numa noite, inclusive ×3
  sequencial (6,7 h). Se um corpus PT dessa ordem aparecer, o recorte
  amostrado passa na porta de *custo*. Continua alarme, nunca decisão; índice
  em diretório descartável, nunca `[[base]]` (invariante 7).

`--medir` agora, nesta máquina, sai 4: a trava de indexação está viva. É o
comportamento certo, não um atalho. Conferir de novo:

```
py -m eval.custo_miracl                  # semente, sem GPU — pode com a passada no fundo
py -m eval.custo_miracl --medir --config config.toml
```

O segundo recusa se qualquer `indexacao.lock` das bases estiver com PID vivo.
Não há flag que desligue isso.

---

## O que isto não é

Não é ablação de modelo. Não mexe em `[padrao]`, em `retrieve/*`, em ranking.
Não é o `E3` inteiro — só a condição de entrada da camada 3. Não autoriza
MIRACL-ES (10,4M passagens, ~10× o planejamento) como proxy de PT: domínio
errado duas vezes (Wikipedia, e língua que o usuário não consulta).
