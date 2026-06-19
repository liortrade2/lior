@echo off
rem TOAI PLAYBACK Control Panel — isolated data root for Market Replay testing.
rem Uses C:\LIOR_ML_PLAYBACK instead of C:\LIOR_ML, so replay never touches live
rem data. On the replay chart set the v4 indicators' PlaybackMode = true; the
rem execution logger routes the Playback101 account here automatically.
cd /d "%~dp0"
title TOAI PLAYBACK Control Panel
set "TOAI_DATA_DIR=C:\LIOR_ML_PLAYBACK"
rem Seed the playback root with the live models (refreshes each launch).
python -m toai.playback
python -c "from toai.control_panel import main; main()"
echo.
echo (window closed)
pause
