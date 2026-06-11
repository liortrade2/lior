@echo off
rem TOAI — real-time scoring loop for NinjaTrader (Ctrl+C to stop)
cd /d "%~dp0"
title TOAI Watch Mode
echo ============================================
echo   TOAI Watch Mode - real-time scoring
echo   Reads current_features.csv, writes score.txt
echo   Press Ctrl+C to stop
echo ============================================
python -c "from toai.score import watch; watch()"
echo.
pause
