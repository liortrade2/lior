@echo off
rem TOAI — opens the Control Panel (GUI). Same as TOAI_Control.bat: the full
rem panel with live scorecard, variant switching, multi-TF and portfolio.
rem (The old single-shot panel toai.gui is kept in the code but no longer
rem launched — it predates the watch-in-window flow.)
cd /d "%~dp0"
python -m toai.control_panel
if errorlevel 1 (
    echo.
    echo TOAI failed to start. Is Python installed and on PATH?
    pause
)
