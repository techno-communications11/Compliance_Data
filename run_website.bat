@echo off
REM ============================================================
REM  Techno Communications - Compliance Data website launcher
REM ============================================================
cd /d "%~dp0"

echo Installing/updating required packages...
pip install -r requirements.txt

echo.
echo Starting the website...
echo Open this in your browser:  http://127.0.0.1:5000
echo (Press Ctrl+C in this window to stop.)
echo.
python web_app.py

pause
