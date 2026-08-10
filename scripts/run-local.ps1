$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

$apiProcess = Start-Process -FilePath "py" `
  -ArgumentList "-3.13", "-m", "uvicorn", "poker_coach.api.app:app", "--app-dir", "backend" `
  -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

$webProcess = Start-Process -FilePath "npm.cmd" `
  -ArgumentList "run", "dev" `
  -WorkingDirectory (Join-Path $projectRoot "frontend") -WindowStyle Hidden -PassThru

Write-Output "Poker Coach API PID: $($apiProcess.Id)"
Write-Output "Poker Coach Web PID: $($webProcess.Id)"
Write-Output "API: http://127.0.0.1:8000"
Write-Output "Web: http://127.0.0.1:3000"
Write-Output "Stop both processes when finished; local SQLite data is under .data/."
