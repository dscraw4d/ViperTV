$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Docker Desktop is not installed or docker is not in PATH." -ForegroundColor Red
    exit 1
}
try { docker compose version | Out-Null } catch {
    Write-Host "ERROR: Docker Compose v2 is required." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path data, backups, media | Out-Null
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "Building and starting ViperTV..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$port = "8409"
$line = Get-Content .env | Where-Object { $_ -match '^VIPERTV_PORT=' } | Select-Object -First 1
if ($line) { $port = ($line -split '=',2)[1].Trim() }
Write-Host ""
Write-Host "ViperTV is starting. Open http://localhost:$port"
Write-Host "For LAN clients, use this PC's LAN IP and the same port."
