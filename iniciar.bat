@echo off
chcp 65001 >nul
title Revisa
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  python -m venv .venv
)

echo Verificando dependencias...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Falha ao instalar as dependencias.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Revisa rodando em http://127.0.0.1:5000  (feche esta janela para parar)
echo.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:5000"
".venv\Scripts\python.exe" app.py
pause
