@echo off
rem ============================================================
rem  TOAI START OF DAY (scheduled or double-click)
rem    1) open the Control Panel   2) clear NinjaTrader cache
rem    3) launch NinjaTrader
rem  Register in Windows Task Scheduler to run ~15 min before the open.
rem  NinjaTrader must be CLOSED when this runs (so the cache clears fully).
rem ============================================================
cd /d "%~dp0"
title TOAI Start Day
rem 1) Control Panel in its own window (non-blocking)
start "TOAI Control Panel" python -c "from toai.control_panel import main; main()"
rem 2) clear NT cache + 3) launch NinjaTrader
python -m toai.routines start
