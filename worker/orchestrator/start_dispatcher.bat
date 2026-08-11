@echo off
REM Thin launcher for start_dispatcher.ps1 - -ExecutionPolicy Bypass applies
REM only to this one invocation, not a system-wide policy change. Needed
REM because PowerShell's default policy blocks running local .ps1 files
REM directly on a fresh machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dispatcher.ps1" %*
