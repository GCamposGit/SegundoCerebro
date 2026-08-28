# Guia de Engenharia 5 Estrelas — Segundo Cérebro (Pacotes Q1–Q10)
**Status:** revisado em 2026-08-25 — **o juiz do guia mudou** (ver Parte 0)
**Data:** 2026-08-24 · **Revisão:** 2026-08-25 · **Origem:** auditoria de qualidade de engenharia (produto final + processo de desenvolvimento assistido por IA)
**Objetivo (revisado):** que o sistema funcione na máquina de um leigo, numa base que nunca vimos — e, **em segundo lugar**, que o repositório resista a uma revisão de dev sênior. A ordem entre os dois é o que esta revisão corrige.
**Formato:** mesmo contrato dos dossiês — um pacote = uma branch = um PR; donos conforme `docs/colaboracao.md` §1.

---

## Parte 0 — A régua que manda (acrescentada em 25/08/2026)

A versão original deste guia tinha um defeito de mira, e ele é instrutivo porque
não é um erro de conteúdo: **o juiz era imaginário**. A régua final dizia "um dev
sênior clonando o repo a frio", e um juiz assim é barato de agradar — ele pede
CHANGELOG, índice de docs, peça pública de processo, teto de linhas por módulo.
Nada disso quebra para o usuário do produto.

O juiz certo está em [`regra-de-ouro.md`](regra-de-ouro.md), tem precedência sobre
este guia, e é um leigo apontando uma pasta que nunca vimos. Três consequências
diretas para os pacotes Q:

1. **Q ordena-se por "o que quebra primeiro para o leigo"**, não por "o que o
   sênior aponta em 10 minutos". `Q2` (instalar) e o **teste e2e do protocolo MCP**
   do `Q5` sobem; `Q3`, `Q7`, `Q8`, `Q9` e `Q10` descem para **P3 — vitrine**.
2. **Nenhum pacote Q é rota de fuga.** Eixo ortogonal não é eixo prioritário: se
   há item de produto aberto (F6 inteira, Office legado, OCR), o Q de vitrine
   espera. Rebaixado não é apagado — cada um continua abaixo, com o motivo escrito.
3. **A régua final deste guia passa a ter duas metades**, e a primeira é a que
   manda. Ver o fim do documento.

O que **não** se rebaixa, e é o que salva o guia: `Q1` continua P0. Dois agentes em
duas máquinas com regras divergentes de linter é drift garantido, e drift entre
agentes atrasa o produto — não é estética. Pelo mesmo motivo o `Q4` (política de
`except Exception`) fica em P1: ele é a política de **arquivo hostil**, e arquivo
hostil é o que uma base desconhecida tem de sobra. "Falhar é aceitável; travar ou
mentir em silêncio, não" é requisito de produto, não de revisão.

---

## Parte 1 — O que já é 5 estrelas (preservar e exibir, não mexer)

Um revisor sênior honesto elogiaria antes de criticar. Estes pontos são raros mesmo em times profissionais:

1. **Docstrings narrativas com decisão, número e data.** `sheets.py`, `familias.py`, `parsers/__init__.py` documentam *por que* cada limiar existe, com medição datada ("medido em 13/08/2026: aba 4.279×22 gerou 3.277 chunks"). Isso é ADR embutido no código — melhor que ADR em pasta separada, porque não descola.
2. **Disciplina de ablação como invariante** ("sem número antes/depois, a mudança não entra") — e cumprida: 20+ docs de ablação com tabelas reprodutíveis.
3. **Post-mortem público** (`docs/truncagem-silenciosa.md` — defeito que custou 80% do texto indexado). Cultura blameless documentada é assinatura de time maduro.
4. **625 testes, razão teste/src de 0,70 linhas, CI a cada push**, isolamento com `tmp_path`/`monkeypatch`, markers para o que exige modelo real ou GPU (`-m 'not modelo and not cuda'`).
5. **Invariantes numerados no README** com teste provando o invariante 6 (servidor funciona com painel desinstalado).
6. **Segurança consciente no painel**: token via `secrets.token_urlsafe` + `hmac.compare_digest`, loopback, e a docstring "porta local não é porta privada". Logger para stderr porque "stdout é do protocolo MCP" — detalhe que 9 em 10 servidores MCP erram.
7. **Governança multi-agente de referência**: `colaboracao.md` (tabela de donos, 9 regras anti-retrabalho, seção "Tentação → custo"), SKILL.md por máquina com "você pode / você recusa", versionamento de parser com regra explícita de bump. **Este é o material que torna o repo exemplar em dev assistido por IA — hoje está escondido; a Parte 3 o expõe.**

