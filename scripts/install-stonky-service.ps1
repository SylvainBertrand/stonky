#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs the Stonky backend as a Windows service managed by NSSM.

.DESCRIPTION
    This script:
      1. Checks for admin privileges (required for service management).
      2. Downloads and installs NSSM 2.24 if not already present.
      3. Registers (or re-registers) the stonky-backend Windows service.
      4. Starts the service and verifies the health endpoint.

    Prerequisites:
      - PowerShell 5.1+ (ships with Windows 10/11)
      - Admin privileges (run from an elevated PowerShell prompt)
      - uv installed (https://docs.astral.sh/uv/)
      - Docker running with Postgres up (docker compose up -d)
      - .env file present at the repo root (cp .env.example .env)

.NOTES
    NSSM install location: C:\Program Files\nssm\nssm.exe
    Service name:          stonky-backend
    Working directory:     C:\Users\sylva\my-software-projects\stonky\backend
    Stdout log:            C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.out.log
    Stderr log:            C:\Users\sylva\my-software-projects\stonky\logs\stonky-backend.err.log
    Health endpoint:       http://localhost:8000/api/health

    For dev hot-reload, continue using start-backend.sh.
    The service is the production/unattended runtime path.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$ServiceName    = "stonky-backend"
$DisplayName    = "Stonky Backend (FastAPI)"
$Description    = "Stonky personal investment analysis backend. Managed by Trading Company Release Manager."
$RepoRoot       = "C:\Users\sylva\my-software-projects\stonky"
$BackendDir     = "$RepoRoot\backend"
$LogDir         = "$RepoRoot\logs"
$StdoutLog      = "$LogDir\stonky-backend.out.log"
$StderrLog      = "$LogDir\stonky-backend.err.log"
$NssmDir        = "C:\Program Files\nssm"
$NssmExe        = "$NssmDir\nssm.exe"
$NssmVersion    = "2.24"
$NssmZipUrl     = "https://nssm.cc/release/nssm-$NssmVersion.zip"
$NssmZipPath    = "$env:TEMP\nssm-$NssmVersion.zip"
$NssmExtractDir = "$env:TEMP\nssm-$NssmVersion"
$HealthUrl      = "http://localhost:8000/api/health"
$HealthWaitSecs = 15

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step  { param($msg) Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# 1. Admin check (belt-and-suspenders -- #Requires above handles CLI invocation)
# ---------------------------------------------------------------------------
Write-Step "Checking for admin privileges..."
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "This script must be run from an elevated (admin) PowerShell prompt."
    Write-Fail "Right-click PowerShell -> 'Run as Administrator', then re-run."
    exit 1
}
Write-Ok "Running as Administrator."

# ---------------------------------------------------------------------------
# 2. Locate uv
# ---------------------------------------------------------------------------
Write-Step "Locating uv executable..."
# uv is typically installed to ~/.local/bin which may not be in the system PATH
# when running from an elevated session. Search common locations.
$UvExe = $null
$UvCandidates = @(
    "$env:USERPROFILE\.local\bin\uv.exe",
    "$env:LOCALAPPDATA\uv\uv.exe",
    "$env:USERPROFILE\.cargo\bin\uv.exe"
)
# Also check PATH
$uvOnPath = Get-Command uv -ErrorAction SilentlyContinue
if ($uvOnPath) { $UvCandidates = @($uvOnPath.Source) + $UvCandidates }

foreach ($candidate in $UvCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $UvExe = $candidate
        break
    }
}

if (-not $UvExe) {
    Write-Fail "'uv' not found. Install uv first: https://docs.astral.sh/uv/"
    Write-Fail "Searched: PATH, $env:USERPROFILE\.local\bin\uv.exe, $env:LOCALAPPDATA\uv\uv.exe"
    exit 1
}
Write-Ok "uv found at: $UvExe"

# ---------------------------------------------------------------------------
# 3. Verify backend directory and .env
# ---------------------------------------------------------------------------
Write-Step "Verifying repo structure..."
if (-not (Test-Path $BackendDir)) {
    Write-Fail "Backend directory not found: $BackendDir"
    exit 1
}
$EnvFile = "$RepoRoot\.env"
if (-not (Test-Path $EnvFile)) {
    Write-Fail ".env not found at $EnvFile"
    Write-Fail "Run:  cp .env.example .env  from the repo root, then edit POSTGRES_PASSWORD."
    exit 1
}
Write-Ok "Repo structure OK."

