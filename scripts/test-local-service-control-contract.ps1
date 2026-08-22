$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$startPath = Join-Path $PSScriptRoot "start-riverline.ps1"
$stopPath = Join-Path $PSScriptRoot "stop-riverline.ps1"

if (-not (Test-Path -LiteralPath $startPath)) { throw "start-riverline.ps1 is missing" }
if (-not (Test-Path -LiteralPath $stopPath)) { throw "stop-riverline.ps1 is missing" }

$startContent = Get-Content -Raw -LiteralPath $startPath
$stopContent = Get-Content -Raw -LiteralPath $stopPath

function Require-Text([string]$Content, [string]$Needle, [string]$ScriptName) {
    if (-not $Content.Contains($Needle)) { throw "$ScriptName contract missing: $Needle" }
}

Require-Text $startContent 'run-local.ps1' 'start-riverline.ps1'
Require-Text $startContent '[switch]$NoOpen' 'start-riverline.ps1'
Require-Text $startContent 'local-runtime.json' 'start-riverline.ps1'
Require-Text $startContent 'already running' 'start-riverline.ps1'
Require-Text $startContent 'Start-Process $runtime.web.url' 'start-riverline.ps1'

Require-Text $stopContent 'local-runtime.json' 'stop-riverline.ps1'
Require-Text $stopContent 'startedAtUtc' 'stop-riverline.ps1'
Require-Text $stopContent 'processName' 'stop-riverline.ps1'
Require-Text $stopContent 'Get-ChildProcessIds' 'stop-riverline.ps1'
Require-Text $stopContent 'PID identity mismatch' 'stop-riverline.ps1'
Require-Text $stopContent 'Remove-Item -LiteralPath $RuntimeStatePath' 'stop-riverline.ps1'

Write-Output "local service-control contract passed for $projectRoot"
