@echo off
rem Observa as raizes da base e reindexa o que mudou. Processo a parte:
rem fechar esta janela nao desfaz o indice; o indexador CLI continua valendo.
cd /d "%~dp0\.."
set PYTHONPATH=src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m segundocerebro.index.watcher %*
) else (
  py -3 -m segundocerebro.index.watcher %*
)