# ---------------------------------------------------------------------------
# 4. Install NSSM if missing
# ---------------------------------------------------------------------------
Write-Step "Checking NSSM installation..."
if (Test-Path $NssmExe) {
    Write-Ok "NSSM already installed at $NssmExe"
} else {
    Write-Step "NSSM not found -- downloading NSSM $NssmVersion..."
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $NssmZipUrl -OutFile $NssmZipPath -UseBasicParsing
        Write-Ok "Downloaded to $NssmZipPath"
    } catch {
        Write-Fail "Failed to download NSSM: $_"
        Write-Fail "Download manually from https://nssm.cc/release/nssm-$NssmVersion.zip"
        Write-Fail "Extract nssm.exe (64-bit build, from win64 folder) to $NssmExe, then re-run."
        exit 1
    }

    Write-Step "Extracting NSSM..."
    if (Test-Path $NssmExtractDir) { Remove-Item $NssmExtractDir -Recurse -Force }
    Expand-Archive -Path $NssmZipPath -DestinationPath $NssmExtractDir -Force

    # The zip contains nssm-2.24/win64/nssm.exe (and win32/)
    $NssmSrc = Get-ChildItem -Path $NssmExtractDir -Recurse -Filter "nssm.exe" |
                Where-Object { $_.FullName -match "win64" } |
                Select-Object -First 1
    if (-not $NssmSrc) {
        Write-Fail "Could not find win64/nssm.exe in the extracted archive."
        exit 1
    }

    if (-not (Test-Path $NssmDir)) { New-Item -ItemType Directory -Path $NssmDir | Out-Null }
    Copy-Item $NssmSrc.FullName -Destination $NssmExe -Force
    Write-Ok "NSSM installed to $NssmExe"

    # Clean up temp files
    Remove-Item $NssmZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item $NssmExtractDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 5. Create log directory
# ---------------------------------------------------------------------------
Write-Step "Ensuring log directory exists: $LogDir"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Ok "Log directory created."
} else {
    Write-Ok "Log directory already exists."
}

# ---------------------------------------------------------------------------
# 6. Handle existing service
# ---------------------------------------------------------------------------
Write-Step "Checking if service '$ServiceName' already exists..."
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Warn "Service '$ServiceName' already exists (Status: $($existingService.Status))."
    Write-Step "Stopping and removing existing service to reinstall cleanly..."
    if ($existingService.Status -ne "Stopped") {
        Write-Step "Stopping service..."
        & $NssmExe stop $ServiceName
        Start-Sleep -Seconds 3
    }
    & $NssmExe remove $ServiceName confirm
    Write-Ok "Existing service removed."
}

# ---------------------------------------------------------------------------
# 7. Register the service with NSSM
# ---------------------------------------------------------------------------
Write-Step "Registering service '$ServiceName'..."

& $NssmExe install $ServiceName $UvExe
& $NssmExe set $ServiceName DisplayName $DisplayName
& $NssmExe set $ServiceName Description $Description

# Application arguments -- NO --reload (that is for dev only)
& $NssmExe set $ServiceName AppParameters "run uvicorn app.main:app --host 0.0.0.0 --port 8000"

# Working directory -- the backend folder where pyproject.toml lives
& $NssmExe set $ServiceName AppDirectory $BackendDir

# Startup type: automatic (start on boot)
& $NssmExe set $ServiceName Start SERVICE_AUTO_START

# Stdout / Stderr logging
& $NssmExe set $ServiceName AppStdout $StdoutLog
& $NssmExe set $ServiceName AppStderr $StderrLog

# Log rotation: rotate on service restart; keep rotated files
& $NssmExe set $ServiceName AppStdoutCreationDisposition 4   # OPEN_ALWAYS (append)
& $NssmExe set $ServiceName AppStderrCreationDisposition 4
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateOnline 0               # rotate on service restart
& $NssmExe set $ServiceName AppRotateSeconds 0
& $NssmExe set $ServiceName AppRotateBytes 0

# Restart on failure: 10 s delay, 60 s throttle (won't thrash on hard crash)
& $NssmExe set $ServiceName AppRestartDelay 10000           # ms
& $NssmExe set $ServiceName AppThrottle 60000               # ms -- reset window

# .env note: config.py resolves .env via Path(__file__).resolve().parents[2]
# which is an absolute path computed from the source file location -- not CWD.
# Therefore AppDirectory=backend/ is safe; no AppEnvironmentExtra needed.

Write-Ok "Service registered."

# ---------------------------------------------------------------------------
# 8. Grant non-admin service-control rights via SDDL (TC-002c)
#
#    Windows defaults give only Administrators/SYSTEM start+stop rights.
#    We add an Access-Allowed ACE for the current interactive user so that
#    unattended agents (e.g. TC-002b Release Manager) running as that user
#    can restart the service from a non-elevated shell with zero UAC prompts.
#
#    Permissions granted: RP=Start  WP=Stop  DT=Pause/Continue
#                         LO=Interrogate  RC=ReadControl
# ---------------------------------------------------------------------------
Write-Step "Granting service-control rights to the current user via SDDL..."

# --- Resolve the interactive user's SID.
#     $env:USERNAME is preserved across UAC elevation (right-click Run as Admin),
#     so this resolves the *original* user, not SYSTEM/Administrator.
$UserAccount = "$env:USERDOMAIN\$env:USERNAME"
try {
    $NtAccount = [System.Security.Principal.NTAccount]$UserAccount
    $UserSid   = $NtAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
} catch {
    Write-Fail "Failed to resolve SID for '$UserAccount': $_"
    Write-Fail "Cannot grant service-control rights. Aborting install."
    exit 1
}
Write-Step "Resolved user: $UserAccount  →  SID: $UserSid"

