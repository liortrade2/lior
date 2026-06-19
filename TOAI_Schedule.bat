@echo off
rem ============================================================
rem  Register the TOAI start/end-of-day routines in Windows Task
rem  Scheduler (Mon-Fri). EDIT the two times below to YOUR machine's
rem  local timezone: ~15 min BEFORE the session open and ~15 min AFTER
rem  the close. Re-run after editing to update; see remove commands below.
rem ============================================================
cd /d "%~dp0"
set "START_TIME=09:15"
set "END_TIME=16:15"

schtasks /Create /TN "TOAI Start Day" /TR "\"%~dp0TOAI_StartDay.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST %START_TIME% /F
schtasks /Create /TN "TOAI End Day"   /TR "\"%~dp0TOAI_EndDay.bat\""   /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST %END_TIME% /F

echo.
echo Registered. To change times, edit START_TIME/END_TIME above and re-run.
echo To remove:
echo   schtasks /Delete /TN "TOAI Start Day" /F
echo   schtasks /Delete /TN "TOAI End Day" /F
pause
