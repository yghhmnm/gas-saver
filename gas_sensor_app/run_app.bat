@echo off
cd /d "%~dp0"
set "PY=python"
python --version >nul 2>nul || set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
"%PY%" gas_monitor.py
pause
