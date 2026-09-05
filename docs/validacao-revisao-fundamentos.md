# Validação da revisão — 04/09/2026

## Estado do escopo

Revisão e edição de oito skills do projeto, procedimento compartilhado, AGENTS.md, relatório e plano. Código de produto não alterado. Novo helper: scripts/verificar_skills.py. Branch: codex/revisao-fundamentos-skills. Base: d9d6b9e6631cc30de3d41547bf29df827c42e96e.

## Evidências concluídas

- Reproduções temporárias sintéticas: dois registros de contrato.md em raízes diferentes deixam somente raiz_b; pacote com 100.000 caracteres excede budget 8.000 (100.173 caracteres no probe); inserção antes do offset repete c na sequência b,c,c,d.
- Configuração: 151 passed, 1 skipped; skip exige census.toml local ausente. Comando: `.venv/Scripts/python.exe -m pytest tests/test_config_chaves.py tests/test_config.py -q --tb=short --maxfail=2`.
- Ruff de src/tests/eval: aprovado. Ruff do helper: aprovado. Pyright src: zero erros/avisos; vários diagnósticos estão desativados no projeto, portanto isto é verificação parcial de tipos.
- Oito skills aprovadas no quick_validate.py oficial de skill-creator. O helper local também encontra oito skills e zero erros de frontmatter/nome/links.
- Helper exercitado em cinco cenários temporários: diretório sem skills, skill válida, link ausente, nome divergente e frontmatter ausente. O caso válido passa e os quatro inválidos são detectados.
- git diff --check sem erros.

## Validação comportamental por leitura de cenários

Esta é revisão manual das instruções, não ensaio independente com outro modelo.

1. Árvore com alteração alheia: pacote/entregar mandam inspecionar e isolar, não executar pull ou stage amplo.
2. Teste determinístico recém-aprovado: revisar/entregar reutilizam evidência com mesmo SHA/diff; repetição exige mudança ou evidência nova.
3. GPU indisponível: skills de setup exigem diagnóstico; não inventam ausência/presença de GPU nem modificam ambiente por inferência.
4. PR sem CLI: entregar consulta capacidade autenticada disponível e distingue compare de PR real. Não inventa publicação.
5. Mesmo número de falhas com node IDs diferentes: procedimento reprova falha nova, sem compensação por contagem.
6. Medição com fatia vazia: medir encerra como instrumento inválido, não hipótese refutada.
7. Processo sem resultado: procedimento exige status final ou limitação explícita, não aprovação por log parcial.

Uma primeira edição local introduziu links com quatro níveis; o helper os reprovou. Foram corrigidos para três níveis e os validadores repetidos com sucesso. Não houve defeito correspondente nas skills originais: a correção foi da própria edição.

## Ambiente e processos

O sandbox falha ao criar processos com erro apply deny-read ACLs. Leituras/escritas autorizadas e testes foram executados com permissão ampliada. Não houve rejeição automática de autorização.

As primeiras execuções longas perderam a sessão, sem resumo final. O processo oculto tentado também não permaneceu ativo nem criou log/código de saída. A inspeção de processos confirmou ausência de Python ativo naquela verificação. Não se atribui aprovação a essas tentativas.

Duas falhas isoladas em test_comando (cancelar antes da largada e durante a passada) foram causadas por seleção de CUDA sem runtime carregável. O teste retornou 2 failed, 5 passed. Nenhuma dependência foi reinstalada. Uma execução posterior define SEGUNDOCEREBRO_PROVIDER=cpu somente no processo filho, preservando configuração do usuário.

## Limites

Sem benchmark de ranking, teste de OCR real, GPU real ou instalação nova de dependências. Novas propostas estruturais ainda não implementadas. Não houve ensaio com agente mais simples nem medição de tokens faturáveis. Redução de palavras não prova redução de custo financeiro.

A skill Canvas foi consultada, mas não havia diretório gerenciado identificável deste workspace na instalação disponível. A entrega durável é o pacote Markdown executável, integrado ao roadmap.

## Resultado final de testes

- Documentação/saneamento após stage: **87 passed, 2 skipped em 7,66 s**. Os dois skips são da lista local nomes-proibidos.txt ausente; isso NÃO comprova ausência de todo dado privado. O diff deste pacote foi revisado e usa vocabulário sintético.
- Contratos de comando/leitura/pack/protocolo: **66 passed em 17,03 s**, com SEGUNDOCEREBRO_PROVIDER=cpu somente no processo. Comando: `python -m pytest tests/test_comando.py tests/test_leitura.py tests/test_pack_folder.py tests/test_protocolo_mcp.py -q --tb=short`.
- Configuração: **151 passed, 1 skipped**. Os três conjuntos concluídos acima são disjuntos: **304 aprovados e 3 pulados**, sem afirmar que substituem a suíte integral.
- Última suíte ampla em CPU: log até **39%**, sem falha visível nessa tentativa e sem resumo/código final. Processo Python ausente após perda da sessão; diagnóstico da interrupção não estabelecido. Não há job ativo deixado por esta revisão na última inspeção. Não repetir indefinidamente a mesma tentativa.
- Resultado: validações focais concluídas; **suíte integral não homologada neste executor**. Como produto não mudou, a entrega local do plano/skills pode ser revisada; CI completo permanece requisito antes de afirmar merge-ready.

## Entrega

Arquivos preparados em branch própria para commit local. Nenhum push, PR, merge, alteração de dependência ou modificação de índice real fez parte desta entrega. Consultar `git log -1` para o SHA do commit, evitando autorreferência de hash dentro do próprio commit.
