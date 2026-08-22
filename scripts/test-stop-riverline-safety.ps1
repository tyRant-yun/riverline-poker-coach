$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$stopPath = Join-Path $PSScriptRoot "stop-riverline.ps1"
$tempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("riverline-stop-test-" + [guid]::NewGuid().ToString("N"))
$statePath = Join-Path $tempDirectory "local-runtime.json"
$ownedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function New-Sleeper {
    $process = Start-Process -FilePath "pwsh" -ArgumentList "-NoProfile", "-Command", "Start-Sleep -Seconds 300" -WindowStyle Hidden -PassThru
    $ownedProcesses.Add($process)
    return $process
}

function New-State([System.Diagnostics.Process]$ApiProcess, [System.Diagnostics.Process]$WebProcess, [switch]$CorruptApiIdentity) {
    $ApiProcess.Refresh()
    $WebProcess.Refresh()
    $apiStartedAt = $ApiProcess.StartTime.ToUniversalTime()
    if ($CorruptApiIdentity) { $apiStartedAt = $apiStartedAt.AddMinutes(-5) }
    $state = [ordered]@{
        schemaVersion = 1
        projectRoot = $projectRoot
        startedAtUtc = [DateTime]::UtcNow.ToString("o")
        api = [ordered]@{
            pid = $ApiProcess.Id
            processName = $ApiProcess.ProcessName
            startedAtUtc = $apiStartedAt.ToString("o")
            startedAtUtcTicks = $apiStartedAt.Ticks
            port = 18000
            url = "http://127.0.0.1:18000/health"
        }
        web = [ordered]@{
            pid = $WebProcess.Id
            processName = $WebProcess.ProcessName
            startedAtUtc = $WebProcess.StartTime.ToUniversalTime().ToString("o")
            startedAtUtcTicks = $WebProcess.StartTime.ToUniversalTime().Ticks
            port = 13000
            url = "http://127.0.0.1:13000"
        }
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
}

try {
    New-Item -ItemType Directory -Path $tempDirectory -Force | Out-Null

    $api = New-Sleeper
    $web = New-Sleeper
    New-State $api $web
    & $stopPath -RuntimeStatePath $statePath
    Start-Sleep -Milliseconds 300
    if (Get-Process -Id $api.Id -ErrorAction SilentlyContinue) { throw "API test process was not stopped" }
    if (Get-Process -Id $web.Id -ErrorAction SilentlyContinue) { throw "Web test process was not stopped" }
    if (Test-Path -LiteralPath $statePath) { throw "Runtime state was not removed after a successful stop" }

    $api = New-Sleeper
    $web = New-Sleeper
    New-State $api $web -CorruptApiIdentity
    $caughtMismatch = $false
    try { & $stopPath -RuntimeStatePath $statePath } catch { $caughtMismatch = $_.Exception.Message.Contains("PID identity mismatch") }
    if (-not $caughtMismatch) { throw "Expected a PID identity mismatch" }
    if (-not (Get-Process -Id $api.Id -ErrorAction SilentlyContinue)) { throw "Mismatched API PID was killed" }
    if (-not (Get-Process -Id $web.Id -ErrorAction SilentlyContinue)) { throw "Preflight failure partially stopped the process set" }
    if (-not (Test-Path -LiteralPath $statePath)) { throw "State was removed after a failed identity check" }

    Write-Output "stop-riverline safety contract passed"
}
finally {
    foreach ($process in $ownedProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempDirectory) { Remove-Item -LiteralPath $tempDirectory -Recurse -Force }
}
