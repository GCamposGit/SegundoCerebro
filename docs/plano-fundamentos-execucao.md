# Plano fundamental — execução por pacotes

Fonte: [revisão de 04/09](revisao-fundamentos-2026-09-04.md). Os pacotes abaixo são propostas; FND-11 é a melhoria de skills aplicada nesta revisão. Símbolos e paths são relativos à raiz. Confirmar a existência no checkout atual antes de editar. P0 protege integridade; P1 protege uso cotidiano; P2 reduz dívida e custo.

## Protocolo para executar um bloco

Leia AGENTS.md e o [procedimento compartilhado](desenvolvimento-eficiente.md). Use uma branch por bloco, fixtures temporárias e o Python verificado. Não executar o plano inteiro em um único diff. Donos se confirmam em colaboração: os rótulos abaixo são capacidades necessárias, não transferência unilateral de arquivos.

Antes: reproduzir o problema; registrar teste e resultado. Implementar apenas paths autorizados; novo módulo pequeno é preferível a ampliar monólito. Depois: teste focal, teste do consumidor entregue, suite/lint/tipos finais. Relatar falhas preexistentes por node ID; não aceitá-las por contagem. Se uma dependência já estiver entregue, conferir seu teste e reutilizar.

Para cada pacote, preencher: SHA inicial, executor, paths finais, reprodução, aceites comprovados, comandos/códigos, limitações, rollback e commit/PR quando autorizado. Parar diante de migração ambígua, novo defeito fora do escopo ou duas tentativas sem evidência nova. Preparar handoff, não inventar contrato.

Os nomes de testes novos abaixo são propostas. Os comandos usam módulos existentes; acrescente o novo arquivo à invocação se optar por arquivo separado. Nenhuma instrução autoriza apagar índices reais, sobrescrever corpus, publicar dados ou mudar modelo padrão.

## FND-01a — Recusar colisão de caminho antes de escrever

P0; complexidade média; indexação + configuração; independente. Novo complemento ao J.c-mapa.2.

Paths: novo `index/identidade_entrada.py`, pontos de entrada em `index/indexer.py`, `tests/test_index.py` e `tests/test_identidade.py`. Reservar pipeline com seu dono. Não migrar schema neste bloco.

1. Criar duas raízes temporárias com `contrato.md`, conteúdos diferentes; demonstrar que o Store atual termina com uma linha. Acrescentar também caso mesmo hash em raízes distintas.
2. Na enumeração prévia, detectar identidade de armazenamento duplicada por caminho relativo. Validar as raízes sem ler conteúdo ou hidratar placeholder. Detectar também conflito entre raiz atual e raiz já registrada, inclusive passada incremental com prefixo.
3. Recusar a passada ANTES de remover/gravar qualquer documento em conflito. Mensagem deve nomear raízes configuradas e caminho relativo, orientar separar bases como mitigação. Não escolher primeiro/último silenciosamente.
4. Não permitir que a recusa dispare reconciliação de remoção. Retornar estado explícito de execução recusada.
5. Testar ordem de raízes invertida, mesmo hash, raiz vazia, duas raízes sem homônimo, índice antigo e --prefixo. Acrescentar caso no ponto de entrada de indexação, não só no helper.

Aceite: colisão não modifica o estado anterior; base sem colisão mantém comportamento. Testes: `python -m pytest tests/test_index.py tests/test_identidade.py -q`. Recuperação: nenhuma migração; reverter commit restaura comportamento anterior. Encerrar após guarda comprovada; não ampliar para redesenho do banco.

## FND-01b — Identidade interna por raiz e caminho

P0 estrutural; alta; depende de 01a e 08b antes de dados reais. Requer desenho revisado antes de execução por agente simples. Relaciona J.b1 sem trocar sua identidade pública de conteúdo.

