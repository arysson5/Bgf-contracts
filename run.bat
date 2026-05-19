@echo off
title Contract Analyzer
cd /d %~dp0
echo Iniciando Contract Analyzer...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m streamlit run app/main.py --server.headless true --server.port 8501 --server.address 127.0.0.1
) else (
    python -m streamlit run app/main.py --server.headless true --server.port 8501 --server.address 127.0.0.1
)
pause
