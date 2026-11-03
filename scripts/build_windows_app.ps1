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
& $Python (Join-Path $PSScriptRoot "package_manifest.py") identity (Join-Path $OutputDirectory "build-info.json")
if ($LASTEXITCODE -ne 0) { throw "Build identity failed." }
$env:TANGERINE_BUILD_INFO = Join-Path $OutputDirectory "build-info.json"
$Notices = Join-Path $OutputDirectory 'ThirdPartyNotices'
& $Python (Join-Path $PSScriptRoot 'package_notices.py') $Notices
if ($LASTEXITCODE -ne 0) { throw 'Third-party notices failed.' }
$env:TANGERINE_NOTICES = $Notices
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
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "manage_windows_app.ps1") -Destination $Bundle
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "windows_package_common.ps1") -Destination $Bundle
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "manage_windows_app.cmd") -Destination (Join-Path $Bundle "Manage.cmd")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'setup_windows_app.ps1') -Destination $Bundle
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'LICENSE') -Destination $Bundle
& $Python (Join-Path $PSScriptRoot "package_manifest.py") manifest $Bundle
if ($LASTEXITCODE -ne 0) { throw "Package manifest failed." }
$Version = (Get-Content $env:TANGERINE_BUILD_INFO -Raw | ConvertFrom-Json).version
if (-not $Version) { $Version = '0.1.0' }
$Archive = Join-Path $OutputDirectory "TangerinePhotoAssistant-$Version-Windows-x64-Portable.zip"
& $Python (Join-Path $PSScriptRoot 'package_zip.py') $Bundle $Archive
if ($LASTEXITCODE -ne 0) { throw 'Portable archive failed.' }
& $Python (Join-Path $PSScriptRoot 'compile_windows_setup.py') --bundle $Bundle --output (Join-Path $OutputDirectory "TangerinePhotoAssistant-$Version-Windows-x64-Setup.exe") --version $Version
if ($LASTEXITCODE -ne 0) { throw 'Setup build failed.' }
$Identity = Get-Content $env:TANGERINE_BUILD_INFO -Raw | ConvertFrom-Json
if (-not $Identity.dirty -and $Identity.revision -ne 'unknown') {
    & git -C $ProjectRoot archive --format=zip "--output=$(Join-Path $OutputDirectory "TangerinePhotoAssistant-$Version-Source.zip")" $Identity.revision
    if ($LASTEXITCODE -ne 0) { throw 'Corresponding source archive failed.' }
} else { Write-Warning 'Dirty checkout: development artifacts only; no corresponding source archive generated.' }
$Artifacts = Get-ChildItem -LiteralPath $OutputDirectory -File | Where-Object { $_.Extension -in @('.exe','.zip') }
$Lines = $Artifacts | ForEach-Object { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $_.Name }
[IO.File]::WriteAllLines((Join-Path $OutputDirectory 'SHA256SUMS.txt'), $Lines)
Write-Host "Unsigned local packages ready: $OutputDirectory"
