param(
    [string]$InstallRoot = "",
    [string]$ConfigFile = "",
    [switch]$NoShortcuts
)
$ErrorActionPreference = "Stop"
$Bundle = (Resolve-Path $PSScriptRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $Bundle "TangerinePhotoAssistant.exe") -PathType Leaf)) {
    throw "Run this installer from the extracted application bundle."
}
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\TangerinePhotoAssistant" }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
if ($InstallRoot.Equals($Bundle, [StringComparison]::OrdinalIgnoreCase) -or
    $InstallRoot.StartsWith($Bundle.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallRoot must not be inside the extracted bundle (recursive copy prevented)."
}
if ($ConfigFile) {
    $ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
}
# Versioned directories: never overwrite the executable of a running service.
$ReleaseName = "release-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$Release = Join-Path $InstallRoot $ReleaseName
if (Test-Path -LiteralPath $Release) { throw "This release directory already exists; no files were changed." }
New-Item -ItemType Directory -Path $Release -Force | Out-Null
Get-ChildItem -LiteralPath $Bundle -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Release -Recurse
}
$Executable = Join-Path $Release "TangerinePhotoAssistant.exe"
if (-not $NoShortcuts) {
    $Shell = New-Object -ComObject WScript.Shell
    $Programs = Join-Path ([Environment]::GetFolderPath("Programs")) "TangerinePhotoAssistant"
    New-Item -ItemType Directory -Path $Programs -Force | Out-Null
    foreach ($ShortcutPath in @(
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "TangerinePhotoAssistant.lnk"),
        (Join-Path $Programs "TangerinePhotoAssistant.lnk")
    )) {
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $Executable
        $Shortcut.WorkingDirectory = $Release
        $Shortcut.Arguments = if ($ConfigFile) { "--config `"$ConfigFile`"" } else { "" }
        $Shortcut.IconLocation = "$Executable,0"
        $Shortcut.Save()
    }
}
Write-Host "Installed application files: $Release"
Write-Host "Existing config, databases, caches and photos were not changed. No service was stopped."
