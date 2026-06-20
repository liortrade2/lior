@echo off
rem TOAI Analytics - local, ML-aware trading dashboard (opens in your browser).
rem Reads the same executions/journal/bar data the rest of TOAI writes; nothing
rem leaves this machine. For PLAYBACK data, launch via TOAI_Playback.bat first so
rem TOAI_DATA_DIR points at C:\LIOR_ML_PLAYBACK, then run this.
cd /d "%~dp0"
title TOAI Analytics
python -m streamlit run toai\dashboard.py
echo.
echo (window closed)
pause
