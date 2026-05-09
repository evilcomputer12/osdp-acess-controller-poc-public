# OSDP Access Control Panel - Run (PowerShell)
# Usage: .\run.ps1
#        Opens React on http://localhost:3000, Flask API on http://localhost:5000

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== OSDP Access Control Panel ===" -ForegroundColor Cyan

# -- Python dependencies --
Write-Host ""
Write-Host "[1/3] Installing Python dependencies..." -ForegroundColor Yellow
Push-Location $root
& pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed - make sure Python and pip are on PATH" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# -- Frontend build --
Write-Host ""
Write-Host "[2/3] Installing frontend dependencies..." -ForegroundColor Yellow
Push-Location (Join-Path $root "frontend")
& npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "npm install failed" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# -- Start backend + frontend dev server --
Write-Host ""
Write-Host "[3/3] Starting Flask API on http://localhost:5000" -ForegroundColor Green
Write-Host "       Starting React dev server on http://localhost:3000" -ForegroundColor Magenta
Write-Host ""
Write-Host "Open http://localhost:3000 in your browser" -ForegroundColor Cyan

$frontendDir = Join-Path $root "frontend"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontendDir'; npm run dev"

Push-Location $root
& python app.py
Pop-Location
