#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Removes the stonky-backend Windows service managed by NSSM.

.DESCRIPTION
    Stops the running service (if any), then removes it via NSSM.
    Log files are intentionally left in place for post-mortem analysis.

.NOTES
    Log files are preserved at:
      C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.out.log
      C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.err.log
    Delete them manually if no longer needed.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ServiceName = "stonky-backend"
$NssmExe     = "C:\Program Files\nssm\nssm.exe"
$LogDir      = "C:\Users\sylva\my-software-projects\stonky\logs"

function Write-Step { param($msg) Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

# Admin check
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "This script must be run from an elevated PowerShell prompt."
    exit 1
}

# Verify NSSM is available
if (-not (Test-Path $NssmExe)) {
    Write-Fail "NSSM not found at $NssmExe"
    Write-Fail "If the service was installed via a different NSSM location, use:"
    Write-Fail "  sc stop $ServiceName; sc delete $ServiceName"
    exit 1
}

# Check service exists
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Warn "Service '$ServiceName' does not exist -- nothing to remove."
    exit 0
}

# Stop the service
if ($svc.Status -ne "Stopped") {
    Write-Step "Stopping service '$ServiceName' (current status: $($svc.Status))..."
    & $NssmExe stop $ServiceName
    Start-Sleep -Seconds 5
    $svc.Refresh()
    if ($svc.Status -ne "Stopped") {
        Write-Warn "Service did not stop cleanly; forcing removal anyway."
    } else {
        Write-Ok "Service stopped."
    }
} else {
    Write-Ok "Service is already stopped."
}

# Remove the service
Write-Step "Removing service '$ServiceName'..."
& $NssmExe remove $ServiceName confirm
if ($LASTEXITCODE -ne 0) {
    Write-Fail "NSSM remove returned exit code $LASTEXITCODE"
    Write-Fail "Try manually: sc delete $ServiceName"
    exit 1
}

Write-Ok "Service '$ServiceName' removed."
Write-Host ""
Write-Warn "Log files preserved at $LogDir -- delete manually when no longer needed."
Write-Host "  $LogDir\stonky-backend.out.log" -ForegroundColor Gray
Write-Host "  $LogDir\stonky-backend.err.log" -ForegroundColor Gray
Write-Host ""
Write-Ok "Uninstall complete."
