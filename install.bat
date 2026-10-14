@echo off
title Chess Coach - Setup
cd /d "%~dp0"
python --version >nul 2>&1 || (echo Python 3.10 or newer is required: https://www.python.org/downloads/ & pause & exit /b 1)
echo Installing Python packages ...
python -m pip install -r requirements.txt || goto :error
echo.
echo Downloading the Stockfish chess engine ...
python setup_engine.py || goto :error
echo.
echo Done! Start the coach with "Chess Coach.bat".
pause
exit /b 0
:error
echo.
echo Setup failed - see the message above.
pause
exit /b 1
