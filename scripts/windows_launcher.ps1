param(
    [ValidateSet("Start", "Status", "Validate", "Install", "Remove")]
    [string]$Mode = "Start",
    [int]$Port = 8765,
    [switch]$Console,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppUrl = "http://127.0.0.1:$Port"
$Executable = Join-Path $ProjectRoot ".venv\Scripts\tangerine-photo.exe"
$ConfigFile = Join-Path $ProjectRoot "config.toml"
$WebIndex = Join-Path $ProjectRoot "web\dist\index.html"
$SilentEntry = Join-Path $ProjectRoot "TangerinePhotoAssistant.vbs"
$IconFile = Join-Path $ProjectRoot "assets\tangerine-photo-assistant.ico"
$RuntimeRoot = Join-Path $ProjectRoot "runtime\launcher"
$PidFile = Join-Path $RuntimeRoot "server.pid"

function Show-LauncherMessage([string]$Message, [bool]$IsError = $false) {
    if ($Console) {
        if ($IsError) { [Console]::Error.WriteLine($Message) } else { Write-Host $Message }
        return
    }
    $icon = if ($IsError) { 16 } else { 64 }
    $shell = New-Object -ComObject WScript.Shell
    [void]$shell.Popup($Message, 0, "TangerinePhotoAssistant", $icon)
}

function Assert-LauncherFiles {
    $missing = @()
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        $missing += "Python environment (.venv)"
    }
    if (-not (Test-Path -LiteralPath $WebIndex -PathType Leaf)) {
        $missing += "built web interface (web/dist)"
    }
    if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
        $missing += "local configuration (config.toml)"
    }
    if (-not (Test-Path -LiteralPath $IconFile -PathType Leaf)) {
        $missing += "application icon (assets\tangerine-photo-assistant.ico)"
    }
    if ($missing.Count) {
        throw "The application is not ready: $($missing -join ', '). Complete the one-time setup first."
    }
}

function Get-TangerineHealth {
    try {
        $health = Invoke-RestMethod -UseBasicParsing -TimeoutSec 2 -Uri "$AppUrl/api/health"
        if ($health.status -eq "ok" -and $health.mode -eq "local-only" -and
            $null -ne $health.schema_version) {
            return $health
        }
    } catch {}
    return $null
}

function Test-LocalPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        return $pending.AsyncWaitHandle.WaitOne(400) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-TrackedTangerineProcess {
    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) { return $null }
    $savedPid = 0
    $rawPid = (Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not [int]::TryParse($rawPid, [ref]$savedPid)) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
    $tracked = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($null -eq $tracked) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
    $trackedPath = $null
    try { $trackedPath = $tracked.Path } catch {}
    if ($trackedPath -and $trackedPath -ne $Executable) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
    if (-not $trackedPath -and $tracked.ProcessName -notlike "tangerine-photo*") {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
    return $tracked
}

function Open-Tangerine {
    if (-not $NoBrowser) { Start-Process $AppUrl }
}

