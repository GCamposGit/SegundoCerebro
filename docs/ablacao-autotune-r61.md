# `R6.1` — autotune: peso por base, fábrica vira prior

**05/09/2026 · notebook (i7-1355U, 15 W, CPU, sem GPU) · acervo sintético e corporativo ·
varredura RRF canônica (37 triplos) · calibração local sem rede.**

```bash
# Execução direta com relatório markdown
py -m eval.autotune --base padrao --n-perguntas 60 --semente 42

# Gravação dos pesos calibrados na base em config.toml
py -m eval.autotune --base padrao --gravar
```

---

## 1. Por que este pacote existe

A Regra de Ouro do produto (`docs/regra-de-ouro.md`) e a Regra 10 de colaboração
(`docs/colaboracao.md` §4) estabelecem uma barreira estrita:

> *"Ganho de um acervo não vira `[padrao]`. Medido num acervo só, o ganho é daquele
> acervo. Ele entra como prior do autotune (`R6.1`), que é onde peso por base é a
> arquitetura e não o remendo."*

Até este pacote, os pesos canônicos da fusão RRF:

$$\text{denso} = 1{,}0, \quad \text{lexical} = 0{,}25, \quad \text{nome} = 0{,}5$$

eram constantes absolutas herdadas do acervo corporativo. Em bases desconhecidas,
essa presunção falha estruturalmente em dois extremos:

1. **Acervos com nomes de arquivo opacos ou ruidosos** (ex.: `IMG_4021.jpg`, `Scan_001.pdf`,
   notas de voz): atribuir peso 0,5 ao nome polui o topo com coincidências lexicais
   vazias, empurrando chunks densos e lexicais relevantes para fora do top-$k$.
2. **Acervos técnicos e estruturados** (ex.: contratos com numeração estrita, códigos de peças,
   atas com nomes altamente informativos tipo `ATA-2026-Q1-DIRETORIA.docx`): o sinal
   lexical exato e o nome do arquivo carregam quase todo o poder de recuperação,
   enquanto o denso dilui identificadores raros.

O pacote `R6.1` transforma a fábrica de constante imutável em **prior bayesiano**:
um ponto de partida que só é deslocado se o próprio acervo local demonstrar ganho
real e reprodutível.

---

## 2. Desenho do mecanismo (`eval/autotune.py`)

A calibração opera sob cinco restrições do produto:
- **Zero chamadas a LLM externo ou APIs pagas**: geração sintética e avaliação rodam
  estritamente na máquina do usuário.
- **Zero dependência de perguntas anotadas por humano**: o acervo desconhecido não tem
  perguntas prontas nem dourado pré-existente.
- **Eficiência**: o ranqueamento dos candidatos por canal é pré-computado uma única vez
  (`_preparar_candidatos`), permitindo que a varredura completa da grade rode em milissegundos.
- **Persistência explícita**: a procedência da calibração (`ajustado_em`, `n_perguntas`, `mrr`)
  é registrada na seção `[base.<nome>.pesos]` do `config.toml`.

### 2.1 Amostragem heurística (`amostrar_perguntas`)

A amostragem seleciona $N \approx 60$ perguntas divididas balanceadamente em três famílias:

1. **Identificadores exatos** ($N/3$): extraídos via regex (`extrair_ids`) a partir
   de chunks de texto existentes (códigos alfanuméricos, números de contrato, IDs técnicos).
   Testa a sensibilidade ao sinal lexical exato.
2. **Nomes de arquivo informativos** ($N/3$): selecionados a partir de `documentos`,
   filtrando nomes curtos ou puramente numéricos, e limpando separadores e extensões.
   Testa a utilidade real do canal de nome.
3. **Trechos semânticos** ($N/3$): frases iniciais ou períodos de chunks informativos.
   Testa a capacidade do canal denso.

O oráculo (ground truth) de cada pergunta é o próprio documento ou chunk de onde o
estímulo foi gerado.

### 2.2 Grade canônica RRF (`grade_rrf`)

A grade avalia 37 triplos discretos $(\text{denso}, \text{lexical}, \text{nome})$
com passo 0,25 e normalização onde o valor máximo do triplo é fixado em 1,0.
Cobre desde configurações balanceadas até perfis extremos (puro denso, puro lexical,
nome desligado).

### 2.3 Os dois guarda-corpos contra sobreajuste

Ajustar pesos sobre perguntas geradas heuristicamente traz risco intrínseco de
sobreajuste (overfitting). O algoritmo implementa dois guarda-corpos mandatários:

1. **Guarda-corpo de sensibilidade** (`AMPLITUDE_MINIMA_SENSIBILIDADE = 0.05`):
   Se a diferença entre o melhor MRR e o pior MRR de toda a grade de 37 pontos for
   menor que 0,05, o acervo é considerado *insensível* à variação de fusão (paisagem plana).
   O algoritmo aborta o ajuste e mantém o prior de fábrica, registrando a razão no relatório.
2. **Guarda-corpo de ganho mínimo** (`GANHO_MINIMO_MRR = 0.02`):
   O triplo ótimo da grade só substitui o prior se superar o MRR do prior por pelo
   menos 0,02 (+2% de MRR). Pequenas oscilações ou empates numéricos preservam
   estritamente a configuração de fábrica.

---

## 3. Validação em perfis sintéticos

A suíte em `tests/test_autotune.py` valida o comportamento nos cenários esperados:

| Perfil de Teste | Comportamento Observado | Veredito |
|---|---|---|
| **Perfil Ruidoso** (`IMG_0001.jpg`, `Scan_002.pdf`) | O canal de nome degrada MRR quando ativado; a grade derruba o peso de nome para 0,00 ou 0,25. | ✅ Protege contra poluição |
| **Perfil Informativo** (nomes taxonômicos ricos) | O canal de nome correlaciona com o documento alvo; o peso de nome converge para 0,50–1,00 com ganho $\ge 0{,}02$. | ✅ Explora sinal útil |
| **Perfil Plano / Pouco Sensível** | Amplitude $< 0{,}05$; guarda-corpo é acionado. | ✅ Mantém prior intacto |
| **Persistência e Procedência** | `config_escrita.py` salva `[base.pesos]`; `Pesos.validar()` confere tipos e limites. | ✅ Carregamento íntegro |

---

## 4. Fronteira e próximo passo (`R9.1`)

O mecanismo do autotune está **entregue e validado funcionalmente**. A calibração
pode ser executada por qualquer operador de base via CLI.

A validação de generalização ampla — medindo se a auto-calibração melhora o MRR
em múltiplos acervos de teste cegos sem degradação nas fatias frágeis — aguarda
a infraestrutura do **`R9.1`** (harness de benchmark multi-perfil), que fornecerá
a régua comparativa automatizada para cross-validation entre acervos distintos.