Paths: `index/esquema.py`, `store.py`, `ingest/chunking.py`, `acesso/registro.py`, `identidade.py`, consumidores de path em retrieve/mcp/index; testes correspondentes. Dividir a lista final em PR de migração e PR de integração conforme donos. Não escrever todos os arquivos no primeiro bloco.

1. Inventariar todos os usos de path como chave (`rg` em src/tests). Definir chave interna opaca para `(root_id, relative_path)` e persistência de root_id. doc_id de conteúdo continua servindo deduplicação/citação; não confundir conteúdo com ocorrência.
2. Definir versão de schema, IDs de chunks e compatibilidade. Path sem raiz só resolve quando único; ambiguidade deve pedir ID. Não deduzir root_id de letra de drive; mover raiz deve ter ação explícita de remapeamento.
3. Criar fixture do schema antigo e migrador para diretório novo. Validar contagem e identidade dos documentos, chunks, FTS, vetores, menções, quarentena e parse store. Preservar o original para rollback.
4. Integrar produtores/consumidores por contrato. Somente retirar a recusa 01a quando os dois documentos homônimos puderem ser indexados e consultados sem colisão.
5. Provar duas raízes com mesmos nomes, mesmo conteúdo em caminhos distintos, mover arquivo/raiz, deletar apenas uma ocorrência e interromper migração.

Aceite: fontes distinguíveis na resposta MCP; migração interrompida não ativa índice parcial; todas as referências migradas resolvem. Rodar suites de index/identidade/hybrid/leitura/grafo e regressão entregue quando ranking for afetado. Rollback: selecionar cópia anterior consistente; não aplicar downgrade destrutivo.

## FND-02a — Integridade por identidade, não só contagem

P0; média; storage; independente de migração. Complementa trava/retomada existentes.

Paths: novo `index/integridade.py`, facade em `index/store.py`, `tests/test_index.py` e `tests/test_dois_passes.py`.

1. Construir SQLite com IDs a,b e vetor com a,c: contagens iguais, estado divergente. Acrescentar IDs densos duplicados.
2. Implementar diagnóstico somente leitura por lotes: órfãos densos, faltantes, duplicados, modelo divergente. Separar pendência legítima do passe lexical de corrupção; usar carimbo de modelo/estado disponível.
3. Preservar chaves antigas de verificar_consistencia para consumidores; expor campos novos explícitos. Erro ao ler LanceDB vira diagnóstico indisponível, não zero vetores.
4. Testar tabela ausente no passe 1, base vazia, erro de I/O, duplicação e conjuntos diferentes de mesma cardinalidade. Inspecionar callers antes de alterar formato de retorno.

Aceite: fixture a,b versus a,c acusa divergência e passe lexical válido não acusa corrupção. Varredura paginada evita vetor completo em RAM; diagnóstico completo não roda por consulta. Testes: módulos index/dois_passes. Rollback: retirar campos adicionais/facade; nenhum dado modificado.

## FND-02b — Recuperação idempotente entre stores

P0 estrutural; alta; depende de 02a. Revisão experiente define protocolo de falha antes de implementar.

Paths: novo `index/operacoes.py`, integração em store/indexer, `tests/test_retomada.py`, `test_indice_em_uso.py` e teste novo de crash.

1. Definir estados persistidos de operação, ID de operação, documento e versão pretendida. Especificar quando leitura fica permitida. Reutilizar trava existente, não criar segundo escritor concorrente.
2. Separar preparar/escrever/verificar/publicar; journal gravado antes de alteração irreversível. Não capturar qualquer falha de delete como tabela ausente.
3. Recovery reexecuta operação sem duplicar vetores e sem marcar ok prematuramente. Integrar com diagnóstico 02a e passe 1/2.
4. Injetar falha após cada etapa: journal, delete, textos, vetores, carimbo, commit e confirmação. Fechar/reabrir Store entre falha e recovery; provar idempotência de duas retomadas.

