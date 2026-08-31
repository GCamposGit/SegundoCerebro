"""A camada de acesso ao corpus — o segundo modo de consumo (pacote J).

O produto tinha um modo: pergunta curta, top-k trechos, o cliente responde.
`search`, `read_note` e `neighbors` servem esse modo. O modo que este subpacote
abre é **ingestão integral dirigida por agente** — *"escreva um paper sobre esta
pasta"* —, onde o agente precisa **enumerar, mapear e ler** em vez de perguntar.

Aqui mora só a parte pura: identidade pública de documento e as consultas de
leitura sobre o registro. A superfície MCP que as expõe está em `mcp/leitura.py`,
e a razão de estarem separadas é a de sempre neste repositório — o que é testável
sem transporte não deve exigir transporte para ser testado.

Nada deste subpacote entra no caminho de consulta: ele não ranqueia, não funde
sinal e não toca `retrieve/hybrid.py`. É o que a "ablação nula" do pacote J
exige provar a cada PR.
"""
