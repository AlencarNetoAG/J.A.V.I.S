@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual ausente. Siga a instalacao com Python 3.11 no README.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)"
if errorlevel 1 (
    echo Use Python 3.11 de 64 bits e recrie o ambiente virtual conforme README.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo.
    echo O Jarvis encontrou um erro. Copie a mensagem acima.
    pause
    exit /b 1
)
