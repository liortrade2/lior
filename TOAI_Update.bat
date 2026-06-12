@echo off
rem TOAI — pull the latest code from GitHub (one click).
cd /d "%~dp0"
title TOAI Update from GitHub
echo ============================================
echo   TOAI - Pulling latest code from GitHub
echo ============================================
git fetch origin claude/magical-dirac-1yd0d4
git checkout claude/magical-dirac-1yd0d4
git pull origin claude/magical-dirac-1yd0d4
echo.
echo Done. If ninjascript files changed, re-paste them
echo into the NinjaScript Editor and press F5 (Compile).
echo.
pause
