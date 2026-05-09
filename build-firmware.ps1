# build-firmware.ps1 - Build app firmware and export a timestamped .bin for web update
# Usage: .\build-firmware.ps1
# Output: firmware\osdp-bridge-YYYYMMDD-HHmmss.bin

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ensure platformio CLI is on PATH
$penvScripts = Join-Path $env:USERPROFILE ".platformio\penv\Scripts"
if (Test-Path $penvScripts) {
    $env:PATH = "$penvScripts;$env:PATH"
}

$pioCmd = Get-Command pio -ErrorAction SilentlyContinue
if (-not $pioCmd) {
    Write-Host "ERROR: PlatformIO CLI (pio) not found." -ForegroundColor Red
    exit 1
}

$appDir = Join-Path $ROOT "osdp-controller"
$outDir = Join-Path $ROOT "firmware"
$srcBin = Join-Path $appDir ".pio\build\bluepill\firmware.bin"

# Build
Write-Host "=== Building App Firmware ===" -ForegroundColor Cyan
Push-Location $appDir
try {
    pio run 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Build failed." -ForegroundColor Red
        exit 1
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $srcBin)) {
    Write-Host "ERROR: firmware.bin not found at $srcBin" -ForegroundColor Red
    exit 1
}

# Create output directory
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

# Timestamped filename
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$outFile = Join-Path $outDir "osdp-bridge-$ts.bin"

Copy-Item -Path $srcBin -Destination $outFile
$size = (Get-Item $outFile).Length

Write-Host ""
Write-Host "=== Firmware Ready ===" -ForegroundColor Green
Write-Host "File : $outFile"
Write-Host "Size : $size bytes"
Write-Host ""
Write-Host "Upload this file via the web panel (Firmware page) to update over USB."