**Regra do guia:** nenhum pacote abaixo pode diluir os itens acima. Em conflito, o item acima vence.

---

## Parte 2 — Lacunas que um sênior apontaria (pacotes Q)

### Q1 — CI é só pytest: sem lint, format, types, coverage — **P0** · Dono: qualquer
**Evidência.** `tests.yml` tem um job (pytest, Windows, Py 3.12). Porém o código carrega 95 `# noqa` com códigos do **ruff** (`ANN001`, `BLE001`, `S603`) — ruff é usado localmente, mas **não há config commitada e o CI não o roda**: dois agentes em duas máquinas com versões/regras divergentes de linter é drift garantido, e os `noqa` viram carga de culto.
**Ação.**
1. Commitar a config real em `pyproject.toml` (`[tool.ruff]`: select, ignores, line-length — a que estiver em uso no notebook, congelada).
2. CI ganha jobs paralelos: `ruff check` + `ruff format --check`; falha bloqueia merge.
3. Coverage: `pytest --cov` com `coverage.xml` publicado e **piso realista** (medir primeiro; sugerir gate em -2 p.p. do medido, não um número aspiracional). Badge no README.
4. Type check: **pyright em modo basic** (ou mypy) — o código já tem ~100% de anotações (455 assinaturas com `->`); hoje nada as verifica, ou seja, paga-se o custo das annotations sem colher o benefício. Começar `basic`, subir para `strict` módulo a módulo.
**Aceite.** PR sem lint/format/types/cov não passa; zero mudança de comportamento; contagem de `noqa` não cresce (baseline registrada).

### Q2 — Empacotamento contraditório: `dependencies = []` + requirements.txt sem pins — **P0** · Dono: desktop (já é R8.1; este pacote antecipa o mínimo)
**Evidência.** `pyproject.toml` declara `dependencies = []` enquanto README e CI instalam de `requirements.txt`. Um `pip install segundocerebro` hoje instala um pacote quebrado. Sem lockfile, o CI de amanhã pode falhar por release de terceiro (o repo já viveu isso: pin do ORT 1.18 no smoke CUDA).
**Ação.** Mover dependências reais para `[project.dependencies]` (com extras: `[gpu]`, `[painel]`, `[dev]`); `requirements.txt` passa a ser lock gerado (`pip-compile`/`uv lock`) e o CI instala do lock. Registrar a versão em um lugar só.
**Aceite.** `pip install -e .[dev]` num venv limpo roda a suíte inteira; CI usa lock; `pyproject` é a fonte única.

### Q3 — Módulos gigantes: teto de tamanho como regra de processo IA — **P3 · vitrine** · Dono: cada um no seu território
**Rebaixado em 25/08:** nenhum leigo tropeça em `indexer.py` ter 1.143 linhas. O custo é nosso (contexto queimado por edição), e a regra escrita já colhe quase todo o benefício sem tocar em código.
**Evidência.** `indexer.py` 1.143 linhas, `config.py` 958, `app.py` 891, `store.py` 819. Não é (só) estética: **arquivo grande é o pior caso para edição por agente** — mais contexto queimado por edição, mais conflito entre os dois setups, diff mais difícil de revisar.
**Ação.** Regra em `colaboracao.md`: novo módulo ≤ ~500 linhas; os 4 acima só decompõem **oportunisticamente** (quando um pacote R/C já for tocá-los — nunca refactor-só-por-refactor, que quebra `git blame` das docstrings-decisão). `app.py` é o candidato natural: rotas por domínio em módulos, tabela de rotas central.
**Aceite.** Regra escrita; cada decomposição em PR próprio com suíte verde e zero mudança de comportamento.