Aceite: cada estado interrompido termina recuperado ou explicitamente recusado, nunca sucesso inconsistente. Testes de retomada/index/dois_passes e fio de consulta. Rollback: manter leitor compatível com diário pendente; se incompatível, restaurar backup. Não apagar journal pendente para voltar versão.

## FND-03a — Limitar trabalho de pack_folder

P1; média; acesso; independente. Complemento novo ao orçamento R7.3/J.d.

Paths: `acesso/empacote.py`, helper novo de seleção/metadados se necessário, `tests/test_pack_folder.py`. Preservar parser e ranking.

1. Leitor falso registra documentos carregados e pode falhar se ler além do necessário. Criar 1.000 entradas leves sem encoder.
2. Separar manifesto de carregamento de conteúdo. Montar identidade da seleção a partir dos metadados; não carregar todos os canônicos para decidir primeira página.
3. Aplicar limite de documentos/tempo de parse por chamada; limite de resposta não basta. Validar orçamento inválido antes de enumerar/parser.
4. Cursor versionado inclui base, pasta, política, seleção e revisão; progresso não depende de carregar N documentos anteriores novamente. Definir mudança de parser/cache como invalidação ou revisão da leitura, não misturar versões.
5. Manter omissões explícitas e nunca rotular seleção parcial como cobertura completa. Medir chamadas ao leitor em vez de depender só do relógio.

Aceite: primeira página pequena não carrega 1.000 documentos; continuação não reprocessa páginas anteriores; orçamento inválido custa zero parse. Comparar conteúdo da pasta pequena com comportamento anterior. Testes pack_folder/leitura/get_document. Rollback: restaurar implementação anterior; cursor novo recusado com reinício.

## FND-03b — Orçamento estrito e documento maior que a página

P1; média; depende de 03a. Mudança de contrato, pois J.d permite exceder orçamento.

Paths: `acesso/empacote.py`, `mcp/empacote.py`, `docs/jd-pack-folder.md`, testes pack_folder/protocolo. Revisar compatibilidade antes de mudar default.

1. Adicionar modo estrito opt-in inicialmente. Definir unidade como caracteres Unicode do Markdown e limite separado para metadados/itens; não chamar caracteres de tokens.
2. Documento que não cabe é declarado como pendente de get_document, com ID, motivo e próximo passo. Não marcar lido nem excluir silenciosamente. Cursor precisa avançar sem loop e cobertura deve contabilizar os encaminhados.
3. Paginar manifesto/omitidos; se orçamento nem comporta envelope mínimo, devolver erro de orçamento antes de carregar conteúdo.
4. Testar documento de 100.000 caracteres, orçamento de 1, Unicode, milhares de omitidos, item enorme no meio e no fim.

Aceite: Markdown estrito nunca ultrapassa limite; todos os documentos ficam cobertos ou explicitamente encaminhados; cliente chega ao fim sem loop. Preservar modo legado enquanto compatibilidade não for aceita. Rollback: desativar modo opt-in.

## FND-04 — Continuidade detectável de list_folder

P1; média; acesso/MCP; independente; complementar J.c-mapa.2.

Paths: `acesso/manifesto.py`, `mcp/leitura.py`, `tests/test_leitura.py`, teste de protocolo.

1. Reproduzir inserção/remoção entre páginas com cursor por posição. Separar snapshot consistente de enumeração ao vivo com revisão: escolher revisão para o primeiro bloco.
2. Criar cursor opaco opt-in com versão, base, escopo, ordenação, revisão do manifesto e posição. Durante compatibilidade, manter cursor inteiro documentado como legado sem garantia.
3. Comparar revisão na continuação e devolver cursor_desatualizado. Calcular revisão com campos estáveis que detectem mudanças relevantes, incluindo raiz e status. Falha de censo não vira completude.
4. Limitar travessia ao escopo quando seguro; não seguir symlinks nem hidratar nuvem. Instrumentar quantos arquivos são visitados em pasta pequena dentro de raiz grande.

