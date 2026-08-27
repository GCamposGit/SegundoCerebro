# Alarme externo — C5.c

**26/08/2026, desktop.** Sucessor do MIRACL na camada 3. Sem download. A
indexação do acervo privado segue no fundo; esta porta não compete com ela.

Instrumento: `eval/alarme_externo.py`, sobre a conta de 12 h de
[`custo-miracl.md`](custo-miracl.md).

---

## As três perguntas (regra de ouro)

1. **Que defeito isto conserta para quem instala amanhã?** Se só medimos o
   gerador VCE, dá para “melhorar” o sintético enquanto o recuperador falha em
   português de verdade. O leigo aponta uma pasta, não a VCE. A camada 3 é o
   canário — não o produto, não o juiz de peso.
2. **Efeito mínimo.** Hipótese: existe recorte PT **nativo**, com qrels, licença
   aberta e ≤12 h nesta máquina. `quati-50k`: **~1,1 h**, passa. `quati-1m`:
   22,5 h, a porta corta — não se baixa o milhão porque “já veio pronto”.
   Empate na porta adota; `>` descarta. Tradução e língua ausente descartam
   **antes** do custo.
3. **Se der empate?** Encerra. Não se baixa o 10M nem o mMARCO “para comparar”.

**Classe generalizada:** sucessor do MIRACL adotado pelo nome, sem passar na
porta de língua, licença e orçamento. O que passa a pegá-la:
`eval/test_alarme_externo.py` (camada 3 = `quati-50k`, 1M estoura, mMARCO sai
por tradução, módulo sem `load_dataset`).

---

## Veredito

**Camada 3 = Quati amostrado (`quati-50k`).** Canário cross-lingual = Pirá 2.0.
mMARCO-pt, Quati-1M/10M, MIRACL-PT e JurisTCU **não** ocupam a camada 3.

| Artefato | Passagens | Queries | h / modelo (semente) | Papel | Veredito |
|---|---:|---:|---:|---|---|
| `quati-50k` | 50 000 | 50 | **1,1 h** | alarme | **adotar** |
| `pira-2` | 4 074 | 2 258 | minutos | canário PT↔EN | adotar *como canário* |
| `quati-1m` | 1 000 000 | 50 | 22,5 h | — | descartar — `custo` |
| `quati-10m` | 10 000 000 | 50 | ~9 d | — | descartar — `custo` |
| `mmarco-pt` | 8 841 823 | 6 980 | ~8 d (amostra caberia) | — | descartar — `traducao` |
| `miracl-pt` | — | — | — | — | descartar — `lingua_ausente` |
| `juristcu` | 16 045 | 150 | 0,4 h | — | descartar — `dominio_estreito` |

Fontes, sem baixar: Bueno et al. 2024 ([Quati](https://huggingface.co/datasets/unicamp-dl/quati),
CC-BY-4.0); Bonifacio et al. 2021 (mMARCO); Pirozelli et al. (Pirá 2.0);
Fernandes et al. 2025 (JurisTCU); C5.a (MIRACL).

---

## Limites do alarme, declarados antes de medir

- **n=50.** Fatia pequena. O alarme dispara se o IC do Δ nDCG@10 no Quati
  **excluir zero para baixo** enquanto o sintético sobe. Não escolhe peso
  (regra 10).
- **Qrels de LLM** (κ≈0,31). Canário, não ouro.
- **e5-large entrou no pool** que montou os qrels. Viés a favor do nosso
  encoder. Serve para “o gerador VCE é o único mundo que a gente acerta”; não
  serve para ablação e5 vs mpnet.
- **Nunca `[[base]]`.** Diretório descartável. `--medir` recusa trava viva.

mMARCO-pt fica fora por três motivos independentes: tradução (Quati e MTEB-BR
já recusam nativo), licença *non-commercial research* da MS MARCO, e
contaminação — o e5 treinou na família, o alarme não dispara.

JurisTCU caberia na porta e tem n=150, mas é jurisprudência de um tribunal.
Pacote à parte se um dia for alarme jurídico; não é o sucessor do MIRACL.

---

## O que ainda não aconteceu

Não se baixou o Quati. Não se indexou. O recorte de 50k só entra com a trava
solta:

```
py -m eval.alarme_externo
py -m eval.custo_miracl --medir --config config.toml
```

O segundo recusa se a indexação estiver viva. Não há flag que desligue isso.
