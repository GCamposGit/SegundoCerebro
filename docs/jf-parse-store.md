# J.f — medição do Parse Store no Desktop

## Plano registrado antes das medições — 02/09/2026

Defeito a evitar: anunciar o ganho do cache isolado como redução do rebuild
inteiro. A integração já existe; este pacote não altera código de produção.
Escopo fechado: `eval/parse_store_benchmark.py`, `eval/parse_store_corpus.py`,
`eval/test_parse_store_benchmark.py`, este documento, resultado JSON sintético,
`CLAUDE.md` e `ROADMAP.md`.

População: seis arquivos VCE sintéticos, dois por rota (PDF textual, Word OLE
convertido pelo LibreOffice, PDF rasterizado com OCR real). Sem corpus privado.
Encoder real e5-large já instalado, CPU, quatro threads, um worker de parse.
Sem downloads de modelos, alteração de configuração do usuário ou índice real.

Procedimento e parada:

1. Gerar o corpus fora do relógio. Rodar um rebuild de aquecimento descartado,
   que também produz o Parse Store usado para preparar todos os braços quentes.
2. Seis pares intercalados frio/quente, cada braço num processo novo e índice
   novo. Frio = nenhum Parse Store; quente = só Parse Store copiado. Nunca
   reutilizar vetores nem registros de documentos. Pré-ler o corpus nos dois
   braços; cache do SO não é limpo nem controlado (não chamar de disco frio).
3. Cronometrar criação do encoder/store, carga do modelo, `indexar`, commits e
   fechamento. Imports, geração, cópia do cache e auditoria ficam fora. Guardar
   também duração do processo e tempos de etapas já medidos pelo produto.
4. Aceite funcional: os seis documentos precisam chegar a `ok`, com chunks;
   canônico, registro estável, texto dos chunks e bytes dos vetores devem
   coincidir entre braços e aquecimento. Timestamps de execução e organização
   física dos bancos não são conteúdo e não entram na comparação.
5. Aceite do contraste: zero hits frios e todos os acessos quentes atendidos;
   as três rotas precisam ser efetivamente exercitadas. Falha funcional, falta
   de modelo/motor, timeout de 300 s por processo ou estado inconsistente
   invalida o experimento, em vez de declarar ganho.
6. Métrica primária: média das reduções pareadas `1 - quente/frio` no rebuild
   completo, IC95 por bootstrap pareado com semente fixa do harness. Meta ≥80%;
   confirmação exige também limite inferior do IC ≥80%. Média <80% refuta a
   hipótese neste corpus; faixa cruzando o alvo é inconclusiva. Encerrar após
   seis pares, sem ampliar amostra ou ajustar parâmetros após ver o resultado.

Registrar estado de CPU, RAM, alimentação e temperatura disponível antes/depois.
Windows pode não expor temperatura: ausência será explícita, não estabilidade
presumida. Seis pares medem variação de execução, não diversidade de acervos;
este mix pequeno não permite generalizar a meta para qualquer base.

## Reuso e fontes primárias

O [pyperf](https://pyperf.readthedocs.io/en/stable/runner.html) orienta processos
independentes, aquecimento, timeout e metadados. O
[ASV](https://github.com/airspeed-velocity/asv/blob/main/docs/source/benchmarks.rst)
separa preparação do trecho cronometrado e intercala rounds. Não os adicionamos
como dependências: `eval.regime.ordem_intercalada`, `eval.estatistica.ic_da_media`,
gerador de documentos e instrumentação `medicoes` já cobrem o experimento.

O PDF digitalizado do gerador existente é uma página **vazia**, não uma imagem
com texto; por isso esta fixture rasteriza texto sintético de verdade. O Word
antigo é convertido de DOCX pelo LibreOffice antes da medição, não um container
OLE artificial que o conversor não conseguiria abrir.

## Reprodução

`py -m eval.parse_store_benchmark --out index-jf-experimento`

O destino precisa ser inexistente. Todo material é sintético e fica nele;
resultados em `resultado.json`. Não executar junto com testes ou indexação.

## Pré-checagem inválida e correção do desenho, antes dos pares

O primeiro aquecimento foi recusado: os dois scans chegaram a `vazio`, não OCR.
Um probe do mesmo scan extraiu 504 caracteres sem teto e com teto de 2.048 MB;
com o teto adaptativo de 560 MB retornou vazio. Nenhum par de desempenho foi
contado. Isso expõe uma limitação do caminho atual sob teto de RAM; não é
evidência de OCR ausente, arquivo vazio nem benefício do cache.

Para medir o cache com as três rotas ativas, o experimento controlado fixa
`ram_parse_mb=2048` em ambos os braços, sem mudar a política de produção. O
resultado **não** representa a configuração adaptativa padrão neste Desktop.
O sintoma de OCR sob teto baixo fica registrado para investigação/correção
posterior, separada da adoção de modelos novos.

A calibração usa `SEGUNDOCEREBRO_CALIBRACAO` em diretório novo por rodada,
dentro do experimento. O primeiro aquecimento tentou usar o diretório global e
a gravação foi negada pelo ambiente; seu resultado foi descartado. Nem o
histórico do Desktop nem o aquecimento treinam a calibração dos braços medidos.
Mantidos: seis pares, mesmo corpus lógico, encoder, alvo, IC e regra de parada.

## Resultado — experimento controlado encerrado

[Dados completos, hashes, sensores e tempos por etapa](jf-parse-store-20260902.json).
O teste `test_relatorio_publicado_regenera_o_contraste` recalcula o resumo a
partir das observações publicadas, sem repetir a indexação nem carregar modelos.

- Redução média pareada do rebuild: **59,3%**, IC95 **52,3% a 64,3%**.
- Medianas descritivas: **39,06 s** com cache vazio e **14,39 s** preenchido.
  A razão dessas medianas não é a média das reduções pareadas.
- Cache: **0/48** hits frios e **48/48** quentes. Os oito acessos por rodada
  incluem a leitura nativa dos scans antes da fase OCR; `falhas.vazio=2` é
  esse estágio intermediário, não o estado final dos documentos.
- Seis documentos e seis chunks em todas as rodadas; dois documentos por rota.
  Canônico, registro estável, chunks e bytes dos vetores idênticos ao aquecimento.
  Não é promessa de arquivos SQLite/LanceDB fisicamente byte-idênticos.
- CPU, e5-large, FastEmbed 0.8.0, ONNX Runtime 1.18.0, RapidOCR 1.4.4 e
  PyMuPDF 1.28.2. RAM por parser explicitamente fixada conforme pré-checagem.

**Hipótese de ≥80% refutada neste experimento.** O Parse Store continua útil e
não altera o conteúdo, mas não elimina carregamento do encoder, embeddings,
leitura/hash, processos e gravação. Não mexemos no produto para alcançar a meta.

O último braço quente demorou mais que os demais e foi **mantido** na análise.
A máquina não estava isolada de outros aplicativos; temperatura indisponível
no Windows, cache do SO não controlado e política de esforço ao vivo do produto
preservada. O IC descreve estas seis repetições, não todos os documentos nem
todos os regimes de máquina. Nenhum ganho em corpus privado ou ranking é
declarado. O aceite no regime adaptativo padrão permanece inválido pelo sintoma
registrado como `Q15.b`, não como uma meta de desempenho a perseguir indefinidamente.
