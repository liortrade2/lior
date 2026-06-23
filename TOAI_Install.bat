@echo off
rem ============================================================================
rem  TOAI Installer — fresh-PC setup. Double-click this.
rem  Runs TOAI_Install.ps1 (Python + deps, optional API key, NinjaScript ->
rem  NinjaTrader, desktop shortcuts, optional restore of C:\LIOR_ML from D).
rem  After it finishes: compile in NinjaTrader (F5), add the indicator to your
rem  chart, and launch "TOAI Analytics" from the desktop.
rem ============================================================================
title TOAI Installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0TOAI_Install.ps1"
