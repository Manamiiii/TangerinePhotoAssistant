@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\windows_launcher.ps1" -Mode Start -Console
if errorlevel 1 pause
