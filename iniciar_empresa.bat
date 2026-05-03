@echo off
setlocal
cd /d %~dp0
if exist ".venv\Scripts\activate" call .venv\Scripts\activate
if not exist ".env" copy /Y ".env.example" ".env" >nul
set APP_DEBUG=0
set LOG_LEVEL=INFO
python run_waitress.py
pause
