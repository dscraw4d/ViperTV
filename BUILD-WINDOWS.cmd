@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 is required only on the build machine.
  echo End users do not need Python installed.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\\Build-Windows-Standalone.ps1"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo Build failed with error %RC%.
if "%RC%"=="0" echo Build complete. See dist-windows.
pause
exit /b %RC%
