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

REM Matar cualquier instancia previa en el puerto 5000
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

set HOST=127.0.0.1
set PORT=5000
set APP_DEBUG=0
set LOG_LEVEL=INFO

echo [1/2] Iniciando servidor Flask en http://127.0.0.1:5000 ...
echo       (Esta ventana debe quedar abierta)
echo.

REM Iniciar servidor en ventana separada minimizada
start "WorkLog Servidor" /min .venv\Scripts\python.exe run_waitress.py

REM Esperar a que levante usando ping (compatible con todos los entornos)
echo Esperando que el servidor termine de iniciar (10s)...
ping -n 11 127.0.0.1 >nul 2>&1

REM Verificar que este corriendo
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo.
    echo [ERROR] El servidor no pudo arrancar en el puerto 5000.
    echo         Revisa si hay algun error en los logs:
    echo         %~dp0logs\app.log
    echo.
    exit /b 1
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
