param([string]$InstallRoot = '', [string]$ConfigFile = '', [switch]$NoShortcuts)
. (Join-Path $PSScriptRoot 'windows_package_common.ps1')
$Bundle = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$Package = Read-Package $Bundle -Verify
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\TangerinePhotoAssistant' }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
Assert-PlainPath $InstallRoot
if ($InstallRoot -eq $Bundle -or $InstallRoot.StartsWith($Bundle + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'InstallRoot cannot be inside the bundle.' }
if ($ConfigFile) {
    $ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
    if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf) -or $ConfigFile.StartsWith($InstallRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'User configuration must remain outside the program installation.' }
}
if ((Test-Path -LiteralPath $InstallRoot) -and -not (Test-Path -LiteralPath (Join-Path $InstallRoot '.tangerine-install.json')) -and @(Get-ChildItem -LiteralPath $InstallRoot -Force).Count) { throw 'Directory contains unmanaged/legacy files. Choose a new empty program directory.' }
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Assert-PlainPath (Join-Path $InstallRoot '.maintenance.lock')
$Lease = [IO.File]::Open((Join-Path $InstallRoot '.maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (Test-Path -LiteralPath (Join-Path $InstallRoot '.tangerine-install.json')) {
        $State = Read-Installation $InstallRoot
        if ($ConfigFile -and $ConfigFile -ne $State.config) { throw 'Upgrade must preserve the configuration; edit directories in application settings.' }
        if ($Package.schema_version -lt $State.schema_floor) { throw 'Package is older than the schema floor; database downgrade is not supported.' }
    } else {
        $State = [pscustomobject]@{app_id='tangerine-photo-assistant'; format=1; active=''; releases=@(); config=$ConfigFile; schema_floor=$Package.schema_version; shortcuts=(-not $NoShortcuts)}
    }
    if ($NoShortcuts) { $State.shortcuts = $false }
    Save-Installation $InstallRoot $State
    $Name = 'release-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $Release = Get-ChildPath $InstallRoot $Name
    New-Item -ItemType Directory -Path $Release | Out-Null
    foreach ($File in $Package.files) {
        $Source = Get-ChildPath $Bundle $File.path
        $Target = Get-ChildPath $Release $File.path
        New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Target
    }
    Copy-Item -LiteralPath (Join-Path $Bundle 'package-manifest.json') -Destination $Release
    [void](Read-Package $Release -Verify)
    $State.releases = @($State.releases) + @($Name)
    Save-Installation $InstallRoot $State
    Set-ProgramShortcuts $InstallRoot $State $Name
    $State.active = $Name
    $State.schema_floor = [Math]::Max($State.schema_floor, $Package.schema_version)
    Save-Installation $InstallRoot $State
    Write-Host "Installed: $Release"
    Write-Host 'Existing processes were not changed. Close/restart normally to use this version.'
    Write-Host 'Configuration, database, cache, photos and old program versions were preserved.'
} finally { $Lease.Dispose() }
