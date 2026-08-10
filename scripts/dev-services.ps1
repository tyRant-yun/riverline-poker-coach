# Starts the local PostgreSQL and Redis containers used by deployment
# regression tests. Requires Docker Desktop to be running.
#
# Usage:
#   .\scripts\dev-services.ps1            # start both containers
#   .\scripts\dev-services.ps1 -Down      # stop and remove them

param(
    [switch]$Down
)

$ErrorActionPreference = "Stop"

$containers = @(
    @{
        Name = "pkcoach-pg"
        Image = "postgres:16-alpine"
        Ports = @("55432:5432")
        Env = @("POSTGRES_PASSWORD=coach", "POSTGRES_USER=coach", "POSTGRES_DB=coach")
    },
    @{
        Name = "pkcoach-redis"
        Image = "redis:7-alpine"
        Ports = @("56379:6379")
        Env = @()
    }
)

foreach ($spec in $containers) {
    $name = $spec.Name
    $existing = docker ps -a --filter "name=^/$name$" --format "{{.Names}}"
    if ($Down) {
        if ($existing) {
            docker rm -f $name | Out-Null
            Write-Host "Removed $name"
        }
        continue
    }
    if ($existing) {
        $running = docker ps --filter "name=^/$name$" --format "{{.Names}}"
        if ($running) {
            Write-Host "$name already running"
            continue
        }
        docker start $name | Out-Null
        Write-Host "Started $name"
        continue
    }
    $args = @("run", "-d", "--name", $name)
    foreach ($port in $spec.Ports) { $args += @("-p", $port) }
    foreach ($env in $spec.Env) { $args += @("-e", $env) }
    $args += $spec.Image
    docker @args | Out-Null
    Write-Host "Created $name"
}

if (-not $Down) {
    Write-Host ""
    Write-Host "PostgreSQL: postgresql://coach:coach@127.0.0.1:55432/coach"
    Write-Host "Redis:      127.0.0.1:56379"
    Write-Host "Live regression: `$env:POKER_COACH_TEST_PG_URL='postgresql://coach:coach@127.0.0.1:55432/coach_test'"
    Write-Host "                 py -3.13 -m pytest backend/tests/test_postgres_live.py -v"
}
