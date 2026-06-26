@echo off
setlocal
title WorkLog - Servidor Demo
cd /d %~dp0

echo.
echo  ==========================================
echo   WORKLOG - Levantando servidor para demo
echo  ==========================================
echo.

REM Verificar entorno virtual
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No se encontro el entorno virtual.
    echo         Ejecuta primero: instalar_empresa.bat
    exit /b 1
)

REM Matar cualquier proceso python previo en el puerto 5000
echo Liberando puerto 5000 si estaba ocupado...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
ping -n 3 127.0.0.1 >nul 2>&1

set HOST=127.0.0.1
set PORT=5000
set APP_DEBUG=0
set LOG_LEVEL=INFO

echo [1/2] Iniciando servidor Flask en http://127.0.0.1:5000 ...
echo.

REM Iniciar servidor en ventana separada minimizada
start "WorkLog Servidor" /min .venv\Scripts\python.exe run_waitress.py

REM Esperar 15 segundos — el servidor inicializa DB + scheduler
echo Esperando que el servidor termine de iniciar...
ping -n 16 127.0.0.1 >nul 2>&1

REM Verificar que este corriendo
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if errorlevel 1 (
    REM Esperar 10 segundos mas por si tarda mas de lo normal
    echo Esperando un poco mas...
    ping -n 11 127.0.0.1 >nul 2>&1
    netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
    if errorlevel 1 (
        echo.
        echo [ERROR] El servidor no pudo arrancar. Revisa logs\app.log
        echo.
        exit /b 1
    )
)

echo [OK] Servidor corriendo en http://127.0.0.1:5000
echo.
echo [2/2] Abriendo tunel Cloudflare...
echo       La URL publica aparecera abajo en unos segundos.
echo       Compartela con el cliente para acceso remoto.
echo.
echo  IMPORTANTE: Mientras esta ventana este abierta, el tunel funciona.
echo  Cierra esta ventana cuando termines la demo.
echo.
echo ---------------------------------------------------------------

cloudflared tunnel --url http://localhost:5000

echo.
echo [INFO] Tunel cerrado.