### Q4 — Política de exceções escrita (os 34 `BLE001`) — **P1 · produto** · Dono: desktop · **neste PR**
**Mantido em P1 e reenquadrado em 25/08:** isto é a política de arquivo hostil, que é o que uma base desconhecida tem de sobra. O aceite ganha um item de produto: nenhum caminho de ingestão pode engolir exceção **e** seguir como se o documento tivesse entrado — o `sem_parser` silencioso é dessa família.
**Evidência.** 31 `except Exception` concentrados nas bordas certas (subprocesso, parse, CUDA — defensável), mas a política é tácita. Revisor sênior pergunta: "quando `except Exception` é aceitável aqui?"
**Ação.** Seção curta em `ARCHITECTURE.md`: permitido apenas em (a) borda de subprocesso/arquivo hostil, (b) loop de onda que não pode morrer, (c) probe de hardware; sempre com log da exceção real e nunca no caminho de consulta MCP sem re-raise tipado. Cada `noqa: BLE001` ganha o sufixo de motivo (`# noqa: BLE001 — borda de parse, arquivo hostil`); os que não se justificarem, estreitar.
**Aceite.** Política publicada; `noqa: BLE001` sem motivo = falha de lint (ruff `--require-noqa-reason` via `RUF100`+convenção).

### Q5 — Testes: propriedade, mutação leve e o fio ponta a ponta MCP — **e2e em P0**, resto P1/P3 · Dono: notebook (eval/testes de consulta) + desktop (indexação)
**Dividido em 25/08:** o **teste e2e do protocolo MCP é P0** — é a lição do `F4-P.0` virada teste ("o eval media um recuperador que o cliente não executa") e o único que prova o caminho que o leigo executa. Os dois property tests ficam em P1; o smoke de mutação vai para **P3 · vitrine**.
**Evidência.** 625 testes bons, mas quase todos exemplo-a-exemplo; `consulta_fts` (sanitização MATCH) e `chave_de_familia` são funções ideais para property-based; não há teste de integração que fale o protocolo MCP de verdade.
**Ação.**
1. **Hypothesis** nos dois pontos críticos: nenhuma string quebra `consulta_fts` (fuzz de hífens/aspas/operadores/unicode — já é aceite do C3); `chave_de_familia` idempotente e estável sob marcadores empilhados.
2. **Teste ponta a ponta MCP**: subprocesso do servidor em stdio + cliente `mcp` real → `search`→`read_note`→`neighbors` no índice sintético. É o teste que pega quebra de protocolo que nenhum unit pega (e protege o invariante do stdout).
3. **Smoke de mutação** (mutmut/cosmic-ray) uma vez, manual, em `retrieve/` — não como gate, como auditoria: mutantes sobreviventes revelam asserts fracos. Registrar achados em doc.
**Aceite.** 2 property tests + 1 teste e2e MCP no CI; relatório de mutação em `docs/`.

