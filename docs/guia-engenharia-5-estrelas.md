# Guia de Engenharia 5 Estrelas — Segundo Cérebro (Pacotes Q1–Q10)
**Status:** FINAL — pronto para distribuição aos devs
**Data:** 2026-08-24 · **Origem:** auditoria de qualidade de engenharia (produto final + processo de desenvolvimento assistido por IA)
**Objetivo:** tornar o repositório exemplo público de engenharia — à prova de revisão de dev sênior — nos dois eixos: qualidade do software e qualidade do processo com agentes.
**Formato:** mesmo contrato dos dossiês — um pacote = uma branch = um PR; donos conforme `docs/colaboracao.md` §1.

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

### Q3 — Módulos gigantes: teto de tamanho como regra de processo IA — **P1** · Dono: cada um no seu território
**Evidência.** `indexer.py` 1.143 linhas, `config.py` 958, `app.py` 891, `store.py` 819. Não é (só) estética: **arquivo grande é o pior caso para edição por agente** — mais contexto queimado por edição, mais conflito entre os dois setups, diff mais difícil de revisar.
**Ação.** Regra em `colaboracao.md`: novo módulo ≤ ~500 linhas; os 4 acima só decompõem **oportunisticamente** (quando um pacote R/C já for tocá-los — nunca refactor-só-por-refactor, que quebra `git blame` das docstrings-decisão). `app.py` é o candidato natural: rotas por domínio em módulos, tabela de rotas central.
**Aceite.** Regra escrita; cada decomposição em PR próprio com suíte verde e zero mudança de comportamento.

### Q4 — Política de exceções escrita (os 34 `BLE001`) — **P1** · Dono: qualquer
**Evidência.** 31 `except Exception` concentrados nas bordas certas (subprocesso, parse, CUDA — defensável), mas a política é tácita. Revisor sênior pergunta: "quando `except Exception` é aceitável aqui?"
**Ação.** Seção curta em `ARCHITECTURE.md`: permitido apenas em (a) borda de subprocesso/arquivo hostil, (b) loop de onda que não pode morrer, (c) probe de hardware; sempre com log da exceção real e nunca no caminho de consulta MCP sem re-raise tipado. Cada `noqa: BLE001` ganha o sufixo de motivo (`# noqa: BLE001 — borda de parse, arquivo hostil`); os que não se justificarem, estreitar.
**Aceite.** Política publicada; `noqa: BLE001` sem motivo = falha de lint (ruff `--require-noqa-reason` via `RUF100`+convenção).

### Q5 — Testes: propriedade, mutação leve e o fio ponta a ponta MCP — **P1** · Dono: notebook (eval/testes de consulta) + desktop (indexação)
**Evidência.** 625 testes bons, mas quase todos exemplo-a-exemplo; `consulta_fts` (sanitização MATCH) e `chave_de_familia` são funções ideais para property-based; não há teste de integração que fale o protocolo MCP de verdade.
**Ação.**
1. **Hypothesis** nos dois pontos críticos: nenhuma string quebra `consulta_fts` (fuzz de hífens/aspas/operadores/unicode — já é aceite do C3); `chave_de_familia` idempotente e estável sob marcadores empilhados.
2. **Teste ponta a ponta MCP**: subprocesso do servidor em stdio + cliente `mcp` real → `search`→`read_note`→`neighbors` no índice sintético. É o teste que pega quebra de protocolo que nenhum unit pega (e protege o invariante do stdout).
3. **Smoke de mutação** (mutmut/cosmic-ray) uma vez, manual, em `retrieve/` — não como gate, como auditoria: mutantes sobreviventes revelam asserts fracos. Registrar achados em doc.
**Aceite.** 2 property tests + 1 teste e2e MCP no CI; relatório de mutação em `docs/`.

### Q6 — Higiene de repositório público: LICENSE, CONTRIBUTING, SECURITY, templates — **P1** · Dono: qualquer
**Evidência.** README exibe badge MIT (conferir que `LICENSE` está commitado — o dump não cobre arquivos sem extensão). Não há `CONTRIBUTING.md`, `SECURITY.md`, template de PR/issue. O bloco de PR obrigatório vive em `colaboracao.md` §7 — ótimo para os dois agentes, invisível para o público.
**Ação.**
1. `CONTRIBUTING.md` curto apontando para `colaboracao.md` e `ARCHITECTURE.md` (invariantes + "sem número não entra").
2. `.github/PULL_REQUEST_TEMPLATE.md` = o bloco da §7 (corpus da medição, número antes/depois, dono) — o processo vira formulário que humano e agente preenchem igual.
3. `SECURITY.md` (1 página: escopo local-first, painel loopback+token, como reportar).
4. `pip-audit` no CI (semanal, não bloqueante) + Dependabot/Renovate para o lock.
**Aceite.** Clone público sem contexto entende como contribuir em <5 min; auditoria de deps rodando.

