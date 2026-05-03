@echo off
setlocal
cd /d %~dp0
if exist ".venv\Scripts\activate" call .venv\Scripts\activate
set APP_DEBUG=1
set LOG_LEVEL=DEBUG
python app.py
pause
