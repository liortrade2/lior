@echo off
rem TOAI Control Panel - live monitor + variant switcher + auto-train.
rem Replaces TOAI_Watch.bat: it runs the watch loop inside the window.
cd /d "%~dp0"
title TOAI Control Panel
python -c "from toai.control_panel import main; main()"
echo.
echo (window closed)
pause