### Q6 — Higiene de repositório público: LICENSE, CONTRIBUTING, SECURITY, templates — **P2**, com um item em P0 · Dono: qualquer
**Revisado em 25/08:** o `.github/PULL_REQUEST_TEMPLATE.md` subiu para **P0 e já foi feito** — é onde as regras 10 a 12 da §4 mordem no merge. `CONTRIBUTING`, `SECURITY` e `pip-audit` ficam em P2.
**Evidência.** README exibe badge MIT (conferir que `LICENSE` está commitado — o dump não cobre arquivos sem extensão). Não há `CONTRIBUTING.md`, `SECURITY.md`, template de PR/issue. O bloco de PR obrigatório vive em `colaboracao.md` §7 — ótimo para os dois agentes, invisível para o público.
**Ação.**
1. `CONTRIBUTING.md` curto apontando para `colaboracao.md` e `ARCHITECTURE.md` (invariantes + "sem número não entra").
2. `.github/PULL_REQUEST_TEMPLATE.md` = o bloco da §7 (corpus da medição, número antes/depois, dono) — o processo vira formulário que humano e agente preenchem igual.
3. `SECURITY.md` (1 página: escopo local-first, painel loopback+token, como reportar).
4. `pip-audit` no CI (semanal, não bloqueante) + Dependabot/Renovate para o lock.
**Aceite.** Clone público sem contexto entende como contribuir em <5 min; auditoria de deps rodando.

### Q7 — Versão, CHANGELOG e releases — **P3 · vitrine** · Dono: qualquer
**Evidência.** `version = "0.0.1"` estático; sem tags, sem CHANGELOG. Para repo-vitrine, release marca narrativa ("F1: híbrido medido"; "F2: famílias+rerank").
**Ação.** SemVer 0.x com tag por fase fechada; `CHANGELOG.md` no formato Keep a Changelog, gerado por fase (não por commit); GitHub Release com o resumo da ablação da fase.
**Aceite.** Tag por fase F1–F3.6 retroativa; release notes apontam para os docs de métrica.

### Q8 — Docs navegáveis: os 67 arquivos merecem um índice — **P3 · vitrine** · Dono: notebook
**Rebaixado em 25/08, com uma exceção:** o índice completo é vitrine, mas `docs/regra-de-ouro.md` e `docs/historico-decisoes.md` **têm** de estar linkados do `CLAUDE.md` e do README — o primeiro porque governa, o segundo porque saiu do retomador.
**Evidência.** `docs/` é o maior ativo do repo e não tem sumário; um visitante não sabe que `truncagem-silenciosa.md` (a melhor peça do repo) existe.
**Ação.** `docs/README.md` com índice temático (decisões · ablações · post-mortems · operação · colaboração); opcional: MkDocs Material publicado via Pages (job `docs` no CI) — sem reescrever nada, só navegação. Selar com link no README raiz: "comece por: post-mortem da truncagem; ablação de famílias; colaboracao.md".
**Aceite.** Todo doc alcançável em ≤2 cliques a partir do README.

### Q9 — O processo multi-agente como artefato público de primeira classe — **P3 · vitrine** · Dono: acordo entre setups
**Rebaixado em 25/08.** É a peça mais interessante do repositório para um leitor externo e não entrega nada ao usuário. O material continua vivo onde é usado (`colaboracao.md`, SKILLs); escrever a peça pública é trabalho de publicação, e publicação vem depois de produto.
**Evidência.** O material de governança IA (colaboracao.md, SKILLs, versionamento de parser, regra "um de cada vez" no despachante) é **estado da arte e está espalhado**. É exatamente o que falta na literatura pública de dev assistido por IA: não prompts, mas *contratos de fronteira entre agentes*.
**Ação.** `docs/processo-ia.md` — peça única, escrita para leitor externo:
1. o modelo mental: dois agentes (Claude Code / Grok Build), duas máquinas, dados disjuntos, tabela de donos por path;
2. os mecanismos anti-conflito: um pacote=um PR, "um de cada vez" em arquivo compartilhado, regra 8 (não corrigir arquivo do outro — reportar), §8 "Tentação → custo";
3. o que falhou e virou regra (a lista da §4 nasceu de retrabalho real — contar 2 casos);
4. como o eval disciplina o agente: "sem número não entra" é o guard-rail que impede o LLM de 'melhorar' ranking por intuição;
5. skills como identidade, não como memória (a distinção já escrita no SKILL.md).
**Aceite.** Doc publicado e linkado do README; um leitor externo consegue replicar o setup de 2 agentes no próprio projeto.

