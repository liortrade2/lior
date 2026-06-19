@echo off
rem ============================================================
rem  TOAI END OF DAY (scheduled or double-click)
rem    1) save the Edgewonk journal files (per instrument, per day)
rem    2) close NinjaTrader (graceful)
rem  Register in Windows Task Scheduler to run ~15 min after the close.
rem  Graceful close: if NinjaTrader prompts, it waits — make sure you are
rem  FLAT and NT is set to close without a dialog for fully unattended use.
rem ============================================================
cd /d "%~dp0"
title TOAI End Day
python -m toai.routines end
