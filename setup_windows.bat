@echo off
REM ============================================================
REM  Setup unico del bot Alerta Alquiler (Windows)
REM  Ejecutalo UNA sola vez, parado en la carpeta del repo.
REM ============================================================
cd /d "%~dp0"

echo.
echo [1/4] Creando entorno virtual...
python -m venv venv
if errorlevel 1 (
    echo ERROR: no se encontro Python. Instalalo desde https://www.python.org/downloads/ y marca "Add Python to PATH".
    pause
    exit /b 1
)

echo.
echo [2/4] Instalando dependencias...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [3/4] Instalando navegador de Playwright (para MercadoLibre)...
playwright install chromium

echo.
echo [4/4] Verificando config.json...
if not exist config.json (
    copy config.json.example config.json
    echo Se creo config.json. EDITALO con tu token y chat_ids antes de correr el bot.
) else (
    echo config.json ya existe. OK.
)

echo.
echo ============================================================
echo  Setup completo. Completa config.json y corre run_bot.bat
echo ============================================================
pause
