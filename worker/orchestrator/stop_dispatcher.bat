@echo off
REM Thin launcher for stop_dispatcher.ps1 - see start_dispatcher.bat for why.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_dispatcher.ps1" %*