Aceite: sem alteração, cada ocorrência aparece uma vez; com alteração, reinício explícito antes de devolver página incoerente. Testar inserir, excluir, renomear, status mudar, base errada e permissão negada. Rollback: manter decoder legado e orientar reinício de cursores novos.

## FND-05 — Painel responsivo durante operação longa

P1; média; painel; independente. Não é pausa/retomada do indexador já existente.

Paths: `painel/app.py`, `painel/exportar.py`, novo helper de jobs se justificado, `tests/test_painel.py`/`test_vault.py`. Reservar painel.

1. Testar medidor/exportador bloqueado por threading.Event enquanto GET estado acontece, com dois requests simultâneos no mesmo event loop. Event evita benchmark frágil de milissegundos.
2. Tirar execução bloqueante do loop, com concorrência limitada. Começar com worker e resposta síncrona aguardável; job persistente é outro bloco se necessário.
3. Criar/fechar conexões Store dentro do worker. Não compartilhar conexão SQLite da thread da requisição. Definir ocupado, erro e conclusão; limite de um job caro por base.
4. Testar exceção do worker, token inválido, duas solicitações simultâneas e liberação do slot após falha. Cancelamento de request não deve fingir que trabalho nativo foi cancelado; informar estado real.

Aceite: GET estado conclui antes de liberar Event do job; nenhum segundo export pesado paralelo; painel abre sem encoder. Testes painel/vault. Rollback: retornar handler anterior; não interromper escrita ativa ao trocar versão.

## FND-06 — Configuração sem perda de alteração

P1; média; config/painel; 05 torna concorrência mais relevante, mas pode entrar antes.

Paths: `config_escrita.py`, consumidor no painel, `tests/test_config.py`, `tests/test_painel.py`.

1. Criar dois snapshots A/B da mesma configuração. A salva; B não pode sobrescrever silenciosamente.
2. Adicionar escrita condicional com revisão esperada (hash dos bytes lidos) e erro de conflito. Serializar comparação+replace entre processos com trava no mesmo diretório; threading.Lock sozinho não cobre duas instâncias.
3. Usar temporário exclusivo no mesmo filesystem, fechamento antes de replace e limpeza somente do próprio temporário. Não excluir .tmp de outro processo.
4. Preservar assinatura de gravar para consumidores que não precisam CAS ou migrá-los explicitamente. No painel, ler revisão e retornar 409 com ação recarregar ao conflito.
5. Testar primeiro salvamento concorrente, duas bases alteradas, falha de replace, caractere Unicode e configuração inválida.

Aceite: apenas um escritor vence cada revisão, arquivo permanece TOML válido e nenhuma atualização desaparece sem aviso. Testes config/painel. Rollback: manter configuração compatível; recurso só adiciona controle de concorrência.

## FND-07 — Erros MCP coerentes e acionáveis

P1; pequena/média; MCP; independente; extensão de R7.2/Q5, não ferramenta nova.

Paths: novo `mcp/respostas.py`, `mcp/busca.py`, `leitura.py` e adaptadores existentes conforme necessidade; testes mcp/protocolo/leitura.

1. Escrever teste stdio de erro: consulta vazia, ID ausente, cursor inválido, base divergente; registrar envelope atual. Distinguir erro de protocolo de erro operacional.
2. Criar adaptador único CallToolResult com texto serializado e structured_content quando suportado pelo SDK instalado. Preservar payloads de sucesso e não duplicar utilitário por tool.
3. Adotar códigos estáveis e mensagem portuguesa com ação; retry somente em condição recuperável, sem laço automático ilimitado. Consulta legítima sem matches continua sucesso vazio.
4. Conferir outputSchema, se declarado, em sucesso e erro. Não mudar versão de protocolo para obter um campo já suportado.

Aceite: casos operacionais de erro têm isError verdadeiro no wire; consulta sem matches não tem. Testar clientes/dublês que consumiam dict e atualizar interface intencionalmente. Rollback: adaptador compatível, sem migração de dados.