# Guard: refuse to grant if the SID resolves to a built-in system account that
# already has full control — this would mean $env:USERNAME is wrong in context.
$SystemSids = @("S-1-5-18", "S-1-5-19", "S-1-5-20")   # SYSTEM, LOCAL SERVICE, NETWORK SERVICE
if ($SystemSids -contains $UserSid) {
    Write-Fail "Resolved SID '$UserSid' is a built-in system account."
    Write-Fail "This means the interactive user identity could not be determined."
    Write-Fail "Run the install from a regular elevated session (right-click -> Run as Admin)."
    exit 1
}

# --- Fetch the current service SDDL.
$rawSddl = & sc.exe sdshow $ServiceName 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "sc.exe sdshow returned exit code $LASTEXITCODE. Raw output: $rawSddl"
    Write-Fail "Cannot read service SDDL. Aborting install."
    exit 1
}
$currentSddl = ($rawSddl | Out-String).Trim()
Write-Step "Current SDDL: $currentSddl"

# --- Idempotency check: skip if user's SID already present in DACL.
if ($currentSddl -match [regex]::Escape($UserSid)) {
    Write-Ok "SID '$UserSid' already present in service SDDL — skipping ACE grant (idempotent)."
} else {
    # Build the new ACE: Access-Allowed, RP=Start WP=Stop DT=Pause LO=Interrogate RC=ReadControl
    $NewAce = "(A;;RPWPDTLORC;;;$UserSid)"

    # Insert ACE into the DACL section.
    # Common formats:
    #   D:...                       → pure DACL, no SACL
    #   D:...(S:...)                → DACL followed by optional SACL
    # Strategy: split on /(S:[^)]*(\([^)]*\))*)/ boundary and insert before SACL (or append).
    if ($currentSddl -match '^(D:[^S]*)(S:.+)?$') {
        $DaclPart  = $Matches[1]
        $SaclPart  = if ($Matches[2]) { $Matches[2] } else { "" }
        $newSddl   = "$DaclPart$NewAce$SaclPart"
    } else {
        # Unexpected format — log and abort rather than guessing.
        Write-Fail "Cannot parse SDDL into DACL/SACL sections. Raw value: $currentSddl"
        Write-Fail "Expected format starting with 'D:'. Please review manually:"
        Write-Fail "  sc.exe sdshow $ServiceName"
        exit 1
    }

    Write-Step "Applying new SDDL: $newSddl"
    & sc.exe sdset $ServiceName $newSddl | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "sc.exe sdset returned exit code $LASTEXITCODE. SDDL was: $newSddl"
        Write-Fail "Service DACL was NOT updated. Aborting install."
        exit 1
    }
    Write-Ok "Granted start/stop/query rights to $UserAccount ($UserSid)."
}

# ---------------------------------------------------------------------------
# 9. Start the service
# ---------------------------------------------------------------------------
Write-Step "Starting service '$ServiceName'..."
& $NssmExe start $ServiceName
if ($LASTEXITCODE -ne 0) {
    Write-Fail "NSSM reported an error starting the service (exit code $LASTEXITCODE)."
    Write-Fail "Check event log: Get-EventLog -LogName Application -Source nssm -Newest 10"
    Write-Fail "Check stderr log: $StderrLog"
    exit 1
}
Write-Ok "Start command issued."

# ---------------------------------------------------------------------------
# 10. Health check
# ---------------------------------------------------------------------------
Write-Step "Waiting $HealthWaitSecs seconds for Stonky to initialise..."
Start-Sleep -Seconds $HealthWaitSecs

Write-Step "Checking health endpoint: $HealthUrl"
try {
    $response = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 10
    Write-Ok "Health check PASSED."
    Write-Ok "Response: $($response | ConvertTo-Json -Compress)"
} catch {
    Write-Fail "Health check FAILED: $_"
    Write-Fail "Service may still be starting -- check logs:"
    Write-Fail "  Stdout: $StdoutLog"
    Write-Fail "  Stderr: $StderrLog"
    Write-Fail "Service status:"
    Get-Service -Name $ServiceName -ErrorAction SilentlyContinue | Format-List
    exit 1
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Ok "====================================================="
Write-Ok " stonky-backend service installed and running!"
Write-Ok "====================================================="
Write-Host ""
Write-Host "Management commands:" -ForegroundColor White
Write-Host "  Start:   net start $ServiceName   (or: Start-Service $ServiceName)" -ForegroundColor Gray
Write-Host "  Stop:    net stop $ServiceName    (or: Stop-Service $ServiceName)" -ForegroundColor Gray
Write-Host "  Restart: scripts\restart-stonky-service.ps1" -ForegroundColor Gray
Write-Host "  Remove:  scripts\uninstall-stonky-service.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "Log files:" -ForegroundColor White
Write-Host "  Stdout: $StdoutLog" -ForegroundColor Gray
Write-Host "  Stderr: $StderrLog" -ForegroundColor Gray
Write-Host ""
Write-Host "Health endpoint: $HealthUrl" -ForegroundColor White
Write-Host ""
Write-Warn "REMINDER: start-backend.sh is still available for dev mode (hot-reload)."
Write-Warn "Use this service for unattended/automated contexts (Trading Company agents)."
