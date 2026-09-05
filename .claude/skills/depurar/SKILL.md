---
name: depurar
description: Investigar falha reproduzível em teste ou comportamento do Segundo Cérebro e corrigir sua causa com uma guarda de regressão.
---

Leia [o procedimento compartilhado](../../../docs/desenvolvimento-eficiente.md) e a seção vigente de [colaboração](../../../docs/colaboracao.md) quando ainda não estiverem no contexto. Caminhos de comandos partem da raiz do checkout.

# Depurar com evidência

1. Registre sintoma, comando, SHA e esperado/observado. Mascare dados privados. Identifique a fronteira no mapa de navegação.
2. Reproduza com fixture temporária e o menor teste que percorra o caminho real. Guarde o resultado antes da correção.
3. Só repita três a cinco vezes se houver indício de intermitência. Se passar isolado e falhar em conjunto, pareie suspeito/vítima com `-p no:cacheprovider`; investigue ambiente, caches e threads.
4. Se a evidência for métrica, confira cobertura, fatia, manipulação e caminho entregue antes de mudar ranking. Para latência, intercale braços e registre regime da máquina.
5. Corrija a causa e cubra a classe observável: colisões em raízes, status falso, cursor inválido, transação interrompida ou estado global, conforme o caso. Prefira asserção de resultado a regex sobre código.
6. Execute teste focal e a validação final compartilhada. Falhas distintas não se compensam por contagem.

Não suprima exceções para fazer o teste passar. Após duas tentativas sem evidência nova, prepare handoff: reprodução, causa ainda incerta, caminhos e próximo experimento discriminante. Em paths reservados, prepare diagnóstico e teste proposto; respeite autorização já concedida pelo usuário.

Saída: causa, correção, comando/resultado, classe coberta e limitações. Falha de ambiente não é falha de produto nem sucesso.
