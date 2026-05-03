@echo off
setlocal
cd /d %~dp0
if not exist "backups" mkdir backups
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%I
set DEST=backups\backup_%TS%.zip
powershell -NoProfile -Command "Compress-Archive -Path 'data','uploads','.env' -DestinationPath '%DEST%' -Force"
echo Respaldo creado en %DEST%
pause