### Q7 — Versão, CHANGELOG e releases — **P2** · Dono: qualquer
**Evidência.** `version = "0.0.1"` estático; sem tags, sem CHANGELOG. Para repo-vitrine, release marca narrativa ("F1: híbrido medido"; "F2: famílias+rerank").
**Ação.** SemVer 0.x com tag por fase fechada; `CHANGELOG.md` no formato Keep a Changelog, gerado por fase (não por commit); GitHub Release com o resumo da ablação da fase.
**Aceite.** Tag por fase F1–F3.6 retroativa; release notes apontam para os docs de métrica.

### Q8 — Docs navegáveis: os 67 arquivos merecem um índice — **P2** · Dono: notebook
**Evidência.** `docs/` é o maior ativo do repo e não tem sumário; um visitante não sabe que `truncagem-silenciosa.md` (a melhor peça do repo) existe.
**Ação.** `docs/README.md` com índice temático (decisões · ablações · post-mortems · operação · colaboração); opcional: MkDocs Material publicado via Pages (job `docs` no CI) — sem reescrever nada, só navegação. Selar com link no README raiz: "comece por: post-mortem da truncagem; ablação de famílias; colaboracao.md".
**Aceite.** Todo doc alcançável em ≤2 cliques a partir do README.

### Q9 — O processo multi-agente como artefato público de primeira classe — **P1** · Dono: acordo entre setups
**Evidência.** O material de governança IA (colaboracao.md, SKILLs, versionamento de parser, regra "um de cada vez" no despachante) é **estado da arte e está espalhado**. É exatamente o que falta na literatura pública de dev assistido por IA: não prompts, mas *contratos de fronteira entre agentes*.
**Ação.** `docs/processo-ia.md` — peça única, escrita para leitor externo:
1. o modelo mental: dois agentes (Claude Code / Grok Build), duas máquinas, dados disjuntos, tabela de donos por path;
2. os mecanismos anti-conflito: um pacote=um PR, "um de cada vez" em arquivo compartilhado, regra 8 (não corrigir arquivo do outro — reportar), §8 "Tentação → custo";
3. o que falhou e virou regra (a lista da §4 nasceu de retrabalho real — contar 2 casos);
4. como o eval disciplina o agente: "sem número não entra" é o guard-rail que impede o LLM de 'melhorar' ranking por intuição;
5. skills como identidade, não como memória (a distinção já escrita no SKILL.md).
**Aceite.** Doc publicado e linkado do README; um leitor externo consegue replicar o setup de 2 agentes no próprio projeto.

### Q10 — Observabilidade mínima do servidor — **P2** · Dono: notebook
**Evidência.** Logging é disciplinado, mas não há métrica de operação: latência por tool, contagem de consultas, taxa de resultados vazios — dados que as ablações offline não veem.
**Ação.** Contador local barato (SQLite, tabela `telemetria`, escrita assíncrona, 100% local — invariante de privacidade intocado): p50/p95 por tool, consultas/dia, % de `search` sem clique de `read_note` subsequente. Painel exibe. **Nunca** telemetria remota.
**Aceite.** `search` p95 visível no painel; overhead <1 ms/consulta; nenhum dado sai da máquina.

---

## Ordem de ataque

| Onda | Pacotes | Racional |
|---|---|---|
| 1 (esta semana) | **Q1, Q2** | são os dois que um sênior aponta em 10 minutos de review; baratos e mecânicos |
| 2 | **Q4, Q6, Q9** | políticas escritas + higiene pública + a peça-vitrine do processo IA |
| 3 | **Q5** | property/e2e/mutação — profundidade de teste |
| 4 | **Q3, Q7, Q8, Q10** | oportunistas e cosméticos de alto retorno |

## Régua final ("o que é 5 estrelas aqui")

Um dev sênior clonando o repo a frio deve conseguir, sem ajuda: instalar com um comando (`Q2`), rodar a suíte e o lint idênticos ao CI (`Q1`), entender as fronteiras do processo multi-agente (`Q9`), achar qualquer decisão com justificativa e número (`Q8`), e não encontrar nenhum `except Exception` ou `noqa` sem motivo escrito (`Q4`). O que ele **não** deve encontrar: refactors que apagaram histórico de decisão, cobertura inflada por teste vazio, ou tooling que contradiz o invariante local-first.
