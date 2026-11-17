@echo off
chcp 65001 >nul
title VICOPU
rem Liga o VICOPU com dois cliques: entra na pasta do projeto, ativa o .venv certo e roda.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo [VICOPU] Nao achei o .venv nesta pasta. Rode a instalacao do README primeiro.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo [VICOPU] Ligando... o painel abre no navegador em alguns segundos.
echo [VICOPU] Pra desligar: Ctrl+C nesta janela.
start "" /b cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8787"
python -m vicopu rodar
echo.
echo [VICOPU] Desligado.
pause
