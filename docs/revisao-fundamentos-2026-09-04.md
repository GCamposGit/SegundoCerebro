# Revisão fundamental do Segundo Cérebro — 04/09/2026

## Decisão recomendada

Priorizar integridade e previsibilidade antes de novos motores de ranking: impedir colisões entre raízes; detectar divergência por identidade entre texto e vetores; tornar leitura de pastas limitada e consistente; manter o painel responsivo; provar instalação do artefato distribuído. Manter OCR avançado, filtros temporais e autotune nos pacotes existentes, sem rebatizá-los como ideias novas.

O [plano de execução](plano-fundamentos-execucao.md) decompõe as recomendações em contratos, dependências, passos, testes negativos e recuperação. Um agente simples pode executar os blocos determinísticos; migrações de identidade e persistência têm etapa explícita de revisão de arquitetura. Nenhum roteiro pode garantir ausência absoluta de erros: o controle é detectar falhas antes de dados reais e não declarar sucesso sem evidência.

## Base e limites da auditoria

Código inicial: `7487536499d47a158ff07515437f36a84b1090f3`. A referência local de origin/main já continha quatro commits adicionais. A branch de revisão parte de `d9d6b9e6631cc30de3d41547bf29df827c42e96e`, incluindo overview, filtro de pasta e versões antigas. Não houve consulta remota para afirmar que esse era o último commit do GitHub.

Inspeção: arquitetura, roadmap, dossiês R/C, guia Q, pacote J, regras de colaboração, oito skills, empacotamento/CI, MCP, leitura/censo, identidade, gravação/configuração, painel e fronteiras de persistência. Foram lidos símbolos e call sites relevantes, não cada linha de cada parser. Reproduções usam dados sintéticos temporários. Não houve benchmark com encoder real, OCR real, CUDA ou leitura do acervo privado.

A suíte ampla apresentou falhas no ambiente original antes das alterações; duas foram isoladas como seleção de CUDA sem runtime carregável. A última tentativa com CPU chegou a 39% sem falha visível, mas perdeu o processo sem resultado final. Portanto não há aprovação da suíte completa. Os conjuntos focais concluídos totalizaram 304 testes aprovados e três skips declarados. Resultados pontuais e diagnóstico do ambiente ficam em [validação](validacao-revisao-fundamentos.md). Não confundir pontinhos verdes parciais com execução concluída.

## O que já está bem resolvido

- Produto com fronteira clara: recuperação local via MCP, multi-hop no cliente, procedência e isolamento físico de bases.
- Leitura integral distinta de chunks, parse store versionado, cursores de get_document ligados ao conteúdo e estrutura Unicode explícita.
- Indexação com limites, subprocesso para arquivos hostis, quarentena, retomada, detecção de nuvem e tratamento de legado.
- Testes de transporte MCP, instalação, isolamento de ambiente, contrato de formatos e regras de configuração.
- Medição distingue caminho entregue e série histórica; existe mecanismo para identificar instrumento insensível.

Preservar esses mecanismos. Não recomendar reescrita, migração de banco, geração no servidor ou novo framework de painel como condição para corrigir os problemas abaixo.

## Qualidade atual em casos de uso

### Duas pastas com os mesmos nomes — FND-01, P0

**Confirmado por reprodução.** `index/esquema.py` declara `documentos.path` como chave primária; `Store.registrar_documento` faz `ON CONFLICT(path)` e atualiza raiz. O censo entrega caminho relativo à raiz. Registrar `contrato.md` em raiz_a e raiz_b deixa uma única linha, da raiz_b. Isso não é deduplicação por conteúdo e compromete origem e cobertura.

O roadmap J.c-mapa.2 já reconhece homônimos entre índice e censo; a recusa de ambiguidade em get_document ajuda na leitura, mas não resolve a identidade de persistência. **Novo complemento:** impedir sobrescrita antes da gravação e planejar identidade interna por raiz+caminho. Não mudar doc_id de conteúdo por conveniência.

### Queda durante atualização — FND-02, P0

**Confirmado no código; crash integral ainda precisa de fixture.** `gravar_chunks` grava SQLite e depois LanceDB; `substituir_vetores` remove e adiciona separadamente. `verificar_consistencia` compara somente contagens. Dois conjuntos distintos de IDs com mesmo tamanho passam nesse critério. Algumas falhas de remoção de vetores são capturadas amplamente e viram debug, mesmo antes de nova adição.

