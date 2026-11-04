param(
    [ValidateSet('Install','Uninstall')][string]$Action,
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$ProductName = 'TangerinePhotoAssistant',
    [string]$ProductKey = '{551A03F7-2773-4A5E-962C-6BBDB8B28E08}',
    [string]$DisplayVersion = '0.1.0'
)
. (Join-Path $PSScriptRoot 'windows_package_common.ps1')
if ($ProductName -notmatch '^TangerinePhotoAssistant(?:Fixture-[a-zA-Z0-9-]+)?$' -or $ProductKey -notmatch '^\{[A-Fa-f0-9-]{36}\}$') { throw 'Invalid product identity.' }
if ($DisplayVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid version.' }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
Assert-ProductDirectory $InstallRoot
if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot).TrimEnd('\')) { throw 'Cannot install at a volume root.' }
$Registry = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$ProductKey"
Assert-PlainPath (Join-Path $InstallRoot 'Uninstall.exe')
if ((Test-Path -LiteralPath (Join-Path $InstallRoot 'Uninstall.exe')) -and -not (Test-Path -LiteralPath $Registry)) { throw 'An unowned uninstaller already exists. Choose a different directory.' }
$Programs = [Environment]::GetFolderPath('Programs')
$Shortcut = Join-Path $Programs "$ProductName\$ProductName.lnk"
Assert-PlainPath $Shortcut
$Shell = New-Object -ComObject WScript.Shell
$Previous = $null
if (Test-Path -LiteralPath $Shortcut) {
    $Previous = $Shell.CreateShortcut($Shortcut)
    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot '.tangerine-install.json'))) { throw 'Start Menu shortcut belongs to another installation.' }
    $Before = Read-Installation $InstallRoot
    $Owned = @($Before.releases | ForEach-Object { Get-ChildPath $InstallRoot ($_ + '/TangerinePhotoAssistant.exe') })
    if ($Previous.TargetPath -notin $Owned) { throw 'Start Menu shortcut target is not a registered program.' }
}
if (Test-Path -LiteralPath $Registry) {
    $Registration = Get-ItemProperty -LiteralPath $Registry
    if ($Registration.InstallLocation -ne $InstallRoot -or $Registration.TangerineProduct -ne $ProductName) { throw 'This installation identity belongs to another directory.' }
    [void](Read-Installation $InstallRoot)
    if ($Action -eq 'Install' -and [version]$DisplayVersion -lt [version]$Registration.DisplayVersion) { throw 'Installing an older Setup version is not supported.' }
}
Assert-NoProgramProcess $InstallRoot
if ($Action -eq 'Install') {
    & (Join-Path $PSScriptRoot 'install_windows_app.ps1') -InstallRoot $InstallRoot -NoShortcuts
    $State = Read-Installation $InstallRoot
    $Executable = Get-ChildPath $InstallRoot ($State.active + '/TangerinePhotoAssistant.exe')
    New-Item -ItemType Directory -Path (Split-Path $Shortcut -Parent) -Force | Out-Null
    $Link = $Shell.CreateShortcut($Shortcut)
    $Link.TargetPath = $Executable
    $Link.WorkingDirectory = if ($Previous -and $Previous.WorkingDirectory -ne (Split-Path -Parent $Previous.TargetPath)) {
        $Previous.WorkingDirectory
    } else { Split-Path -Parent $Executable }
    $Link.Arguments = if ($Previous) { $Previous.Arguments } elseif ($State.config) { '--config "' + $State.config + '"' } else { '' }
    $Link.IconLocation = "$Executable,0"
    $Link.Save()
    New-Item -Path $Registry -Force | Out-Null
    foreach ($Entry in @{
        DisplayName=$ProductName; DisplayVersion=$DisplayVersion; Publisher='Manamiiii';
        InstallLocation=$InstallRoot; DisplayIcon="$Executable,0"; TangerineProduct=$ProductName;
        URLInfoAbout='https://github.com/Manamiiii/TangerinePhotoAssistant'
    }.GetEnumerator()) { New-ItemProperty -LiteralPath $Registry -Name $Entry.Key -Value $Entry.Value -PropertyType String -Force | Out-Null }
    foreach ($Name in @('NoModify','NoRepair')) { New-ItemProperty -LiteralPath $Registry -Name $Name -Value 1 -PropertyType DWord -Force | Out-Null }
} else {
    if (-not (Test-Path -LiteralPath $Registry)) { throw 'No owned installation registration; nothing changed.' }
    $State = Read-Installation $InstallRoot
    foreach ($Release in @($State.releases)) {
        & (Join-Path $PSScriptRoot 'manage_windows_app.ps1') -InstallRoot $InstallRoot -Action Uninstall -Release $Release -Apply
    }
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut }
    Remove-Item -LiteralPath $Registry
}
Write-Host "$Action succeeded. Personal configuration, database, photos and backups were preserved."
