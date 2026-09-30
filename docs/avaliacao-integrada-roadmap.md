# Avaliação integrada do roadmap de extração

## Objetivo e limites

Esta avaliação percorre fluxos de uso que atravessam ingestão, índice e MCP.
Usa exclusivamente fixtures VCE sintéticas, bancos em `tmp_path` e hardware
injetado. Não abre nem modifica índices ou acervos reais. O objetivo é verificar
contratos observáveis e contagens, não comparar a qualidade estatística do
ranqueamento.

## Cenários automatizados

| Cenário de uso | Tickets cobertos | Evidência e resultado esperado |
| --- | --- | --- |
| A pessoa pergunta sobre uma pasta com arquivo íntegro, digesto, scan vazio e placeholder. | BUSCA-BURACO | `tests/test_busca_buraco.py`: cada resultado incompleto declara sua limitação; `overview` conta documentos sem canônico sem abrir o original nem expor caminho local. |
| Uma apresentação contém gráfico com cache e gráfico cujo XML não tem valores `c:v`, mas tem XLSX embutido; outra imagem traz texto raster. | GRAFICO-CACHE, GRAFICO-EMBED, IMAGEM-RASTER | `tests/test_ingest.py::test_pptx_grafico_com_cache_entra_no_indice` e `tests/test_raster_ocr.py`: valores do gráfico são recuperados sem duplicação; PNG/JPEG passam pelo OCR injetado, ícones e imagens acima do teto não acionam o motor; o teste CUDA real é opt-in. |
| Uma planilha de produção com mais de 20 mil células é extraída, publicada e lida por páginas MCP. | PLANILHA-CELULA, PLANILHA-LEITURA | `tests/test_roadmap_integrado.py`: parser → publicação no índice temporário → `read_spreadsheet_cells`; a célula V1201 permanece exata, cada resposta respeita o limite pedido e o cursor continua a ordenação. `tests/test_planilha_celula.py` e `tests/test_planilha_leitura.py` cobrem persistência, limites e recusa de cursores inválidos. |
| Um registro antigo perdeu o Parse Store e precisa reconstruir o canônico a partir do TXT ainda inalterado. | CANONICO-BACKFILL | `tests/test_canonico_backfill.py`: o canônico reaparece, a contagem vetorial antes/depois é idêntica e conteúdo alterado, parser obsoleto e PPTX são ignorados. |
| O programa inicia em máquina só-CPU, recebe provider CUDA anunciado mas quebrado, ou encontra duas GPUs com folgas diferentes. | HARDWARE-INICIO | `tests/test_cuda_runtime.py`: decisão depende do kernel efetivamente observado no perfil ONNX; recusa declara motivo, CPU nunca vira CUDA sem GPU aprovada e cada etapa escolhe apenas dispositivo testado com VRAM livre suficiente. O modelo mínimo também executa no provider CPU. |

## Execução integrada

Na raiz do repositório:

```powershell
python -m pytest tests/test_busca_buraco.py tests/test_ingest.py::test_pptx_grafico_com_cache_entra_no_indice tests/test_raster_ocr.py tests/test_planilha_celula.py tests/test_planilha_leitura.py tests/test_canonico_backfill.py tests/test_cuda_runtime.py tests/test_roadmap_integrado.py tests/test_index.py -q
```

O teste físico de OCR CUDA fica separado para não depender da placa disponível
na CI nem tocar dados reais:

```powershell
python -m pytest tests/test_raster_ocr.py::test_raster_ocr_com_kernel_cuda_em_png_sintetico -m cuda -q
```

Esse segundo comando gera um PNG sintético em memória. Se a sonda compartilhada,
o provider CUDA ou o modelo OCR não funcionarem, o teste informa `skip`; a
avaliação injetada continua sendo a evidência determinística para a decisão de
fallback.

## Critérios de aprovação

- Todos os cenários automatizados acima passam; nenhum teste usa o acervo ou o
  índice de uma pessoa.
- Busca e panorama declaram buracos sem vazar caminhos locais.
- Gráficos não duplicam valores entre cache e workbook embutido; raster respeita
  teto de pixels e só ativa OCR quando a rota CUDA aprovada está disponível.
- A leitura paginada mantém arquivo, aba, locator e cursor coerentes, sem ampliar
  a contagem de chunks.
- Backfill muda somente o Parse Store: quantidade de vetores permanece igual.
- O diagnóstico de inicialização registra CPU, placas, compute, VRAM, versão e
  build do ONNX Runtime, providers anunciados, providers cujo kernel rodou e o
  motivo de qualquer recusa. Cada etapa registra o provider e dispositivo
  efetivamente escolhidos.
