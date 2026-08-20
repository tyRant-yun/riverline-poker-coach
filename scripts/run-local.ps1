[CmdletBinding()]
param(
    [switch]$UseExternalServices,
    [ValidateRange(1, 180)]
    [int]$StartupTimeoutSeconds = 60,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$apiUrl = "http://127.0.0.1:$ApiPort"
$webUrl = "http://127.0.0.1:$WebPort"
$frontendDirectory = Join-Path $projectRoot "frontend"
$logDirectory = Join-Path $projectRoot ".data\local-logs"
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$apiLog = Join-Path $logDirectory "api-$runId.log"
$apiErrorLog = Join-Path $logDirectory "api-$runId.err.log"
$webLog = Join-Path $logDirectory "web-$runId.log"
$webErrorLog = Join-Path $logDirectory "web-$runId.err.log"
$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Test-TcpPortAvailable([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($connection.AsyncWaitHandle.WaitOne(200)) {
            $client.EndConnect($connection)
            return $false
        }
        return $true
    }
    catch [System.Net.Sockets.SocketException] {
        return $true
    }
    finally {
        $client.Dispose()
    }
}

function Wait-ForHttpReady([string]$Url, [string]$ProcessName, [System.Diagnostics.Process]$Process) {
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        if ($Process.HasExited) {
            throw "$ProcessName exited before becoming ready at $Url (PID $($Process.Id), exit code $($Process.ExitCode)). See $apiErrorLog and $webErrorLog."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    } while ((Get-Date) -lt $deadline)
    throw "$ProcessName did not become ready at $Url within $StartupTimeoutSeconds seconds. See $apiErrorLog and $webErrorLog."
}

function Clear-StaleNextDevelopmentLock([string]$FrontendDirectory) {
    $lockPath = Join-Path $FrontendDirectory ".next\dev\lock"
    if (-not (Test-Path -LiteralPath $lockPath)) { return }

    try {
        $lockHandle = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "Next.js development lock is already held at $lockPath. Stop the other Next.js development server before starting this project; run-local.ps1 will not replace it."
    }
    finally {
        if ($null -ne $lockHandle) { $lockHandle.Dispose() }
    }

    Remove-Item -LiteralPath $lockPath -Force
    Write-Output "Removed stale Next.js development lock: $lockPath"
}

function Get-ChildProcessIds([int]$ParentProcessId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentProcessId")
    foreach ($child in $children) {
        Get-ChildProcessIds -ParentProcessId $child.ProcessId
        $child.ProcessId
    }
}

function Stop-StartedProcesses {
    foreach ($process in $startedProcesses) {
        try {
            $processIds = @(Get-ChildProcessIds -ParentProcessId $process.Id) + $process.Id
        }
        catch {
            Write-Warning "Could not enumerate the child processes of PID $($process.Id): $($_.Exception.Message)"
            $processIds = @($process.Id)
        }
        foreach ($processId in $processIds) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher 'py' was not found. Install Python 3.13 and retry." }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "npm.cmd was not found. Install the repository's declared Node.js version and retry." }
if ($ApiPort -eq $WebPort) { throw "ApiPort and WebPort must differ." }
if (-not (Test-TcpPortAvailable $ApiPort)) { throw "Port $ApiPort is already in use. Stop the existing service or choose -ApiPort; run-local.ps1 will not replace it." }
if (-not (Test-TcpPortAvailable $WebPort)) { throw "Port $WebPort is already in use. Stop the existing web server or choose -WebPort; run-local.ps1 will not replace it." }
Clear-StaleNextDevelopmentLock $frontendDirectory

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$childEnvironment = @{ NEXT_PUBLIC_API_BASE_URL = $apiUrl; POKER_COACH_CORS_ORIGINS = $webUrl }
if (-not $UseExternalServices) {
    # Empty process variables take precedence over .env without changing that file.
    $childEnvironment["POKER_COACH_DATABASE_URL"] = ""
    $childEnvironment["POKER_COACH_REDIS_URL"] = ""
    $childEnvironment["POKER_COACH_REDIS_WORKER_IN_PROCESS"] = ""
}

try {
    $apiProcess = Start-Process -FilePath "py" `
        -ArgumentList "-3.13", "-m", "uvicorn", "poker_coach.api.app:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "$ApiPort" `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -Environment $childEnvironment `
        -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrorLog
    $startedProcesses.Add($apiProcess)
    Wait-ForHttpReady "$apiUrl/health" "Backend" $apiProcess

    $webProcess = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "$WebPort" `
        -WorkingDirectory $frontendDirectory -WindowStyle Hidden -PassThru -Environment $childEnvironment `
        -RedirectStandardOutput $webLog -RedirectStandardError $webErrorLog
    $startedProcesses.Add($webProcess)
    Wait-ForHttpReady $webUrl "Frontend" $webProcess
}
catch {
    Stop-StartedProcesses
    throw "Local startup failed: $($_.Exception.Message)"
}

$mode = if ($UseExternalServices) { "external DB/Redis opt-in (environment/.env is inherited)" } else { "default local SQLite + no Redis (external .env values are masked only for these child processes)" }
Write-Output "Riverline local experience is ready."
Write-Output "Mode: $mode"
Write-Output "API: $apiUrl/health (PID $($apiProcess.Id))"
Write-Output "Web: $webUrl (PID $($webProcess.Id))"
Write-Output "Logs: $logDirectory"
Write-Output "Stop the listed child PIDs when finished. This script did not modify .env."
