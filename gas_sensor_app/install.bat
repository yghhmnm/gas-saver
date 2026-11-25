@echo off
echo ============================================
echo   Gas Sensor Monitor - Setup
echo ============================================
echo.

echo Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found! Install Python from https://python.org
    pause
    exit /b 1
)

echo.
echo Installing required packages...
pip install pyserial plyer requests

echo.
echo ============================================
echo  Setup complete!
echo  Run the app with:  python gas_monitor.py
echo  Or double-click:   run_app.bat
echo ============================================
pause
