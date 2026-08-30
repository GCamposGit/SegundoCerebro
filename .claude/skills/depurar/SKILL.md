---
name: depurar
description: >
  Achar a causa-raiz de um defeito neste repositório e fechá-lo como classe, não
  como caso. Use ao investigar teste que reprova, suíte vermelha, resultado
  inesperado, indexação que trava ou some com documento, consulta que devolve
  errado, número que não bate. Gatilhos: bug, defeito, falhou, quebrou, não
  funciona, teste vermelho, flaky, intermitente, travou, sumiu, número errado,
  investigar, causa-raiz, por que.
---

# Depurar aqui

## 1. Antes de ler código: qual é o sintoma exato

Cole a mensagem inteira. Nomeie o subsistema pelo mapa de `/navegar` antes de
abrir arquivo. E responda três perguntas que aqui já mudaram o diagnóstico:

- **Reproduz sozinho?** `py -m pytest <arquivo> -q` isolado, depois na suíte
  inteira. Verde sozinho e vermelho junto é **poluição de estado**, não defeito do
  arquivo — foi assim com as seis falhas de `tests/test_watcher.py`, que vinham de
  um teste em `tests/test_smoke_cuda.py`.
- **Reproduz sempre?** Rode três a cinco vezes. Aqui já houve teste que reprova
  com 3,5 GB de RAM livre e passa com 3,9 GB, sem uma linha mudar
  (`tests/test_ocr.py`, `PISO_RAM_OCR_MB`). **Veredito que muda com a janela da
  máquina não é veredito** — grave o regime antes de acusar o código.
- **Reproduz nos dois setups?** O modo de falha aqui é assimétrico com frequência:
  no desktop, com placa, `diagnosticar()` diz `ok` e a suíte fica verde; no
  notebook, sem placa, a mesma linha reprova. Quem só roda de um lado nunca vê.

## 2. Escreva a reprodução mínima antes de consertar

Um teste que falha, ou um script no scratchpad. Sem ele você não sabe se
consertou — sabe que parou de aparecer.

**Bissecte por ordem, não por leitura.** Quando o sintoma é de suíte, o caminho
mais curto é parear módulos:

```bash
py -m pytest tests/test_suspeito.py tests/test_vitima.py -q -p no:cacheprovider
```

## 3. As causas que este repositório já teve

Confira a sua contra estas antes de inventar uma nova:

- **A regra não casou com nada, e o silêncio pareceu sucesso.** Glob, filtro,
  exclusão, chave de config, regex. Menos arquivo é justamente o que se pediu.
  Quatro ocorrências. O que resolve é **contagem por regra conferida contra zero**
  antes de pagar o custo.
- **A guarda cobria metade da superfície.** Duas ocorrências, a segunda sete
  minutos depois da primeira. Pergunte qual metade a sua guarda não vê — e se o
  caso real se esconde num import dentro de função, num segundo call site, ou num
  caminho de código que o produto executa e o teste não.
- **O instrumento tinha o defeito, não o objeto medido.** Cinco ocorrências —
  a classe mais frequente do projeto. Antes de acreditar num número, meça o
  instrumento: a fatia tem n>0? o caminho medido é o que o produto executa?
- **Estado global escrito e não desfeito.** `os.environ`, variável de módulo,
  cache de processo. E lembre: `monkeypatch` só desfaz o que **ele** fez —
  escrita vinda do produto dentro do teste sobrevive à sessão.
- **A causa era o regime da máquina, e a tabela ficou coerente mesmo assim.**
  Blocos em sequência produzem causa falsa: a mesma máscara custou 0× num regime
  e 8× noutro. Braços **intercalados** dentro da janela.
- **Só a distribuição real achou o defeito.** Cinco grafias do mesmo
  identificador; um limite escolhido no abstrato que cortava o caso motivador da
  fase. Olhe a distribuição antes de escolher limiar.

## 4. Conserte na raiz, e entregue a classe

Nada de `try/except` largo, nada de suprimir. E, pela **regra 12**, o conserto
pontual não é a entrega:

> Todo defeito achado em teste ou em medição tem de sair do pacote como classe.
> A entrega é a mudança de método que faz a classe inteira ser pega na próxima
> vez — um teste que confere contrato, uma distribuição que se olha, um
> instrumento que mede o que o produto executa.

Escreva a linha antes de fechar: *"a partir de agora, quem pega esta classe
sozinho é ___"*. Se você não consegue completá-la, ainda não entendeu o defeito.

Os exemplos que já existem, e que valem de modelo:

| Classe | Quem a pega agora |
|---|---|
| régua que nomeia formato que o produto não ingere | `tests/test_fonte_contrato.py` |
| mecanismo de `retrieve/` sem fatia que o exercite | `eval/test_ranking_sintetico.py` |
| Δ zero por insensibilidade lido como empate | `eval/comparar.py::_insensivel` |
| nome real do acervo em arquivo versionado | `tests/test_saneamento.py` |
| produto importando código que o pacote não leva | `tests/test_pacote.py` |
| teste que entrega `os.environ` sujo ao seguinte | `tests/conftest.py::ambiente_devolvido` |
| painel carregando o encoder para abrir | `tests/test_painel.py` |
| consulta voltando a custar uma ida ao banco por item | `tests/test_hybrid.py` |

## 5. Relate

Causa-raiz em uma ou duas frases · o conserto · a evidência colada (saída do
teste, não descrição dela) · **a classe e quem passa a pegá-la**. Se o defeito é
de arquivo do outro setup, **não conserte** — reporte no seu doc e aponte
(regra 8 da §4 de `docs/colaboracao.md`).