## FND-08a — Diagnóstico operacional somente leitura

P1; média; depende de 02a para integridade completa. Novo, diferente de overview.

Paths: novo `index/diagnostico.py`, entrada CLI ou painel a definir no contrato; testes novos com fixtures públicas.

1. Definir resultado com status, código, evidência, escopo e próxima ação para: índice ausente, escrita ativa, integridade divergente, modelo incompatível, parser indisponível, raiz inacessível e configuração inválida.
2. Usar metadados e helpers existentes de trava/provider/consistência; não carregar modelo, modificar tabelas ou abrir conteúdo da origem.
3. Separar diagnóstico barato e profundo por opção explícita, com limite/cancelamento e progresso no profundo. overview continua a visão agregada do corpus.
4. Testar cada condição, incluindo erro interno do diagnóstico: retornar indisponível, não saudável. Exportação de suporte deve remover caminhos absolutos, queries, conteúdo e tokens.

Aceite: leigo recebe causa e ação em português; teste bloqueia abertura de conteúdo e import de encoder. Rollback: remover nova superfície; nenhuma alteração no índice.

## FND-08b — Backup consistente e restauração verificável

P1; alta; depende de 02a/08a; requisito antes de migração 01b em dados reais.

Paths: novo `index/backup.py`, CLI própria, testes novos. Revisar semântica de snapshot do LanceDB instalado antes de implementar.

1. Definir escopo: registro+FTS, vetores, metadados de versão, config/glossário opcionais; parse cache opcional. Originais não entram automaticamente.
2. Primeiro modo: backup com escritor parado e trava exclusiva comprovada. SQLite via backup API ou fechamento consistente; LanceDB via procedimento compatível verificado. Não tratar cópia de arquivos de banco vivo como snapshot.
3. Manifesto inclui schema/model_id, checksums, contagens e integridade. Não incluir segredos em log ou arquivo publicável.
4. Restaurar para destino novo, conferir checksums/compatibilidade/integridade e executar consulta sintética. Ativação separada; nunca apagar índice original.
5. Testar disco cheio, arquivo truncado, checksum divergente, escritor ativo e versão incompatível. Falha deixa índice anterior intacto.

Aceite: restore reproduz IDs e resultados de fixture e recusa backup inconsistente; zero escrita nas raízes de origem. Rollback: reativar diretório anterior. Não prometer restauração de originais excluídos se eles não estão no backup.

## FND-09a — CI do wheel fora do checkout

P1; pequena; distribuição; independente; complementa F6-A/Q2.

Paths: `.github/workflows/tests.yml`, helper em `scripts/`, testes de empacotamento se necessário. Não atualizar pins GPU/modelo.

1. Construir wheel em ambiente de build controlado. Criar venv temporária fora do checkout e instalar o wheel, não -e. Garantir que dependências vêm da política do job.
2. Mudar cwd para diretório temporário; limpar PYTHONPATH apenas no processo filho. Importar pacote e localizar HTML via importlib.resources.
3. Descobrir entrypoints no metadata do wheel e executar --help nos seis atuais. Testar inicialização MCP/list_tools sem corpus real usando fixture instalável externa; proibir import de eval na instalação.
4. Manter matrix de três sistemas do smoke; não supor que o teste real de OCR/CUDA ocorre nele. Separar resolução aberta de compatibilidade e ambiente fixado de regressão.

Aceite: wheel funciona sem checkout; remover asset de um wheel de teste reprova o smoke. Testar scripts antes de inserir CI. Rollback: reverter apenas job/helper, preservar instalação anterior.

## FND-09b — Dependências e custos de CI explícitos

P2; média; depende de 09a. Dívida já mapeada em Q2; complemento de reprodutibilidade.

