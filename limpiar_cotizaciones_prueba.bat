@echo off
cd /d %~dp0
python scripts\final_preflight.py --reset-public-quotes
pause
