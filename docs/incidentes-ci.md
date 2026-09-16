# Incidentes de CI

Registro operacional de falhas observadas no GitHub Actions. Este arquivo guarda
o sintoma, a evidência e a decisão de não transformar uma falha de infraestrutura
em uma correção de produto.

## 2026-09-16 — `KeyboardInterrupt` no pytest do Windows

### Escopo

- Repositório: `GCamposGit/SegundoCerebro`
- PRs observados: [#109](https://github.com/GCamposGit/SegundoCerebro/pull/109) e
  [#110](https://github.com/GCamposGit/SegundoCerebro/pull/110)
- Job: `tests / pytest (3.12)` em `windows-latest`
- Comando:

  ```text
  python -m pytest tests/ eval/ -q --cov=segundocerebro --cov-report=xml --cov-fail-under=80
  ```

### Sintoma registrado

No [job 104946714954 do run 35141062193](https://github.com/GCamposGit/SegundoCerebro/actions/runs/35141062193/job/104946714954?pr=110), o processo terminou assim:

```text
.......................
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
D:\a\SegundoCerebro\SegundoCerebro\src\segundocerebro\index\store.py:194: KeyboardInterrupt
(to show a full traceback on KeyboardInterrupt use --full-trace)
23 passed, 60 deselected in 19.09s
Error: Process completed with exit code 1.
```

O mesmo padrão apareceu na primeira execução do PR #110 e em uma execução do
PR #109. A linha 194 é `self.con.executescript(ESQUEMA)`: ela identifica o ponto
em que o processo recebeu o sinal, não a origem do sinal.

### Evidência e classificação

**Confirmado:**

- não houve assertion failure nem erro de cobertura no trecho reportado;
- a interrupção ocorreu durante a inicialização de um `Store` SQLite;
- o código do projeto não contém um emissor de `SIGINT` nesse caminho;
- o workflow não configura timeout de pytest nem retry que esconda a falha;
- o prefixo equivalente passou três vezes localmente com `32/32`;
- a suíte completa local passou com `2026 passed, 3 skipped, 60 deselected`;
- lint, Pyright e smoke do wheel passaram localmente.

**Não confirmado:** a causa externa exata do sinal — cancelamento do runner,
instabilidade do worker Windows ou outra condição do ambiente. O traceback curto
não permite distinguir essas possibilidades.

### Decisão

Não capturar `KeyboardInterrupt`, não adicionar `continue-on-error` e não usar
retry para converter um cancelamento em sucesso. Essas mudanças mascarariam o
contrato de interrupção e poderiam deixar a suíte verde sem validar o produto.

O PR #110 foi mergeado sem alteração de produto; o `main` remoto resultante é
`40b56d1`.

### Procedimento para não repetir o diagnóstico incompleto

1. Registrar URL do run/job, comando, contagem de testes, duração e exit code.
2. Se aparecer `KeyboardInterrupt` sem assertion, repetir o job uma vez e
   verificar cancelamento do job antes de alterar código.
3. Se repetir, executar o diagnóstico com `--full-trace` para obter a pilha
   completa e identificar o emissor/estado do runner.
4. Reproduzir localmente a ordem mínima dos testes, sempre em `tmp_path` e sem
   abrir índice ou acervo real.
5. Só abrir correção de código quando houver causa reproduzível; não transformar
   um ponto de interrupção em uma exceção ignorada.

## 2026-09-04 — falhas de instalação no PR #109

O run [34999676767](https://github.com/GCamposGit/SegundoCerebro/actions/runs/34999676767)
registrou três checks falhos:

- [install-smoke — macos-latest, Python 3.12](https://github.com/GCamposGit/SegundoCerebro/actions/runs/34999676767/job/104484671078?pr=109), falhou em 14 s;
- [install-smoke — ubuntu-latest, Python 3.12](https://github.com/GCamposGit/SegundoCerebro/actions/runs/34999676767/job/104484671155?pr=109), falhou em 13 s;
- [pytest — Python 3.12](https://github.com/GCamposGit/SegundoCerebro/actions/runs/34999676767/job/104484671123?pr=109), falhou em 2 min.

Os checks de Windows install-smoke, lint, resolve-open e types passaram. O
registro disponível para este incidente contém o status e as URLs dos jobs, mas
não o corpo completo dos logs de instalação; por isso não atribui uma causa que
não esteja preservada na evidência.

Após a correção do empacotamento, o smoke local do wheel passou fora do checkout
e o PR #109 foi mergeado. Qualquer nova falha de instalação deve preservar o
log expandido do step antes de uma alteração no workflow.
