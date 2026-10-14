@echo off
rem Chess Coach as a desktop app (own window, no console)
cd /d "%~dp0"
start "" pythonw "%~dp0app.py"
