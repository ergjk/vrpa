@echo off
rem Real-machine soak wrapper for PowerShell 5.1 execution policy.
rem Usage:
rem   scripts\soak_real.bat
rem   scripts\soak_real.bat -Iterations 5 -IntervalSeconds 15
rem   scripts\soak_real.bat -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0soak_real.ps1" %*
exit /b %ERRORLEVEL%
