@echo off
chcp 65001 >nul
title VICOPU - atualizar
rem Baixa a versao nova do GitHub e instala o que mudou.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo [VICOPU] Nao achei o .venv nesta pasta. Rode a instalacao do README primeiro.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo [VICOPU] Baixando atualizacoes...
git pull
echo [VICOPU] Conferindo bibliotecas...
pip install -q -r requirements.txt
echo.
echo [VICOPU] Pronto! Agora e so abrir o iniciar.bat
pause
