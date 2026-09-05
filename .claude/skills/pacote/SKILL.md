---
name: pacote
description: Definir um pacote executável deste projeto, com escopo, evidência, dependências e critério de aceite antes de implementar uma melhoria.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Definir o pacote

1. Confira SHA, branch, diff e dono dos paths. Abra a seção do roadmap e os consumidores relevantes; classifique como novo, extensão, já entregue ou diagnóstico a confirmar.
2. Responda as três perguntas da [regra de ouro](../../../docs/regra-de-ouro.md): ganho para base desconhecida, efeito mínimo observável e encerramento. Para correção determinística, use reprodução e asserção; para ranking, use fatia e IC pareado.
3. Escreva o contrato: problema; paths permitidos; dependências; passos; teste negativo; aceite; recuperação; evidência de entrega. Não tratar ausência de decisão como licença para migrar dados.
4. Divida por fronteira funcional. Migração e ranking não cabem em um pacote entregue por agente simples sem revisão da interface.
5. Declare orçamento antes de experimento. Fatia vazia ou alavanca inerte invalida o instrumento. Empate mensurável encerra; nova grade não é justificativa para reabrir.

Não repita histórico de pacotes fechados. Consulte o dossiê apenas para conferir sobreposição. Uma mudança documental não exige inventar testes de comportamento do produto.
