param([string]$InstallRoot = '', [ValidateSet('Status','Activate','Uninstall')][string]$Action = 'Status',
      [string]$Release = '', [switch]$Apply, [switch]$Interactive)
. (Join-Path $PSScriptRoot 'windows_package_common.ps1')
if (-not $InstallRoot) {
    $Parent = Split-Path -Parent $PSScriptRoot
    $InstallRoot = if (Test-Path -LiteralPath (Join-Path $Parent '.tangerine-install.json')) { $Parent }
        else { Join-Path $env:LOCALAPPDATA 'Programs\TangerinePhotoAssistant' }
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$State = Read-Installation $InstallRoot
if ($Interactive) {
    Write-Host "Program directory: $InstallRoot"
    Write-Host "Active: $($State.active)"
    $State.releases | ForEach-Object { Write-Host $_ }
    $Choice = Read-Host '1 = switch/rollback, 2 = uninstall one release, Enter = exit'
    if ($Choice -notin @('1','2')) { return }
    $Action = if ($Choice -eq '1') { 'Activate' } else { 'Uninstall' }
    $Release = Read-Host 'Exact release name'
}
if ($Action -eq 'Status') { $State | ConvertTo-Json -Depth 5; return }
if ($Release -notin $State.releases) { throw 'Release is not managed by this installation.' }
$Directory = Get-ChildPath $InstallRoot $Release
Assert-PlainPath (Join-Path $InstallRoot '.maintenance.lock')
$Lease = [IO.File]::Open((Join-Path $InstallRoot '.maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $State = Read-Installation $InstallRoot
    if ($Release -notin $State.releases) { throw 'Installation changed; try again.' }
    $Package = Read-Package $Directory
    if ($Action -eq 'Activate') {
        [void](Read-Package $Directory -Verify)
        if ($Package.schema_version -lt $State.schema_floor) { throw 'Rollback crosses schema floor; refused. Databases are never downgraded.' }
        Write-Host "Preview: activate $Release. No database changes or service restarts."
    } else {
        $Removable = @()
        foreach ($File in $Package.files) {
            $Target = Get-ChildPath $Directory $File.path
            if ((Test-Path -LiteralPath $Target -PathType Leaf) -and (Get-ProgramHash $Target) -eq $File.sha256) { $Removable += $Target }
            elseif (Test-Path -LiteralPath $Target) { Write-Host "Keep modified file: $($File.path)" }
        }
        Write-Host "Preview: remove $($Removable.Count) unchanged program files from $Directory"
        Write-Host 'Unlisted/modified files, user configuration, photos, databases and caches remain.'
    }
    if ($Interactive) { $Apply = (Read-Host "Type $Release to confirm $Action") -ceq $Release }
    if (-not $Apply) { Write-Host 'Preview only. Use -Apply after reviewing.'; return }
    Assert-NoProgramProcess $InstallRoot
    if ($Action -eq 'Activate') {
        Set-ProgramShortcuts $InstallRoot $State $Release
        $State.active = $Release
        $State.schema_floor = [Math]::Max($State.schema_floor, $Package.schema_version)
    } else {
        if ($State.active -eq $Release) { Set-ProgramShortcuts $InstallRoot $State ''; $State.active = '' }
        foreach ($Target in $Removable) {
            $Relative = $Target.Substring($Directory.Length + 1).Replace('\','/')
            $Safe = Get-ChildPath $Directory $Relative
            $Entry = $Package.files | Where-Object path -eq $Relative
            if ((Get-ProgramHash $Safe) -eq $Entry.sha256) { Remove-Item -LiteralPath $Safe }
        }
        # Retain manifest/directories as a receipt, including unknown user files.
        $State.releases = @($State.releases | Where-Object { $_ -ne $Release })
    }
    Save-Installation $InstallRoot $State
    Write-Host "$Action completed. User data was preserved. No process was stopped."
} finally { $Lease.Dispose() }
