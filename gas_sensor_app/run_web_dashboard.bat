@echo off
cd /d "%~dp0\web"
echo Starting Gas Saver Web Dashboard on http://localhost:8080 ...
set "PY=python"
python --version >nul 2>nul || set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
"%PY%" server.py
pause
