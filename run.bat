@echo off
title Contract Analyzer
cd /d %~dp0
set PYTHONPATH=%~dp0
echo Iniciando Contract Analyzer...
if exist ".venv\Scripts\python.exe" (
    echo Verificando Visual C++ e ambiente Python...
    .venv\Scripts\python.exe scripts\check_runtime.py
    if errorlevel 1 (
        echo.
        echo Corrija o ambiente acima e execute run.bat novamente.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m streamlit run app/main.py --server.headless true --server.port 8501 --server.address 127.0.0.1
) else (
    python -m streamlit run app/main.py --server.headless true --server.port 8501 --server.address 127.0.0.1
)
pause
