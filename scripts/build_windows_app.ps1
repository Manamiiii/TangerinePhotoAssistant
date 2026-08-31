param([string]$OutputDirectory = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectRoot ("runtime\packages\windows-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) { throw "Output already exists; choose a new directory. Nothing was overwritten." }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Install the project Python environment first." }
Push-Location (Join-Path $ProjectRoot "web")
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
& $Python -m PyInstaller --noconfirm --distpath (Join-Path $OutputDirectory "dist") `
    --workpath (Join-Path $OutputDirectory "build") (Join-Path $PSScriptRoot "windows_app.spec")
if ($LASTEXITCODE -ne 0) { throw "Windows package build failed." }
$Bundle = Join-Path $OutputDirectory "dist\TangerinePhotoAssistant"
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install_windows_app.ps1") -Destination $Bundle
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install_windows_app.cmd") -Destination (Join-Path $Bundle "Install.cmd")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\WINDOWS_APP.md") -Destination (Join-Path $Bundle "WINDOWS_APP.md")
$Archive = Join-Path $OutputDirectory "TangerinePhotoAssistant-Windows-x64.zip"
Compress-Archive -LiteralPath $Bundle -DestinationPath $Archive -CompressionLevel Optimal
Get-FileHash -LiteralPath $Archive -Algorithm SHA256 | Format-List
Write-Host "Unsigned local package ready: $Archive"
