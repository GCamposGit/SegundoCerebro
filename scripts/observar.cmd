@echo off
rem Observa as raizes da base e reindexa o que mudou. Processo a parte:
rem fechar esta janela nao desfaz o indice; o indexador CLI continua valendo.
rem
rem O caminho do modulo nao se remenda aqui (F6, 30/08/2026): com o pacote
rem instalado ele e importavel de qualquer diretorio. Falhou com
rem ModuleNotFoundError? Instale o pacote; nao conserte no atalho.
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m segundocerebro.index.watcher %*
) else (
  py -3 -m segundocerebro.index.watcher %*
)
