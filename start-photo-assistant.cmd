@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\tangerine-photo.exe" (
  echo TangerinePhotoAssistant has not been installed yet.
  pause
  exit /b 1
)

if not exist "web\dist\index.html" (
  echo The local web interface has not been built yet.
  pause
  exit /b 1
)

set "CONFIG_FILE=config.toml"
if not exist "%CONFIG_FILE%" set "CONFIG_FILE=config.example.toml"

powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/health; if ($response.StatusCode -eq 200) { exit 0 } } catch { exit 1 }; exit 1" >nul 2>nul
if %errorlevel% equ 0 (
  start "" http://127.0.0.1:8765
  exit /b 0
)

echo Starting TangerinePhotoAssistant...
powershell.exe -NoProfile -Command "$exe=(Resolve-Path '.venv\Scripts\tangerine-photo.exe').Path; $config=(Resolve-Path '%CONFIG_FILE%').Path; Start-Process -WindowStyle Hidden -FilePath $exe -ArgumentList @('serve','--config',$config,'--host','127.0.0.1','--port','8765'); for ($attempt=0; $attempt -lt 30; $attempt++) { Start-Sleep -Seconds 1; try { $response=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/health; if ($response.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8765'; exit 0 } } catch {} }; exit 1"
if %errorlevel% neq 0 (
  echo The service did not become ready within 30 seconds.
  pause
  exit /b 1
)
