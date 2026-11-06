@echo off
REM ===========================================================================
REM VRPA-WeChat-Agent quality gate wrapper (M0-F-01)
REM Why: Windows PowerShell may block unsigned .ps1 scripts. This wrapper runs
REM      powershell with -ExecutionPolicy Bypass, so no manual policy change is
REM      needed and no signing is required.
REM Usage: scripts\quality.bat
REM        scripts\quality.bat -Fix
REM        scripts\quality.bat -NoCoverage
REM This script performs NO Git operations.
REM ===========================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0quality.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%