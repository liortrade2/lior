@echo off
rem ============================================================================
rem  TOAI Cockpit — ONE screen, ONE button.
rem  Opens toai\cockpit.py as a chromeless app window (Chrome/Edge --app). The
rem  Streamlit server runs MINIMIZED; closing the app window stops the server.
rem  This is the new front door. The full multi-tab dashboard is still
rem  TOAI_Analytics_App.bat.
rem ============================================================================

if "%~1"=="run" goto run

rem ---- first launch: relaunch MINIMIZED so no big console stays on screen ----
start "" /min cmd /c "%~f0" run
exit /b

:run
cd /d "%~dp0"
title TOAI Cockpit (server - closes with the app)

rem ---- locate Chrome (fall back to Edge) ----
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

rem ---- start the server in the background (port 8766 — distinct from the dashboard's 8765) ----
start "" /b python -m streamlit run toai\cockpit.py --server.port 8766 --server.headless true

rem ---- wait until the port answers ----
:waitloop
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('localhost',8766);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto waitloop

rem ---- open the app window and WAIT until it is closed ----
start "" /wait "%CHROME%" --app=http://localhost:8766 --window-size=1087,625 --disable-extensions --user-data-dir="%LocalAppData%\TOAI_Cockpit_profile"

rem ---- app window closed: stop the server (and its children) by the port PID ----
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8766 " ^| findstr LISTENING') do taskkill /f /t /pid %%P >nul 2>&1
exit /b
