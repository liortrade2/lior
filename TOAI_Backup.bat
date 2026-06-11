@echo off
rem TOAI — one-click backup of everything that is NOT on GitHub:
rem   1. C:\LIOR_ML            (trading data + trained model)
rem   2. NinjaTrader 8 templates (BlackBird/BloodHound)
rem   3. The project folder     (extra safety, without .git/data)
rem
rem Usage:
rem   TOAI_Backup.bat          -> backs up to C:\TOAI_Backups
rem   TOAI_Backup.bat E:       -> backs up to E:\TOAI_Backups (external drive)

setlocal
title TOAI Backup

set "TARGET_DRIVE=%~1"
if "%TARGET_DRIVE%"=="" set "TARGET_DRIVE=C:"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "TS=%%i"
set "DEST=%TARGET_DRIVE%\TOAI_Backups\%TS%"

echo ============================================
echo   TOAI Backup
echo   Destination: %DEST%
echo ============================================
echo.

rem --- 1. Trading data + model ---
if exist "C:\LIOR_ML" (
    echo [1/3] Backing up C:\LIOR_ML ...
    robocopy "C:\LIOR_ML" "%DEST%\LIOR_ML" /E /NFL /NDL /NJH /NP >nul
    echo       done.
) else (
    echo [1/3] C:\LIOR_ML not found - skipped.
)

rem --- 2. NinjaTrader templates ---
if exist "%USERPROFILE%\Documents\NinjaTrader 8\templates" (
    echo [2/3] Backing up NinjaTrader 8 templates ...
    robocopy "%USERPROFILE%\Documents\NinjaTrader 8\templates" "%DEST%\NinjaTrader_templates" /E /NFL /NDL /NJH /NP >nul
    echo       done.
) else (
    echo [2/3] NinjaTrader 8 templates not found - skipped.
)

rem --- 3. Project folder (without .git, data, caches) ---
echo [3/3] Backing up project folder ...
robocopy "%~dp0." "%DEST%\lior_project" /E /XD .git data __pycache__ /NFL /NDL /NJH /NP >nul
echo       done.

echo.
echo ============================================
echo   Backup complete: %DEST%
echo ============================================
start "" explorer "%DEST%"
pause
