# Estimar quanto tempo a indexação leva

> Medido em 16/08/2026, sobre o run completo do corpus de trabalho: 1.601
> documentos, 1.458 com texto, 92.125 chunks, 64 h de parede entre 13 e 16/08.
> Base empírica da F3.5 bloco D.

Documento de método, não de opinião. Quem for implementar a barra de progresso
tira daqui os coeficientes e, principalmente, os quatro modos de errar.

---

## Os quatro jeitos de errar a estimativa, todos medidos aqui

### 1. Errar o denominador

O censo contou **3.154 arquivos**. O indexador processa **1.601** — o resto cai
nos filtros de extensão e exclusão antes de qualquer leitura. Usar a contagem
bruta como denominador reporta 45% quando o real é 91%, e multiplica a
estimativa restante por cinco.

Este erro foi cometido **por mim, em 15/08, com o banco inteiro disponível**, e
sobreviveu a dois relatórios. Um usuário olhando uma barra não tem chance de
perceber. É a razão de o denominador ter que sair de `iter_files`, o mesmo
enumerador que o indexador usa, e nunca de uma contagem paralela.

### 2. Contar documentos como se custassem o mesmo

| | chunks por documento |
|---|---:|
| mediana | 12 |
| média | 67,8 |
| máximo | **7.017** |

Quase 600× entre a mediana e o pior caso. "Documentos feitos ÷ total" é uma
barra que anda em solavancos e mente nos dois sentidos: corre nas pastas de
DOCX curtos e trava por horas numa planilha.

### 3. Usar tempo de parede

64 h de parede contra ~39 h de trabalho efetivo neste run: **40% do relógio foi
suspensão, hibernação e pausa manual**. Uma taxa calculada sobre tempo de parede
subestima a vazão em quase metade, e a estimativa piora sozinha durante a noite,
quando a máquina está dormindo.

O contador tem que ser de **tempo ativo**: relógio monotônico, com salto acima de
um limiar tratado como suspensão e descontado.

### 4. Extrapolação linear ingênua

É o que a maioria das bibliotecas faz — `decorrido ÷ feito × restante`, o método
do `--eta` do GNU parallel e da maior parte dos wrappers de barra de progresso.
Funciona quando os itens são intercambiáveis. Aqui eles não são: a ordem da
varredura é alfabética por pasta, e as pastas não têm composição parecida.

---

## O modelo que os dados sustentam

**Unidade de trabalho: bytes ponderados por formato.** É o único preditor
disponível **antes de abrir o arquivo** — e abrir para estimar custaria o mesmo
que indexar. O censo já entrega tamanho e extensão sem ler conteúdo.

Medianas medidas sobre 1.419 documentos com duração observada (delta entre
registros consecutivos, descartando intervalos acima de 30 min):

| Formato | n | s/MB (mediana) | s/chunk (mediana) | chunks/doc (mediana) |
|---|---:|---:|---:|---:|
| `.pptx` | 124 | **3,8** | 2,84 | 8 |
| `.pdf` | 602 | **48,7** | 1,69 | 16 |
| `.xlsx` | 296 | **487,2** | 1,73 | 25 |
| `.docx` | 353 | **522,5** | 2,50 | 7 |

Duas leituras, e a segunda é a que desenha o estimador:

- **s/chunk quase não varia entre formatos** — 1,69 a 2,84, fator 1,7. Faz
  sentido: o custo dominante é o encoder, e para ele um chunk é um chunk.
- **s/MB varia 137×.** Um megabyte de PPTX é quase todo imagem e vira 8 chunks;
  um megabyte de DOCX é texto puro e vira centenas.

Ou seja: o **chunk** é a unidade natural de custo, e o **byte** é o único
proxy observável antes do trabalho. O estimador converte um no outro por
formato, e os coeficientes acima são a tabela de conversão inicial.

## Por que o total é confiável mesmo com o item sendo péssimo

A dispersão por documento é enorme — coeficiente de variação **4,6** para s/MB.
Estimar um documento é inútil. Mas a barra não estima um documento: estima a
**soma** de ~1.600, e erros independentes se cancelam na soma.

A ressalva honesta: essa compensação vale plenamente para cauda leve, e esta
cauda é pesada — um único arquivo de 7.017 chunks pesa mais que centenas de
DOCX. Duas consequências de projeto:

1. A saída é **faixa**, nunca ponto. P50 e P90.
2. Os arquivos grandes são conhecidos **antes** (o censo dá o tamanho), então a
   cauda não é surpresa: entra na conta com o coeficiente do formato dela.

## Recalibração durante o run

Os coeficientes acima são desta máquina, deste corpus e do `e5-large`. Trocar
qualquer um dos três invalida a tabela. Por isso ela é **semente**, não verdade:
o estimador recalibra com a média ponderada pelo trabalho já feito
(`soma(segundos) / soma(previsto)`), não por arquivo. Um TXT de 2 KB
não pesa o mesmo que um DOCX de 40 MB, e um outlier é recusado em vez
de mandar a barra para o outro extremo. A tabela só governa os
primeiros minutos.

### Semente em GPU (desktop, 19/08/2026)

A tabela é do notebook (i7-1355U, 15 W, CPU). No desktop, a mesma semente
abriu a barra da base empresas em **5–11 h**; o run real levou **637 s
ativos** (7.873 chunks, e5-large, uma 980 Ti, parse em threads). Razão
medida: **~28×**. Com `SEGUNDOCEREBRO_PROVIDER=cuda` o estimador divide a
semente por `FATOR_GPU = 28` e deixa a média móvel tomar conta depois. Não
entra em `model_id`.

Amortecer é requisito, não refinamento: estimativa que salta a cada documento é
lida como "o programa não sabe", e o usuário perde a confiança que a barra
existia para criar.

## O que a tela mostra

- **Percentual por trabalho** (bytes ponderados), não por contagem de documentos
- **Faixa de conclusão** — "entre 6 h e 9 h", e o horário aproximado
- Números absolutos ao lado: documentos e GB, feitos e totais. Envelhecem melhor
  que uma porcentagem e permitem ao usuário conferir a conta
- **Tempo ativo e tempo parado, separados**
- Contagem por status — `ok`, `sem_parser`, `vazio`, `adiado`, `erro`, `travado`.
  Um corpus onde 8% falhou em silêncio parece um corpus com ranqueamento ruim, e
  os dois pedem correções opostas

O que a tela **não** mostra: estimativa por documento. Com CV 4,6 seria ruído
apresentado como informação.
