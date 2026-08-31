@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage_windows_app.ps1" -Interactive
pause
