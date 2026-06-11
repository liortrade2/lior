@echo off
rem TOAI — opens the control panel (GUI)
cd /d "%~dp0"
python -m toai.gui
if errorlevel 1 (
    echo.
    echo TOAI failed to start. Is Python installed and on PATH?
    pause
)
