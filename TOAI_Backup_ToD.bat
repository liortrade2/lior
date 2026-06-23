@echo off
rem ============================================================================
rem  TOAI Backup -> drive D   (run this BEFORE formatting the PC)
rem  Copies, with a date stamp, into D:\TOAI_Backup_<date>:
rem    1. C:\LIOR_ML  - trading data / models / journals  (NOT in git! critical)
rem    2. C:\lior     - the code repo (incl. .git + any uncommitted work)
rem  Uses robocopy (resumable, retries, multithreaded). Safe to re-run.
rem ============================================================================
setlocal

if not exist "D:\" (
  echo ERROR: drive D: was not found. Plug in / check the drive, then retry.
  pause
  exit /b 1
)

rem ---- date stamp (yyyy-MM-dd_HHmm) via PowerShell (reliable on Win11) ----
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "STAMP=%%I"
set "DEST=D:\TOAI_Backup_%STAMP%"

echo ============================================================
echo  Backing up to:  %DEST%
echo ============================================================
echo.

rem ---- 1) the irreplaceable data (data/models/journals) ----
echo [1/2] C:\LIOR_ML  ->  %DEST%\LIOR_ML
robocopy "C:\LIOR_ML" "%DEST%\LIOR_ML" /E /R:2 /W:2 /MT:16 /NFL /NDL /NP

rem ---- 2) the code (in git too, but keep .git + uncommitted work just in case) ----
echo [2/2] C:\lior     ->  %DEST%\lior
robocopy "C:\lior" "%DEST%\lior" /E /R:2 /W:2 /MT:16 /NFL /NDL /NP /XD __pycache__ node_modules .venv

rem ---- 3) drop the installer + restore guide at the backup ROOT for easy access ----
copy /Y "C:\lior\TOAI_Install.bat" "%DEST%\" >nul 2>&1
copy /Y "C:\lior\TOAI_Install.ps1" "%DEST%\" >nul 2>&1
if exist "C:\LIOR_ML\RESTORE_README.md" copy /Y "C:\LIOR_ML\RESTORE_README.md" "%DEST%\" >nul 2>&1

echo.
echo ============================================================
echo  Backup complete:  %DEST%
echo    - LIOR_ML            (data / models / journals)
echo    - lior               (code + .git)
echo    - TOAI_Install.bat   (run this first on the new PC)
echo    - RESTORE_README.md
echo  Verify the folder opened below, THEN format.
echo ============================================================
explorer "%DEST%"
pause
