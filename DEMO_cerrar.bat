@echo off
title WorkLog - Cerrando demo
echo.
echo  ==========================================
echo   WORKLOG - Cerrando sesion de demo
echo  ==========================================
echo.

echo Cerrando tunel de Cloudflare...
taskkill /IM cloudflared.exe /F >nul 2>&1

echo Cerrando servidor Flask (puerto 5000)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo [OK] Demo finalizada. Todos los procesos cerrados.
echo.
ping -n 4 127.0.0.1 >nul 2>&1
