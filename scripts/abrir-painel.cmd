@echo off
rem Atalho do Segundo Cerebro. Abre o painel no navegador.
rem Se o painel ja estiver no ar, so reabre a aba — nao sobe um segundo processo.
rem
rem A porta NAO se declara aqui (Q12, 29/08/2026): ela vem de
rem painel.app.PORTA_PADRAO, que era o segundo lugar onde o numero estava
rem escrito. Para outra porta: passe --porta ao chamar o modulo direto.
cd /d "%~dp0\.."
set PYTHONPATH=src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m segundocerebro.painel
) else (
  py -3 -m segundocerebro.painel
)
