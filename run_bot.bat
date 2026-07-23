@echo off
REM Ejecuta el bot una vez usando el entorno virtual.
REM Esta es la linea que dispara la Tarea Programada 6x/dia.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python rental_alert.py