- O mesmo grupo de testes injetados também deve ser repetido no notebook
  sem o overlay Maxwell antes de marcar o pacote como entregue.

## Verificações manuais propostas para o desktop

Faça os passos abaixo em uma cópia temporária de `config.sintetico.toml`, com a
raiz e o diretório de índice apontando para arquivos sintéticos fora do acervo
real. Não altere `config.toml`, `.mcp.json` nem o índice de uso diário.

1. **Buracos e panorama (BUSCA-BURACO).** Indexe documentos sintéticos íntegros,
   vazios e com placeholder. Consulte `search` e `overview`: cada hit incompleto
   deve explicar a limitação, o panorama deve contar o registro e nenhum
   resultado deve revelar caminho local ou abrir o original.
2. **Gráficos com e sem cache (GRAFICO-CACHE e GRAFICO-EMBED).** Use uma cópia
   temporária de uma apresentação sintética com gráfico em cache e outra cujo
   cache foi removido, mantendo a pasta de trabalho XLSX embutida. Consulte os
   valores pelo MCP e confira que o segundo gráfico foi recuperado da planilha,
   que os valores do primeiro não foram duplicados e que locators apontam para
   os gráficos corretos.
3. **Raster (IMAGEM-RASTER).** Inclua PNG/JPEG sintéticos com texto legível,
   um ícone e uma imagem acima do teto de 2 Mpx. Com CUDA funcional, confirme o
   texto `SCAN-VCE-001` e a GPU aprovada no log; ícone e imagem acima do teto
   não devem acionar OCR. Em CPU, a ingestão continua e não inventa texto OCR.
4. **Células e páginas (PLANILHA-CELULA e PLANILHA-LEITURA).** Consulte no MCP
   uma planilha sintética grande. Confirme conteúdo e locator de células
   individuais e percorra `read_spreadsheet_cells` pelo cursor até
   `Medições!V1201 = 12345.67`. Cada resposta deve respeitar o limite de 200
   células, seguir ordem estável e não aumentar a contagem de chunks/vetores.
5. **Backfill canônico (CANONICO-BACKFILL).** Em uma cópia temporária, remova o
   Parse Store de um TXT ainda inalterado, registre a contagem de vetores e
   execute `segundocerebro-backfill-canonico --config <config-sintetico.toml>`.
   Confirme a reconstrução do canônico, contagem vetorial idêntica e segurança
   em segunda execução. Repita com arquivo alterado, parser obsoleto e PPTX:
   esses casos devem ser ignorados.
6. **Inicialização CPU e fallback (HARDWARE-INICIO).** Defina
   `SEGUNDOCEREBRO_PROVIDER=cpu` e inicie o indexador/MCP sintético. Confira no
   log CPU, versão/build ONNX e provider efetivo; embedding e OCR permanecem em
   CPU, mesmo que a sonda tenha verificado CUDA para diagnóstico. Em seguida,
   simule ou use uma instalação em que CUDA esteja anunciado mas não execute o
   kernel: a recusa precisa explicar o motivo e a ingestão deve terminar em
   CPU.
7. **CUDA aprovada.** Somente em máquina com CUDA funcional, defina
   `SEGUNDOCEREBRO_PROVIDER=cuda` e rode a mesma base com o modelo padrão.
   Confirme no log o kernel executado, compute, VRAM livre e dispositivo
   escolhido por embedding e OCR. Compare conteúdo e identidade do modelo com
   a passada CPU; provider CUDA anunciado sem execução real não é aprovação.

Registre para cada passo: sistema/runtime, provider efetivo, dispositivo,
resultado observado e qualquer diferença entre CPU, GPU desktop e notebook.

## Resultado da execução nesta máquina

- Avaliação integrada do roadmap: 117 aprovados, 3 testes CUDA opt-in separados.
- `eval/`: 312 aprovados e 11 ignorados por exigir census/fixtures douradas locais.
- Suíte `tests/`: 1.817 aprovados, 7 ignorados e 3 falhas de ambiente: o
  ambiente tem `onnxruntime-gpu` 1.23.2 apesar do pin 1.18.0; o executável
  local `segundocerebro-backfill-canonico.exe` não foi instalado; e o Controle
  de Aplicativo do Windows bloqueou o executável temporário do smoke test de
  wheel (`WinError 4551`).
- Ruff, Pyright e harness rápido passaram. A repetição da matriz no notebook sem
  overlay Maxwell continua necessária antes de marcar o pacote como entregue.
