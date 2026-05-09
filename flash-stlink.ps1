# flash-stlink.ps1 - Build and flash bootloader + app via ST-Link
# Usage: .\flash-stlink.ps1 [-BootloaderOnly] [-AppOnly]

param(
    [switch]$BootloaderOnly,
    [switch]$AppOnly
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ensure platformio CLI is on PATH
$penvScripts = Join-Path $env:USERPROFILE ".platformio\penv\Scripts"
if (Test-Path $penvScripts) {
    $env:PATH = "$penvScripts;$env:PATH"
}

# Verify pio is available
$pioCmd = Get-Command pio -ErrorAction SilentlyContinue
if (-not $pioCmd) {
    Write-Host "ERROR: PlatformIO CLI (pio) not found. Install it first." -ForegroundColor Red
    exit 1
}

function Build-And-Flash {
    param([string]$Name, [string]$Dir)

    Write-Host ""
    Write-Host "=== Building $Name ===" -ForegroundColor Cyan
    Push-Location $Dir
    try {
        $ErrorActionPreference = "Continue"
        & pio run
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: $Name build failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "$Name build OK" -ForegroundColor Green

        Write-Host ""
        Write-Host "=== Flashing $Name via ST-Link ===" -ForegroundColor Cyan
        $ErrorActionPreference = "Continue"
        & pio run -t upload
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: $Name flash failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "$Name flash OK" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

# --- Flash bootloader first, then app ---
if (-not $AppOnly) {
    Build-And-Flash "Bootloader" (Join-Path $ROOT "bootloader")
}

if (-not $BootloaderOnly) {
    Build-And-Flash "App Firmware" (Join-Path $ROOT "osdp-controller")
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green

# Wait for USB enumeration
Write-Host "Waiting for USB device..."
Start-Sleep -Seconds 3

$dev = Get-PnpDevice -Class 'Ports' -Status OK -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -match 'VID_0483' }

if ($dev) {
    foreach ($d in $dev) {
        if ($d.InstanceId -match 'PID_5740') {
            Write-Host "App running: $($d.FriendlyName)" -ForegroundColor Green
        }
        elseif ($d.InstanceId -match 'PID_5741') {
            Write-Host "Bootloader running: $($d.FriendlyName)" -ForegroundColor Yellow
        }
    }
}
else {
    Write-Host "No OSDP device detected on USB." -ForegroundColor Yellow
}