### Q10 — Observabilidade mínima do servidor — **P2 · reenquadrado** · Dono: notebook
**Reenquadrado em 25/08:** o valor não é métrica bonita no painel — é ser **a única fonte de evidência sobre uma base que não é nossa**: consulta que volta vazia, `search` sem `read_note` depois, p95 na máquina do usuário. Quando houver primeiro usuário leigo (F6), isto passa a P1.
**Evidência.** Logging é disciplinado, mas não há métrica de operação: latência por tool, contagem de consultas, taxa de resultados vazios — dados que as ablações offline não veem.
**Ação.** Contador local barato (SQLite, tabela `telemetria`, escrita assíncrona, 100% local — invariante de privacidade intocado): p50/p95 por tool, consultas/dia, % de `search` sem clique de `read_note` subsequente. Painel exibe. **Nunca** telemetria remota.
**Aceite.** `search` p95 visível no painel; overhead <1 ms/consulta; nenhum dado sai da máquina.

---

## Ordem de ataque — revisada em 25/08/2026

| Onda | Pacotes | Racional |
|---|---|---|
| **0 · feito** | template de PR (item do `Q6`) | onde as regras 10 a 12 da §4 mordem no merge |
| **1** | **Q2** (lockfile e extras) · **Q5-e2e** · **Q1** | o leigo que não instala não tem produto; o e2e prova o caminho que ele executa; o `Q1` mata o drift entre os dois agentes |
| **2** | **Q4** · property tests do `Q5` | arquivo hostil, e as duas funções que qualquer string do usuário alcança |
| **3** | resto do **Q6** · **Q10** | higiene pública e a evidência sobre base que não é nossa |
| **4 · vitrine** | **Q3, Q7, Q8, Q9**, mutação do `Q5` | só quando não houver item de produto aberto |

A ordem antiga era `Q1,Q2` → `Q4,Q6,Q9` → `Q5` → `Q3,Q7,Q8,Q10`, e a diferença
que importa é uma: a onda 2 antiga era **três quartos de vitrine**.

## Régua final — duas metades, e a primeira manda

**Primeira metade (produto, e é a que decide).** Um leigo, no Windows dele, sem o
nosso `config.toml`, aponta uma pasta que nunca vimos e em ≤ 30 min recebe trecho
com arquivo e seção — sem editar `PYTHONPATH`, sem saber o que é `sm_52`, sem que a
indexação trave num arquivo hostil e sem que ela diga "pronto" tendo engolido
metade do acervo em silêncio. Isso é a F6 e os itens de produto do `Q2`, `Q4` e
`Q5-e2e`. Enquanto isso não passa, nada abaixo conta.

**Segunda metade (repositório).** Um dev sênior clonando a frio deve conseguir,
sem ajuda: instalar com um comando (`Q2`), rodar a suíte e o lint idênticos ao CI
(`Q1`), achar qualquer decisão com justificativa e número
([`historico-decisoes.md`](historico-decisoes.md)), entender as fronteiras do
processo multi-agente (`colaboracao.md`, e o `Q9` quando for a hora), e não
encontrar nenhum `except Exception` ou `noqa` sem motivo escrito (`Q4`). O que ele
**não** deve encontrar: refactors que apagaram histórico de decisão, cobertura
inflada por teste vazio, ou tooling que contradiz o invariante local-first.

**E o que nenhuma das duas metades tolera**, desde 25/08: defeito consertado como
caso, sem a classe generalizada (regra 12 da §4 de `colaboracao.md`). Cinco dos
melhores achados deste repositório — as grafias do grafo, o `schtasks` mockado, o
chunk medido sem o tokenizador real, os quatro campos de `_montar`, o eval que
media o caminho que o cliente não executa — valem pelo método que ficou, não pelo
caso que sumiu.
