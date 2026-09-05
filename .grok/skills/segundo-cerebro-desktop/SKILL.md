---
name: segundo-cerebro-desktop
description: Aplicar as responsabilidades do desktop em hardware, pipeline e corpus sintético; consultar atribuições e ambiente atuais antes de executar.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Responsabilidades do desktop

Confirme setup e capacidades reais. A seção vigente de `docs/colaboracao.md` define donos; esta skill não congela versão de driver, contagem de testes, SHA ou pacotes ativos.

Leia a regra de ouro e o procedimento compartilhado. Desktop responde por CUDA, embeddings e laço do indexador conforme atribuição vigente. Ranking e dados corporativos continuam seguindo o contrato do notebook. Arquivo compartilhado exige reserva de escopo, não edição concorrente.

Antes de operação GPU, leia `docs/smoke-cuda.md`, `requirements-gpu.txt` e `tests/test_gpu_extra.py`; confirme provider e hardware. Não atualizar ambiente de produção como parte de uma revisão documental. Hardware nunca entra em model_id; mudança de modelo/chunking exige a coordenação já estabelecida.

Use corpus sintético e fixtures públicas; não fabricar números corporativos. Respeite isolamento de índice e não rodar jobs caros sem orçamento. Registre PID, log e resultado final dos trabalhos em background.

Não fazer pull automático ou repetir pacote antigo listado em histórico. Consulte roadmap e Git atuais. Entrega e handoff seguem o procedimento compartilhado; estado não se duplica nesta skill.
