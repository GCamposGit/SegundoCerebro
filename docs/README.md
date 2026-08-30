# Índice da documentação

47 arquivos versionados. **Todo link daqui aponta para arquivo que o clone tem** —
e essa é a regra do índice, não um detalhe: mais da metade de `docs/` fica fora do
Git de propósito, porque cita nome de arquivo do acervo real, e um índice que
prometesse esses arquivos daria 404 para quem clonou. A [seção final](#o-que-não-está-aqui)
explica o que falta e por quê.

Comece por **[`regra-de-ouro.md`](regra-de-ouro.md)** se você vai decidir alguma
coisa, e por **[`truncagem-silenciosa.md`](truncagem-silenciosa.md)** se quer
entender como este projeto trabalha.

---

## Governa — leia antes de decidir

| Documento | O que é |
|---|---|
| [`regra-de-ouro.md`](regra-de-ouro.md) | **Precedência sobre tudo.** O produto é para um leigo apontando uma pasta que nunca vimos. As três perguntas que todo pacote responde antes de começar |
| [`colaboracao.md`](colaboracao.md) | A **única** fonte das regras entre os dois setups: quem mexe em quê, as doze regras anti-retrabalho, o que nunca entra no Git, e a §6 com os números vivos |
| [`rigor-estatistico.md`](rigor-estatistico.md) | `E5`: IC bootstrap pareado obrigatório em toda métrica, e a regra de adoção |
| [`guia-engenharia-5-estrelas.md`](guia-engenharia-5-estrelas.md) | Os pacotes `Q` de qualidade, com a régua final em duas metades — produto primeiro |
| [`matriz-de-armadilhas.md`](matriz-de-armadilhas.md) | Fatia ↔ pacote: qual armadilha cada fatia sintética existe para pegar |
| [`porta-de-latencia.md`](porta-de-latencia.md) | As duas portas de latência do `R9.3`, e o estado térmico que as invalida |
| [`prioridade-de-indexacao.md`](prioridade-de-indexacao.md) | A regra de ondas e pastas na indexação |

## Para quem chega agora

| Documento | O que é |
|---|---|
| [`comecar.md`](comecar.md) | De zero à primeira pergunta respondida. É a `F6-D`, e é a página que o leigo lê |
| [`usar-o-mcp.md`](usar-o-mcp.md) | As três ferramentas, e como ligar nos dois clientes |
| [`painel-de-ajuste.md`](painel-de-ajuste.md) | O painel local: o que ele faz, e por que está fora do caminho de consulta |
| [`arquitetura-tecnica.md`](arquitetura-tecnica.md) | A descrição técnica corrente |

## Post-mortem — o que quebrou, e o que passou a pegar a classe

A parte mais útil do repositório para quem nunca o viu. Cada um é um defeito real
com número, data e a mudança de método que fechou a classe.

| Documento | A classe que ele fecha |
|---|---|
| [`truncagem-silenciosa.md`](truncagem-silenciosa.md) | O encoder truncava em 128 tokens: **80,7% do texto** nunca virou vetor, e nenhuma métrica caiu o bastante para denunciar |
| [`duas-falhas-silenciosas.md`](duas-falhas-silenciosas.md) | Regra de exclusão que não casa com nada falha em silêncio — e menos arquivo é justamente o que se pediu |
| [`fatia-reuniao-invisivel.md`](fatia-reuniao-invisivel.md) | Régua que nomeia formato que o produto não ingere: a fatia que decidiria o pacote tinha n=0, e a declaração dizia n≈100 |
| [`afinidade-e-estado-de-maquina.md`](afinidade-e-estado-de-maquina.md) | Braço de velocidade sem regime de máquina gravado mede a janela, não o braço — 22× de diferença, e uma causa falsa refutada em 2h16 |
| [`dourado-cobertura.md`](dourado-cobertura.md) | Cobertura escrita à mão envelhece calada enquanto a métrica que ela qualifica segue circulando |
| [`ocr-no-acervo-bloqueado.md`](ocr-no-acervo-bloqueado.md) | Por que a `F4-O.3` está bloqueada |
| [`revisao-tecnica-resposta.md`](revisao-tecnica-resposta.md) | Resposta à revisão técnica externa de 12/08 |

## Decisões e crônica

| Documento | O que é |
|---|---|
| [`historico-decisoes.md`](historico-decisoes.md) | A crônica de F0 a F4 — trinta blocos de ablação, com número, data e corpus. **Consulte quando a pergunta for sobre aquele número; não como aquecimento** |
| [`fechamento-f1.md`](fechamento-f1.md) | O fechamento formal da F1 e as cinco portas |
| [`relatorio-avaliacao-resiliente.md`](relatorio-avaliacao-resiliente.md) | As três camadas de avaliação, e por que o dourado real não é juiz |
| [`avaliacao-pacote-e1.md`](avaliacao-pacote-e1.md) | O gerador sintético conferido contra o harness |
| [`spec-estimativa-v2.md`](spec-estimativa-v2.md) | A especificação de estimativa que hoje está em `calibracao.py` — e que refuta a v1 ponto a ponto |
| [`estimativa-de-indexacao.md`](estimativa-de-indexacao.md) | O modelo v1, **superado** pelo acima. Fica pela leitura de por que errava |
| [`dossie-melhorias.md`](dossie-melhorias.md) · [`dossie-complemento-update-devs.md`](dossie-complemento-update-devs.md) | Auditoria externa de 24/08, já conferida contra o código e absorvida pelo `ROADMAP.md` |

## Ablações — a mudança e o número que a autorizou

| Documento | O que mediu |
|---|---|
| [`ablacao-f1.md`](ablacao-f1.md) · [`ablacao-f2.md`](ablacao-f2.md) · [`ablacao-f2-tabela.md`](ablacao-f2-tabela.md) | As fases fechadas, consolidadas |
| [`varredura-pesos-f1.md`](varredura-pesos-f1.md) | A varredura de 37 pontos que escolheu os pesos da fusão |
| [`ablacao-c3a-pesos-fts.md`](ablacao-c3a-pesos-fts.md) | `C3.a`: peso da coluna `caminho` no bm25 — **hipótese refutada** |
| [`ablacao-caminho-entregue.md`](ablacao-caminho-entregue.md) · [`ablacao-f4p-nome-no-entregue.md`](ablacao-f4p-nome-no-entregue.md) | `F4-P`: o eval media um recuperador que o cliente não executa |
| [`ablacao-f4p1-nome-por-fonte.md`](ablacao-f4p1-nome-por-fonte.md) | `F4-P.1`: fechada por **especificação errada**, não por empate — a alavanca agia sobre as vítimas |
| [`ablacao-f4-meetings.md`](ablacao-f4-meetings.md) | Exclusão por papel, e por que glob solto apagaria 15 reuniões |
| [`ablacao-f4-email.md`](ablacao-f4-email.md) · [`ablacao-f4-grafo.md`](ablacao-f4-grafo.md) | Parser de e-mail e o grafo derivado |
| [`fatia-cross-lingual.md`](fatia-cross-lingual.md) | `C4.5`: o recall cai 47% quando pergunta e fonte não compartilham idioma |
| [`custo-miracl.md`](custo-miracl.md) · [`alarme-externo.md`](alarme-externo.md) | A camada 3, e por que o MIRACL-PT não existe |

## Hardware e operação

| Documento | O que é |
|---|---|
| [`smoke-cuda.md`](smoke-cuda.md) · [`rerank-gpu.md`](rerank-gpu.md) | O smoke de CUDA e o cross-encoder nas placas do desktop |
| [`portabilidade-f36.md`](portabilidade-f36.md) | Índice gerado numa máquina, consultado na outra |
| [`plano-ocr.md`](plano-ocr.md) | O plano da `F4-O` |
| [`indexacao-cortes.md`](indexacao-cortes.md) · [`estatisticas-arquivos-por-extensao.md`](estatisticas-arquivos-por-extensao.md) | Cortes de indexação e a varredura de disco |

---

## O que não está aqui

**57 dos 104 arquivos de `docs/` não estão no Git**, e é regra, não descuido: são
quase todos `metricas-*.md`, e relatório por pergunta **sempre** cita nome de
arquivo do acervo — é o que ele é. Eles existem na máquina de quem mediu, e o
`.gitignore` usa **padrão** (`docs/metricas-*.md`), não lista por nome, porque
lista por nome falha em silêncio no arquivo seguinte — foi o que aconteceu com
quatro `metricas-f2-*` em 20/08/2026.

Consequência prática, e ela é da família da `F6`: **64 links em arquivos
versionados apontam para esses arquivos** e resolvem em 404 num clone. Este
índice não os inclui, e o pacote `Q19` do `ROADMAP.md` propõe o teste que impede
o próximo de entrar.

Quando um documento cita um relatório que você não tem, o que falta é o número —
não o raciocínio. O raciocínio está no documento de ablação, que é versionado.
