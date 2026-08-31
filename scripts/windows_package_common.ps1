$ErrorActionPreference = 'Stop'
function Get-ProgramHash([string]$Path) {
    $Stream = [IO.File]::OpenRead($Path)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($Hasher.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose(); $Stream.Dispose() }
}
function Assert-PlainPath([string]$Path) {
    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            if ((Get-Item -LiteralPath $Current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Filesystem links are not allowed in managed program paths.'
            }
        }
        $Current = Split-Path -Parent $Current
    }
}
function Get-ChildPath([string]$Root, [string]$Relative) {
    if (-not $Relative -or $Relative -match '(^/|\\|:|(^|/)\.\.?(/|$))') { throw 'Invalid manifest path.' }
    $Result = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    if (-not $Result.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escapes program directory.' }
    Assert-PlainPath $Result
    return $Result
}
function Read-Package([string]$Directory, [switch]$Verify) {
    Assert-PlainPath $Directory
    $Manifest = Join-Path $Directory 'package-manifest.json'
    Assert-PlainPath $Manifest
    if ((Get-Item -LiteralPath $Manifest).Length -gt 4194304) { throw 'Package manifest too large.' }
    $Data = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Data.app_id -ne 'tangerine-photo-assistant' -or $Data.format -ne 1 -or
        ($Data.schema_version -isnot [int] -and $Data.schema_version -isnot [long]) -or $Data.schema_version -lt 1 -or @($Data.files).Count -eq 0) { throw 'Not a supported package manifest.' }
    $Seen = @{}
    foreach ($File in $Data.files) {
        $Target = Get-ChildPath $Directory $File.path
        if ($Seen.ContainsKey($File.path) -or $File.path -eq 'package-manifest.json' -or $File.sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid or duplicate package entry.' }
        $Seen[$File.path] = $true
        if ($Verify -and ((-not (Test-Path -LiteralPath $Target -PathType Leaf)) -or
            (Get-ProgramHash $Target) -ne $File.sha256)) { throw "Package checksum mismatch: $($File.path)" }
    }
    if (-not $Seen.ContainsKey('TangerinePhotoAssistant.exe')) { throw 'Missing executable entry.' }
    return $Data
}
function Read-Installation([string]$Root) {
    Assert-PlainPath $Root
    Assert-PlainPath (Join-Path $Root '.tangerine-install.json')
    $State = Get-Content -LiteralPath (Join-Path $Root '.tangerine-install.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($State.app_id -ne 'tangerine-photo-assistant' -or $State.format -ne 1 -or
        ($State.schema_floor -isnot [int] -and $State.schema_floor -isnot [long])) { throw 'Unrecognized installation; nothing changed.' }
    foreach ($Name in $State.releases) {
        if ($Name -notmatch '^release-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$') { throw 'Invalid release identity.' }
        [void](Get-ChildPath $Root $Name)
    }
    if ($State.active -and $State.active -notin $State.releases) { throw 'Invalid active release.' }
    return $State
}
function Save-Installation([string]$Root, $State) {
    $Path = Join-Path $Root '.tangerine-install.json'
    Assert-PlainPath $Path
    $Temporary = Join-Path $Root ('.state-' + [guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($Temporary, ($State | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($Temporary, $Path, [NullString]::Value) }
    else { [IO.File]::Move($Temporary, $Path) }
}
function Assert-NoProgramProcess([string]$Root) {
    foreach ($Process in (Get-CimInstance Win32_Process -ErrorAction Stop)) {
        if ($Process.ExecutablePath -and $Process.ExecutablePath.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'A managed program is running. Save edits, safely stop its idle service, and close its windows first.'
        }
        if ($Process.Name -eq 'TangerinePhotoAssistant.exe' -and -not $Process.ExecutablePath) { throw 'Cannot establish process ownership; no files changed.' }
    }
}
function Set-ProgramShortcuts([string]$Root, $State, [string]$Release) {
    if (-not $State.shortcuts) { return }
    $Shell = New-Object -ComObject WScript.Shell
    $Paths = @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'TangerinePhotoAssistant.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'TangerinePhotoAssistant\TangerinePhotoAssistant.lnk'))
    foreach ($Path in $Paths) {
        Assert-PlainPath $Path
        if (Test-Path -LiteralPath $Path) {
            $Old = $Shell.CreateShortcut($Path).TargetPath
            $Owned = @($State.releases | ForEach-Object { Join-Path (Join-Path $Root $_) 'TangerinePhotoAssistant.exe' })
            if ($Old -notin $Owned) { throw 'Shortcut belongs to another installation; use -NoShortcuts or preserve it manually.' }
        }
    }
    foreach ($Path in $Paths) {
        if (-not $Release) { if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path }; continue }
        New-Item -ItemType Directory -Path (Split-Path $Path -Parent) -Force | Out-Null
        $Shortcut = $Shell.CreateShortcut($Path)
        $Shortcut.TargetPath = Join-Path (Join-Path $Root $Release) 'TangerinePhotoAssistant.exe'
        $Shortcut.WorkingDirectory = Join-Path $Root $Release
        $Shortcut.Arguments = if ($State.config) { '--config "' + $State.config + '"' } else { '' }
        $Shortcut.IconLocation = $Shortcut.TargetPath + ',0'
        $Shortcut.Save()
    }
}
