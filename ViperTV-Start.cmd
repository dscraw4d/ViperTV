@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\pythonw.exe" (
  echo This is the source package. Build or download the Windows Standalone release first.
  pause
  exit /b 1
)
start "" /b "runtime\pythonw.exe" "windows\launcher.pyw" start
exit /b 0
