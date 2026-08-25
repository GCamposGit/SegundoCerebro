<!--
Este bloco é o da §7 de docs/colaboracao.md, mais as três linhas de 25/08/2026
(regras 10 a 12 da §4). Preencher tudo: linha em branco só passa com o motivo
escrito ao lado. Quem revisa pergunta primeiro "viola a tabela de donos da §1?" —
se não violar, o CI decide.
-->

```
Setup: desktop | notebook
Fase: F4 | F6 | pacote E | pacote Q | …
Toca: (lista fechada de paths)
Não toca: (o que fica do outro lado)
Corpus da medição: sintetico | corporativo | nenhum
Serve base desconhecida: (que defeito isto conserta para quem instala amanhã)
Efeito mínimo declarado: (fatia, valor, e o veredito que o E5 daria)
Classe generalizada: (que classe de defeito fecha, e o que passa a pegá-la)
```

## O que muda

<!-- Uma frase. Se precisar de três, provavelmente são dois PRs. -->

## Número antes e depois

<!--
Invariante 4: sem número, a mudança não entra. Δ pareado com IC95 de
`eval.comparar` — não dois relatórios de `eval.rodar` lado a lado, que é a
armadilha de leitura documentada em docs/rigor-estatistico.md.

Ganho de um acervo só NÃO vai para `[padrao]` (regra 10), a não ser que seja custo
zero por consulta e independente de acervo. Empate ENCERRA o pacote (regra 11) — e
PR que fecha um pacote com "hipótese refutada" é entrega, não fracasso.

Cite o arquivo de métrica gitignorado pelo nome. Não cole o conteúdo: relatório por
pergunta cita nome de arquivo do acervo real.
-->

## Checklist

- [ ] Não viola a tabela de donos da §1 de `docs/colaboracao.md`
- [ ] Suíte padrão verde (`py -m pytest tests/ eval/ -q`)
- [ ] Nenhum nome real, caminho real ou sigla interna — em código, doc, docstring
      ou mensagem de commit. O vocabulário de exemplo é a VCE
- [ ] Número antes/depois, ou a razão escrita de não haver (pacote sem ranking)
- [ ] Classe de defeito generalizada, com o teste ou método que passa a pegá-la
- [ ] Branch apagada depois do merge (local e remota)
