<#
.SYNOPSIS
    Restarts the stonky-backend Windows service and verifies health.

.DESCRIPTION
    Stops then starts the stonky-backend service, waits for the health endpoint,
    and reports success or failure. Intended for use by the Trading Company
    Release Manager agent (TC-002b) and for manual restarts.

.PARAMETER HealthWaitSecs
    Seconds to wait after issuing Start-Service before polling the health endpoint.
    Default: 15.
#>
param(
    [int]$HealthWaitSecs = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ServiceName = "stonky-backend"
$HealthUrl   = "http://localhost:8000/api/health"

function Write-Step { param($msg) Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

# Verify service exists
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Fail "Service '$ServiceName' not found. Run install-stonky-service.ps1 first."
    exit 1
}

# Stop
Write-Step "Stopping $ServiceName (current: $($svc.Status))..."
Stop-Service -Name $ServiceName -Force -ErrorAction Stop
$svc.WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
Write-Ok "Service stopped."

# Start
Write-Step "Starting $ServiceName..."
Start-Service -Name $ServiceName -ErrorAction Stop
Write-Ok "Start command issued."

# Health check
Write-Step "Waiting $HealthWaitSecs s for initialisation..."
Start-Sleep -Seconds $HealthWaitSecs

Write-Step "Polling $HealthUrl ..."
$deadline = (Get-Date).AddSeconds(30)
$healthy  = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
        $healthy = $true
        Write-Ok "Health check PASSED: $($r | ConvertTo-Json -Compress)"
        break
    } catch {
        Write-Step "Not ready yet -- retrying in 3 s..."
        Start-Sleep -Seconds 3
    }
}

if (-not $healthy) {
    Write-Fail "Stonky did not become healthy within 30 s after restart."
    Write-Fail "Check logs:"
    Write-Fail "  C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.err.log"
    exit 1
}

Write-Ok "Restart complete. Stonky is healthy."
