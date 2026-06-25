@echo off
setlocal
cd /d %~dp0

echo ============================================
echo  DEMO - Servidor WorkLog
echo ============================================
echo.

REM Activar entorno virtual
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ERROR] No se encontro el entorno virtual en .venv
    pause
    exit /b 1
)

REM Configuracion para demo
set HOST=127.0.0.1
set PORT=5000
set APP_DEBUG=0
set LOG_LEVEL=INFO

echo [OK] Entorno virtual activado
echo [OK] Servidor arrancando en http://127.0.0.1:5000
echo.
echo Deja esta ventana abierta. Abre otra consola y
echo ejecuta: cloudflared tunnel --url http://localhost:5000
echo.

python run_waitress.py

pause
