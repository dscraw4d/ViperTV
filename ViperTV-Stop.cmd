@echo off
cd /d "%~dp0"
if exist "runtime\pythonw.exe" start "" /b "runtime\pythonw.exe" "windows\launcher.pyw" stop