Retomada, trava e USN já existem; não são transação entre dois bancos. **Novo:** reconciliação por IDs/versão e diário de operações idempotente, com recuperação explícita após falha. O diário proposto é de escrita do índice e não substitui o journal USN de eventos do disco.

### Relatório de pasta grande — FND-03, P1

**Confirmado por código e reprodução.** `empacotar` chama `_carregar` para toda a seleção antes de aplicar orçamento. `_preencher` permite o primeiro documento exceder o limite. Com documento sintético de 100.000 caracteres e budget 8.000, o Markdown retornou 100.173 caracteres no probe. O manifesto completo e itens também são repetidos por página.

A exceção de primeiro documento está deliberadamente documentada em `docs/jd-pack-folder.md`: não é descumprimento da implementação atual. **Melhoria nova de contrato:** modo estrito compatível, com encaminhamento explícito a get_document para grandes arquivos, paginação do manifesto e limite de parsing por chamada. R7.3/J.d já tratam orçamento de resposta; falta limitar trabalho antes da resposta.

### Pasta alterada durante a leitura — FND-04, P1

**Confirmado por reprodução da função de paginação.** Listar b,c,d com página de dois itens e inserir a antes de continuar produz b,c,c,d. `list_folder` informa que a lista é ao vivo e manda reiniciar, porém o cliente não recebe um mecanismo para detectar toda alteração.

O contrato atual é honesto sobre a limitação. **Novo complemento:** cursor com revisão do manifesto e recusa explícita de continuação desatualizada; não prometer snapshot real sem implementá-lo. Diferenciar do cursor já versionado de get_document e pack_folder.

### Painel ocupado ou aberto em duas abas — FND-05 e FND-06, P1

**Confirmado no código; teste de concorrência ainda necessário.** `painel/app.py` chama medidor e diagnosticador síncronos dentro de handlers async; `painel/exportar.py` chama `_gerar` diretamente em async. Trabalho longo pode impedir respostas de estado no mesmo event loop. `config_escrita.gravar` usa nome temporário fixo; leitura-modificação-escrita não confere revisão anterior.

Pausa/retomada de indexação já estão previstas/implementadas; a proposta é tornar operações do painel concorrentes de forma limitada e impedir perda de alteração entre processos/abas. Extração para thread exige abrir e fechar o Store dentro do worker, não transportar conexão SQLite criada em outra thread.

### Cliente que recebe erro — FND-07, P1

**Assimetria confirmada.** get_document converte erro em CallToolResult com is_error; search/read_note/outline retornam dicionário com erro. A resposta final do SDK deve ser comprovada por teste no protocolo; não inferir todos os detalhes do envelope a partir do Python.

