@echo off
title API Ordenes de Produccion
cd /d "%~dp0"

rem Usa el entorno virtual de la carpeta si existe
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo ===============================
echo  API Ordenes de Produccion
echo  http://localhost:8000/docs
echo ===============================
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
