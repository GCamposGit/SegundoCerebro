---
name: revisar
description: Revisar um diff do Segundo Cérebro por impacto observável, isolamento, procedência e regressões; usar antes de entregar ou na revisão de outro autor.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Revisão por risco

1. Fixe base/head e leia o diff e seus call sites. Não reimplemente o pacote durante revisão somente leitura.
2. Confira isolamento físico entre bases; identidade de raiz/documento; dados privados no diff; fronteiras de abertura de arquivos, nuvem e caminhos longos.
3. Confira os sete invariantes em `CLAUDE.md`/`ARCHITECTURE.md`: custo local, ausência de geração, multi-hop no cliente, avaliação de ranking, procedência, painel independente e bases físicas.
4. Procure falhas observáveis: atualização parcial entre stores; texto velho; omissão/cursor; erro reportado como sucesso; loop síncrono em rota assíncrona; trabalho sem limite antes de paginar.
5. Leia o teste do caminho entregue. Teste que confere apenas a presença de uma palavra não demonstra a funcionalidade. Preserve docstrings de decisão e tetos de módulos; decomponha por necessidade funcional.
6. Reutilize evidência final com mesmo SHA/diff. Caso contrário, aplique a escada compartilhada. Reprovar por nova falha, não apenas por contagem maior.

Cada achado informa prioridade, arquivo/símbolo, gatilho, consequência, reprodução/evidência e correção mínima. Separe confirmado de hipótese e de preferência estética. Não afirmar que toda uma classe está provada por uma única fixture.

Nenhum achado acionável também é resultado válido, com escopo e limitações. CI verde não substitui revisão de semântica, especialmente com diagnósticos de tipos desativados.