function Install-TangerineShortcuts {
    Assert-LauncherFiles
    if (-not (Test-Path -LiteralPath $SilentEntry -PathType Leaf)) {
        throw "The Windows launcher entry is missing."
    }
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $programs = [Environment]::GetFolderPath("Programs")
    $startMenuFolder = Join-Path $programs "TangerinePhotoAssistant"
    New-Item -ItemType Directory -Force -Path $startMenuFolder | Out-Null
    foreach ($shortcutPath in @(
        (Join-Path $desktop "TangerinePhotoAssistant.lnk"),
        (Join-Path $startMenuFolder "TangerinePhotoAssistant.lnk")
    )) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = "$env:WINDIR\System32\wscript.exe"
        $shortcut.Arguments = "`"$SilentEntry`""
        $shortcut.WorkingDirectory = $ProjectRoot
        $shortcut.IconLocation = "$IconFile,0"
        $shortcut.Description = "Open the local TangerinePhotoAssistant application"
        $shortcut.Save()
    }
    Show-LauncherMessage "Desktop and Start menu shortcuts are ready."
}

function Remove-TangerineShortcuts {
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "TangerinePhotoAssistant.lnk"
    $startMenuFolder = Join-Path ([Environment]::GetFolderPath("Programs")) "TangerinePhotoAssistant"
    $startMenuShortcut = Join-Path $startMenuFolder "TangerinePhotoAssistant.lnk"
    if (Test-Path -LiteralPath $desktopShortcut) {
        Remove-Item -LiteralPath $desktopShortcut -Force
    }
    if (Test-Path -LiteralPath $startMenuShortcut) {
        Remove-Item -LiteralPath $startMenuShortcut -Force
    }
    if ((Test-Path -LiteralPath $startMenuFolder -PathType Container) -and
        -not (Get-ChildItem -LiteralPath $startMenuFolder -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $startMenuFolder -Force
    }
    Show-LauncherMessage "Shortcuts were removed. Application data was not changed."
}

try {
    switch ($Mode) {
        "Validate" {
            Assert-LauncherFiles
            if ($Console) { Write-Host "Windows launcher prerequisites are ready." }
            exit 0
        }
        "Install" {
            Install-TangerineShortcuts
            exit 0
        }
        "Remove" {
            Remove-TangerineShortcuts
            exit 0
        }
        "Status" {
            $health = Get-TangerineHealth
            if ($null -ne $health) {
                if ($Console) {
                    Write-Host "TangerinePhotoAssistant is running (schema $($health.schema_version))."
                }
                exit 0
            }
            if ($null -ne (Get-TrackedTangerineProcess)) {
                if ($Console) { Write-Host "TangerinePhotoAssistant is starting." }
                exit 0
            }
            if ($Console) { Write-Host "TangerinePhotoAssistant is not running." }
            exit 2
        }
    }

    Assert-LauncherFiles
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $mutexSuffix = ($ProjectRoot -replace '[^A-Za-z0-9]', '_')
    $launchMutex = New-Object System.Threading.Mutex(
        $false, "Local\TangerinePhotoAssistant_$mutexSuffix"
    )
    $lockTaken = $false
    $process = $null
    $alreadyReady = $false
    try {
        try { $lockTaken = $launchMutex.WaitOne(10000) }
        catch [System.Threading.AbandonedMutexException] { $lockTaken = $true }
        if (-not $lockTaken) { throw "Another launcher is preparing the local service." }

        $health = Get-TangerineHealth
        if ($null -ne $health) {
            $alreadyReady = $true
        } else {
            $process = Get-TrackedTangerineProcess
            if ($null -eq $process) {
                if (Test-LocalPort) {
                    throw "Port $Port is used by another local application. No process was stopped."
                }
                $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
                $stdoutLog = Join-Path $RuntimeRoot "server-$timestamp.log"
                $stderrLog = Join-Path $RuntimeRoot "server-$timestamp-error.log"
                # Start-Process joins ArgumentList values with spaces. Keep the config
                # path quoted so installations under a directory with spaces work.
                $arguments = "serve --config `"$ConfigFile`" --host 127.0.0.1 --port $Port"
                $process = Start-Process -WindowStyle Hidden -PassThru -FilePath $Executable `
                    -ArgumentList $arguments -WorkingDirectory $ProjectRoot `
                    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
                Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
            }
        }
    } finally {
        if ($lockTaken) { $launchMutex.ReleaseMutex() }
        $launchMutex.Dispose()
    }
    if ($alreadyReady) {
        Open-Tangerine
        exit 0
    }

    for ($attempt = 0; $attempt -lt 900; $attempt++) {
        Start-Sleep -Seconds 1
        $process.Refresh()
        if ($process.HasExited) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
            throw "The local service stopped during startup. See runtime\launcher for its log."
        }
        $health = Get-TangerineHealth
        if ($null -ne $health) {
            Open-Tangerine
            exit 0
        }
    }
    throw "The local service did not become ready within 15 minutes. See runtime\launcher for its log."
} catch {
    Show-LauncherMessage $_.Exception.Message $true
    exit 1
}
