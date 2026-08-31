@echo off
rem Atalho do Segundo Cerebro. Abre o painel no navegador.
rem Se o painel ja estiver no ar, so reabre a aba — nao sobe um segundo processo.
rem
rem A porta NAO se declara aqui (Q12, 29/08/2026): ela vem de
rem painel.app.PORTA_PADRAO, que era o outro lugar onde o numero morava.
rem Para outra porta: passe --porta ao chamar o modulo direto.
rem
rem O caminho do modulo tambem nao se remenda aqui (F6, 30/08/2026): com o
rem pacote instalado ele e importavel de qualquer diretorio, e escrever o
rem caminho do repositorio num script e a mesma classe que o registrador do MCP
rem acabou de perder — codigo que so roda de dentro do repositorio. Se este
rem comando falhar com ModuleNotFoundError, instale o pacote; nao remende aqui.
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m segundocerebro.painel
) else (
  py -3 -m segundocerebro.painel
)
