---
name: medir
description: Planejar e interpretar avaliação de recuperação ou desempenho neste projeto; usar quando ranking, embedding, chunking ou latência forem medidos.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Medir o caminho entregue

Consulte `--help` antes de compor argumentos. Em `eval.rodar`, `--entregue` mede `buscar_chunks`; sem a flag, mede `BuscaHibrida.search` por documento. Use a mesma seleção em `eval.comparar`. Não presumir flags de relatórios salvos: confira a interface real.

Antes de rodar: declare hipótese, população que a alavanca modifica, fatia, efeito mínimo, orçamento e encerramento. Confira n maior que zero, fonte indexada, ausência de escrita no índice e manipulação efetiva. Não habilitar modelo real ou OCR para teste que admite dublê.

O relatório registra SHA, configuração identificável sem segredos, corpus/seed, máquina/regime, data, cobertura, caminho, duração e resultado. Use `eval.cobertura` para cobertura; use Δ pareado e IC95 de `eval.comparar` conforme [rigor estatístico](../../../docs/rigor-estatistico.md).

Intercale braços de desempenho na mesma janela. Diferencie aquecimento e steady state. Não compare duas máquinas como se a mudança de código fosse a única variável.

Camadas: dourado real como regressão; sintético como decisão; externo como alarme. Ganho de um acervo não vira padrão, salvo a exceção estrutural declarada na regra de ouro.

Insensibilidade (`∅`) e fatia vazia invalidam a conclusão. Empate com instrumento sensível encerra a hipótese. Um novo experimento exige instrumento/acervo novo, não apenas outra grade. Relatório privado fica fora do Git; publique somente agregados saneados. Não repetir medição já válida porque a skill de entrega foi carregada.
