[CmdletBinding()]
param(
    [switch]$UseExternalServices,
    [switch]$NoOpen,
    [ValidateRange(1, 180)]
    [int]$StartupTimeoutSeconds = 60,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$WebPort = 3000,
    [string]$RuntimeStatePath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeStatePath)) {
    $RuntimeStatePath = Join-Path $projectRoot ".data\local-runtime.json"
}

function Test-StateProcess([object]$Record) {
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    try {
        if ($null -eq $Record.startedAtUtcTicks) { return $false }
        $expectedTicks = [long]$Record.startedAtUtcTicks
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
        return (
            [string]::Equals($process.ProcessName, [string]$Record.processName, [StringComparison]::OrdinalIgnoreCase) -and
            [Math]::Abs($actualTicks - $expectedTicks) -lt [TimeSpan]::FromSeconds(2).Ticks
        )
    }
    catch { return $false }
}

if (Test-Path -LiteralPath $RuntimeStatePath) {
    try { $runtime = Get-Content -Raw -LiteralPath $RuntimeStatePath | ConvertFrom-Json }
    catch { throw "Riverline runtime state is unreadable at $RuntimeStatePath. Remove it only after confirming no Riverline service is running." }
    $apiRunning = Test-StateProcess $runtime.api
    $webRunning = Test-StateProcess $runtime.web
    if ($apiRunning -and $webRunning) {
        Write-Output "Riverline is already running."
        Write-Output "API: $($runtime.api.url) (PID $($runtime.api.pid))"
        Write-Output "Web: $($runtime.web.url) (PID $($runtime.web.pid))"
        if (-not $NoOpen) { Start-Process $runtime.web.url }
        return
    }
    if ($apiRunning -or $webRunning) {
        throw "Riverline has a partial live runtime. Run .\scripts\stop-riverline.ps1 before starting again."
    }
    Remove-Item -LiteralPath $RuntimeStatePath -Force
    Write-Output "Removed stale Riverline runtime state."
}

$arguments = @{
    StartupTimeoutSeconds = $StartupTimeoutSeconds
    ApiPort = $ApiPort
    WebPort = $WebPort
    RuntimeStatePath = $RuntimeStatePath
}
if ($UseExternalServices) { $arguments.UseExternalServices = $true }

& (Join-Path $PSScriptRoot "run-local.ps1") @arguments
$runtime = Get-Content -Raw -LiteralPath $RuntimeStatePath | ConvertFrom-Json
if (-not $NoOpen) { Start-Process $runtime.web.url }
