@echo off
rem ============================================================================
rem  TOAI Analytics - APP MODE launcher
rem  Opens the dashboard as a chromeless desktop "app" window (Chrome --app),
rem  and keeps the Streamlit server in a MINIMIZED console window.
rem  Close that minimized window (or the app window's server) to stop it.
rem  Port 8765 + light theme come from .streamlit\config.toml.
rem ============================================================================

rem ---- argument dispatch ----
if "%~1"=="open" goto opener
if "%~1"=="run"  goto server

rem ---- first launch: relaunch MINIMIZED so no big console stays on screen ----
start "" /min cmd /c "%~f0" run
exit /b

rem ---- minimized window: spawn the app-opener, then host the server here ----
:server
cd /d "%~dp0"
title TOAI Analytics (server - you can minimize/leave this)
start "" /min cmd /c "%~f0" open
rem If a server is already running on 8765, just open the app window (no 2nd server).
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('localhost',8765);exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 exit /b
python -m streamlit run toai\dashboard.py --server.port 8765 --server.headless true
exit /b

rem ---- opener: wait for the port, then open the chromeless app window ----
:opener
set "URL=http://localhost:8765"
:waitloop
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('localhost',8765);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto waitloop

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
  start "" "%CHROME%" --app=%URL% --window-size=1071,589
) else (
  start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=%URL% --window-size=1071,589
)
exit /b
