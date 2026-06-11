@echo off
rem TOAI — build training file from the real backtest export and train.
rem Expects: C:\LIOR_ML\trades_export.csv (Strategy Analyzer export)
rem          C:\LIOR_ML\bar_data.csv      (TOAIExporter, ExportBarData=true)
cd /d "%~dp0"
title TOAI Train on Real Data
python -m toai.build_and_train
echo.
pause
