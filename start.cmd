@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" "%~dp0launcher.py" start %*
if errorlevel 1 (
  echo.
  echo Please see the logs in .state or read README-FIRST.txt.
  pause
  exit /b 1
)
