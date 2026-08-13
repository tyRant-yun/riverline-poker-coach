$ErrorActionPreference = "Stop"
$scriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\run-local.ps1"
$content = Get-Content -Raw -LiteralPath $scriptPath

function Require-Text([string]$Needle) {
    if (-not $content.Contains($Needle)) { throw "run-local.ps1 contract missing: $Needle" }
}

Require-Text '[switch]$UseExternalServices'
Require-Text '[int]$ApiPort = 8000'
Require-Text '[int]$WebPort = 3000'
Require-Text 'POKER_COACH_DATABASE_URL"] = ""'
Require-Text 'POKER_COACH_REDIS_URL"] = ""'
Require-Text 'Start-Process -FilePath "py"'
Require-Text 'Wait-ForHttpReady "$apiUrl/health" "Backend"'
Require-Text 'Get-ChildProcessIds'
Require-Text "Stop-StartedProcesses"
Require-Text "-WindowStyle Hidden"
Write-Output "run-local.ps1 contract passed"
