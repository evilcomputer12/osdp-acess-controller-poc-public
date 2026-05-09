param(
    [int]$Port = 5000,
    [string]$NgrokBinary = "ngrok"
)

$ErrorActionPreference = "Stop"

$ngrok = Get-Command $NgrokBinary -ErrorAction SilentlyContinue
if (-not $ngrok) {
    Write-Host "ERROR: ngrok was not found on PATH. Install ngrok and run 'ngrok config add-authtoken <token>' first." -ForegroundColor Red
    exit 1
}

$apiUrl = "http://127.0.0.1:4040/api/tunnels"

function Get-HttpsTunnel {
    try {
        $response = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 2
        return $response.tunnels | Where-Object { $_.proto -eq 'https' } | Select-Object -First 1
    }
    catch {
        return $null
    }
}

$existingTunnel = Get-HttpsTunnel
if ($existingTunnel) {
    Write-Host "Existing ngrok URL: $($existingTunnel.public_url)" -ForegroundColor Green
    Write-Host "Inspector: http://127.0.0.1:4040"
    exit 0
}

$process = Start-Process -FilePath $ngrok.Source -ArgumentList @('http', $Port.ToString()) -PassThru -WindowStyle Hidden
Write-Host "Started ngrok for http://localhost:$Port (PID $($process.Id))" -ForegroundColor Cyan

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $tunnel = Get-HttpsTunnel
    if ($tunnel) {
        Write-Host "Public URL: $($tunnel.public_url)" -ForegroundColor Green
        Write-Host "Inspector: http://127.0.0.1:4040"
        exit 0
    }
    if ($process.HasExited) {
        break
    }
}

Write-Host "ERROR: ngrok started but no public HTTPS tunnel was reported. Check your ngrok authtoken and local web server state." -ForegroundColor Red
exit 1