**Novo complemento ao R7.2/Q5:** taxonomia comum de erro acionável, tratamento no wire e instrução de retomada. Falta de resultados é sucesso vazio; índice indisponível, cursor inválido e documento ausente exigem sinais distintos. A especificação MCP recomenda erro de execução dentro do resultado com isError; isso não exige atualizar protocolo ou SDK neste pacote. [MCP — schema](https://modelcontextprotocol.io/specification/2025-11-25/schema).

## Novas capacidades fundamentais

### Diagnóstico e recuperação pelo próprio usuário — FND-08, P1

overview já oferece estatísticas; o painel já tem diagnóstico de consulta. **Não propor outro overview.** Falta um fluxo operacional que reúna estado de escrita, integridade, compatibilidade de parser/modelo, recursos indisponíveis e ação segura seguinte; junto de backup/restore verificável do índice e configurações do usuário.

Primeiro entregar diagnóstico somente leitura, sem hidratar nuvem, sem carregar encoder e sem revelar segredos. Depois backup consistente sob coordenação da trava e restauração para diretório novo. Não copiar SQLite WAL e LanceDB vivos de forma ingênua. Configuração e glossário são dados do usuário; cache reconstruível e originais têm políticas distintas.

### Pacote realmente instalado — FND-09, P1

**Lacuna confirmada no CI.** O job chamado install-smoke instala com `pip install -e .`; isso testa checkout editável e --help, não o wheel independente. O projeto já tem testes de entrypoints e imports; ampliar sua fidelidade não é refazer F6-A.

Construir wheel, instalar em venv nova fora do checkout, remover PYTHONPATH e provar assets do painel e tools MCP. Avaliação que depende de eval ausente deve recusar claramente. A PyPA distingue instalação editável de desenvolvimento e instalação regular de teste. [PyPA — layouts](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).

## Qualidade e eficiência do código

### Verificação de tipos que cubra contratos — FND-10, P2

`pyproject.toml` desliga vários diagnósticos relevantes: argumentos, chamadas, atributos, retorno e opcionais. É uma dívida já reconhecida no Q1; **não é nova**. O complemento é uma escada por fronteira pública com teste negativo que comprove que o diagnóstico realmente reprova. Começar com envelopes/cursores e interfaces pequenas, sem transformar refatoração estética em pré-requisito do produto.

### Custos escondidos de navegação

Além do carregamento integral em pack_folder, `manifesto._complementar_com_censo` percorre raízes inteiras antes do recorte de pasta, e overview percorre paths para agrupar. A agregação não tem necessariamente custo constante. Medir chamadas e volume visitado em fixtures de tamanhos crescentes antes de propor cache; TTL que esconda documento novo não é ganho de produto. FND-03/FND-04 incluem essa medição.

### Configuração de dependências e CI

Q2 já introduziu lock. O job de tipos ainda instala com resolução aberta e pytest-cov no job principal não usa o pin do lock. pytest/httpx estão nas dependências de runtime. FND-09 pode registrar tamanho/tempo de instalação e separar dev dependencies, mas deve fazê-lo em PR próprio após conferir importações; não remover pacotes sem testar wheel. A prioridade é instalação confiável, não trocar gerenciador de pacotes.

## Processo, agentes e skills — FND-11 aplicado

As oito skills do projeto foram revistas. Antes: 6.627 palavras; depois: 1.863, mais 788 no procedimento comum. A soma caiu para 2.651 (aproximadamente 60% menos palavras). A contagem é por split de espaços, não tokens faturáveis. Benefício financeiro ainda não medido.

Correções realizadas: remover SHA/contagens/fases congeladas; verificar links relativos automaticamente; eliminar pull indiscriminado; não inferir identidade/hardware pelo modelo; não fixar ausência de gh; não inventar coautoria; distinguir compare/PR; substituir comparação de contagem de falhas por identidade de falha; condicionar repetição de testes a evidência; compartilhar validação em vez de repeti-la em revisar e entregar.

Criado AGENTS.md para entrada neutra e procedimento compartilhado com contrato de tarefa, escada de testes, handoff, propriedade de paths, monitoramento de processos e escalonamento após tentativas sem evidência. As skills permanecem nos locais versionados que os agentes existentes usam; nenhum plugin/global SKILL.md foi alterado. Alterar todas as skills instaladas no computador, incluindo documentos e mídia, não seria melhoria específica deste projeto e criaria efeito externo desnecessário.

O roadmap extenso mistura história, status e fila, e CLAUDE.md/skills repetiam estados. FND-12 propõe um registro pequeno de pacotes ativos, separado da história, com dono, dependências, estado, SHA/PR e aceite. Adoção não precisa de banco de tarefas nem serviço pago.

## Não duplicar o planejamento existente

- OCR melhor: F4-O.4/R1.2/R1.5. Manter como avaliação futura com corpus público/representativo; não recomendar apenas outro motor.
- Autotune, reranker e dimensões temporais: R6.1/R6.2/R6.3. Filtro de pasta e versões antigas já constam no código base desta revisão.
- Navegação/visão geral: R7.1 e pacote J. overview, outline, get_document, pack_folder e exportação já existem.
- Refatoração de módulos e lint: Q3/Q16/Q18. Fazer costuras a serviço das correções, sem reescrever tudo.
- CI, empacotamento e docs: Q1/Q2/Q8/Q19/F6. Propor testes de wheel e fidelidade dos checks como complementos.
- Multiusuário, ACL e banco alternativo: F5, dependente de demanda real. Não antecipar.

## Ordem e custo do trabalho

Onda imediata: FND-01a (recusa segura), FND-02a (integridade), FND-07 (erros) e FND-09a (wheel). São blocos que reduzem riscos silenciosos e tornam o restante verificável.

Onda de uso: FND-03a/b (trabalho e resposta limitados), FND-04 (continuidade), FND-05 (painel responsivo), FND-06 (salvamento sem sobrescrita).

Onda estrutural: FND-01b e FND-02b após revisão de arquitetura; FND-08a/b diagnóstico e restauração; FND-10 tipos por fronteira; FND-12 fila ativa. Dependências exatas estão no plano.

Não estimar dias com falsa precisão. Cada bloco declara complexidade pequena/média/alta e critério de parada. Medir tempo, chamadas de ferramenta, contexto carregado e retrabalho nas primeiras cinco entregas comparáveis; economia só pode ser afirmada com dados equivalentes de antes/depois.
