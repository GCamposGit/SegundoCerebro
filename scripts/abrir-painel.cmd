@echo off
rem Atalho do Segundo Cerebro. Abre o painel no navegador (porta 18787).
rem Se o painel ja estiver no ar, so reabre a aba — nao sobe um segundo processo.
cd /d "%~dp0\.."
set PYTHONPATH=src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m segundocerebro.painel --porta 18787
) else (
  py -3 -m segundocerebro.painel --porta 18787
)
