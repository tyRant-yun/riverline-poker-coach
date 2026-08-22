[CmdletBinding()]
param(
    [string]$RuntimeStatePath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeStatePath)) {
    $RuntimeStatePath = Join-Path $projectRoot ".data\local-runtime.json"
}

function Get-ChildProcessIds([int]$ParentProcessId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentProcessId")
    foreach ($child in $children) {
        Get-ChildProcessIds -ParentProcessId $child.ProcessId
        $child.ProcessId
    }
}

function Assert-ProcessIdentity([string]$Label, [object]$Record) {
    if ($null -eq $Record -or $null -eq $Record.pid -or $null -eq $Record.startedAtUtcTicks -or [string]::IsNullOrWhiteSpace([string]$Record.startedAtUtc)) {
        throw "Runtime state is missing the $Label process identity."
    }
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        $expectedTicks = [long]$Record.startedAtUtcTicks
        $actualStart = $process.StartTime.ToUniversalTime()
    }
    catch {
        throw "PID identity mismatch for $Label PID $($Record.pid): start time could not be verified."
    }
    $nameMatches = [string]::Equals($process.ProcessName, [string]$Record.processName, [StringComparison]::OrdinalIgnoreCase)
    $timeMatches = [Math]::Abs($actualStart.Ticks - $expectedTicks) -lt [TimeSpan]::FromSeconds(2).Ticks
    if (-not $nameMatches -or -not $timeMatches) {
        $expectedStart = [DateTime]::new($expectedTicks, [DateTimeKind]::Utc)
        throw "PID identity mismatch for $Label PID $($Record.pid); expected $($Record.processName) at $($expectedStart.ToString('o')), found $($process.ProcessName) at $($actualStart.ToString('o')); refusing to stop an unrelated process."
    }
    return $process
}

if (-not (Test-Path -LiteralPath $RuntimeStatePath)) {
    Write-Output "Riverline is not running (no runtime state found)."
    return
}

try { $runtime = Get-Content -Raw -LiteralPath $RuntimeStatePath | ConvertFrom-Json }
catch { throw "Riverline runtime state is unreadable at $RuntimeStatePath; refusing to guess which processes to stop." }

if (-not [string]::Equals([string]$runtime.projectRoot, $projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime state belongs to another project root; refusing to stop it."
}

# Validate every live root before stopping any process, so a stale PID cannot cause a partial shutdown.
$validated = @(
    [pscustomobject]@{ label = "Web"; process = (Assert-ProcessIdentity "Web" $runtime.web) }
    [pscustomobject]@{ label = "API"; process = (Assert-ProcessIdentity "API" $runtime.api) }
)

foreach ($entry in $validated) {
    if ($null -eq $entry.process) { continue }
    try {
        $processIds = @(Get-ChildProcessIds -ParentProcessId $entry.process.Id) + $entry.process.Id
    }
    catch {
        Write-Warning "Could not enumerate children of $($entry.label) PID $($entry.process.Id); stopping the verified root process only. $($_.Exception.Message)"
        $processIds = @($entry.process.Id)
    }
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Write-Output "Stopped $($entry.label) process tree (root PID $($entry.process.Id))."
}

Remove-Item -LiteralPath $RuntimeStatePath -Force
Write-Output "Riverline stopped. Runtime state removed."
