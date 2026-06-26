@echo off
rem ============================================================================
rem  TOAI Analytics - APP MODE launcher
rem  Opens the dashboard as a chromeless app window (Chrome/Edge --app). The
rem  Streamlit server runs in a MINIMIZED console; CLOSING THE APP WINDOW also
rem  stops the server (and the live watch). Port 8765 + theme come from
rem  .streamlit\config.toml.
rem ============================================================================

if "%~1"=="run" goto run

rem ---- first launch: relaunch MINIMIZED so no big console stays on screen ----
start "" /min cmd /c "%~f0" run
exit /b

:run
cd /d "%~dp0"
title TOAI Analytics (server - closes with the app)

rem ---- locate Chrome (fall back to Edge) ----
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

rem ---- start the server in the background (logs stay in this minimized window) ----
start "" /b python -m streamlit run toai\dashboard.py --server.port 8765 --server.headless true

rem ---- wait until the port answers ----
:waitloop
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('localhost',8765);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto waitloop

rem ---- open the app window and WAIT until it is closed ----
rem  A dedicated --user-data-dir makes Chrome run its own process, so /wait
rem  blocks until THIS window is closed (otherwise it may attach to an existing
rem  Chrome and return immediately).
start "" /wait "%CHROME%" --app=http://localhost:8765 --window-size=1087,625 --disable-extensions --user-data-dir="%LocalAppData%\TOAI_Analytics_profile"

rem ---- app window closed: stop the server (and its children) by the port PID ----
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765 " ^| findstr LISTENING') do taskkill /f /t /pid %%P >nul 2>&1
exit /b