Paths: pyproject, locks, workflow e tests de pacote. Inventariar imports runtime antes de mover pytest/httpx para dev. Medir instalação limpa antes/depois com cache declarado. Fixar toolchain de validação de modo consistente; manter job de resolução aberta separado para detectar incompatibilidades futuras. Não usar uma falha no ambiente GPU como licença para mudar default CPU.

Aceite: runtime instala e todas as superfícies importam sem dev; dev executa suíte/checks; lock regenerado pelo comando real e diferenças revisadas. Rollback: lock e pyproject voltam juntos. Ganho em segundos/bytes é medido, não estimado.

## FND-10 — Tipos por fronteira comprovados

P2; pequena por módulo; complemento de Q1/Q16, depende de contratos estabilizados em 07 quando tocar MCP.

Paths: configuração de pyright, um módulo pequeno por bloco e teste de ferramenta fora de src. Habilitar primeiro reportReturnType/reportArgumentType na fronteira escolhida via configuração focal. Corrigir tipos de dados retornados e Protocols necessários sem adicionar Any como escape universal. Criar fixture negativa externa que deve falhar no checker e positiva que passa; não commitar erro deliberado em src.

Aceite: erro real de contrato é detectado, baseline do módulo fica limpo, restante não muda. Rodar pyright focal e global. Rollback: reverter etapa de configuração e tipos juntos. Não religar todos os diagnósticos de uma vez.

## FND-11 — Skills eficientes e agnósticas de executor

Aplicado nesta revisão; oito skills, procedimento comum e AGENTS.md. Validar com `python scripts/verificar_skills.py` e validação comportamental por cenários no relatório de validação. Manter links relativos para três níveis até a raiz. Não copiar o procedimento comum para cada skill.

Aceite estrutural: frontmatter válido, nomes únicos, todos os links internos resolvem e referências estão versionadas na entrega. Aceite comportamental: árvore suja não sofre pull; teste válido não roda três vezes sem motivo; sem GPU não inventa resultado; compare não é chamado PR; erro novo não se compensa pela contagem. Economia financeira fica como hipótese até medir tarefas comparáveis.

## FND-12 — Fila ativa única e handoff verificável

P2; pequena; processo; pode seguir 11. Complementa Q9; não recriar história de roadmap.

Paths: novo `docs/pacotes-ativos.toml`, pequena referência em roadmap/colaboração e helper de validação. Primeiro inventariar pacotes realmente abertos contra PR/SHA. Não converter toda história automaticamente.

Registro por pacote: id, estado (proposto/pronto/em_execucao/bloqueado/entregue), dono, paths, dependências, aceite, evidência de entrega e próxima ação. Manter roadmap como histórico/contexto. Validar ID duplicado, dependência inexistente/ciclo e dois executores com paths sobrepostos; globs exigem expansão sobre arquivos reais e reserva explícita de arquivo novo.

Aceite: pacote entregue sem evidência ou ciclo falha no validador; retomador acha próximo passo sem reler milhares de linhas. Não inferir merge pelo texto 'neste PR'. Rollback: fila nova só é autoridade após reconciliação humana ou evidência do hosting; antes, é proposta.

## Dependências resumidas

01a → 01b; 02a → 02b e 08a; 08a + 02a → 08b; 08b → ativação real de 01b; 03a → 03b; 09a → 09b; 07 → 10 nas fronteiras MCP; 11 → 12. 04/05/06/07/09a podem ser executados em ordem distinta com paths reservados. Independência lógica não autoriza escritores na mesma árvore.

## Prompt de execução reutilizável

“Execute apenas o bloco FND escolhido deste plano no SHA atual. Leia AGENTS.md, confirme pré-requisitos e paths, reproduza com fixture sintética, implemente o mínimo, rode testes de aceite e validação final. Preserve dados e trabalho alheio. Não implemente o bloco dependente junto. Se surgir decisão estrutural não resolvida, entregue reprodução e handoff. Registre comandos e resultados finais; não declare teste, commit ou PR sem comprovação.”
