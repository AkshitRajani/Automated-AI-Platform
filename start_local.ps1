# Bring up local Automated AI Platform Docker infra + wire .env + optional sandbox UI deps.
# Requires Docker Desktop running.
# Usage:  powershell -ExecutionPolicy Bypass -File .\start_local.ps1

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> 1) KB Postgres (knowledge_base on localhost:5432)"
docker compose -f docker-compose.local.yml up -d --wait
if ($LASTEXITCODE -ne 0) {
    Write-Host "compose up returned $LASTEXITCODE - retrying without --wait"
    docker compose -f docker-compose.local.yml up -d
}

Write-Host "==> 2) Sandbox stack (LocalStack :4566, Microcks :8080, Postgres :5433)"
$CoreDir = Join-Path $Root "sandbox\sandbox\core"
$ComposeFile = Join-Path $CoreDir "profiles\default\docker-compose.yml"
Push-Location $CoreDir
docker compose -f $ComposeFile up -d
$composeExit = $LASTEXITCODE
Pop-Location
if ($composeExit -ne 0) {
    Write-Warning "Sandbox compose failed with exit $composeExit"
}

Write-Host "==> 3) Wait for health endpoints"
$deadline = (Get-Date).AddMinutes(4)
do {
    $ls = $false; $pg = $false; $kb = $false
    try { $ls = (Invoke-WebRequest -Uri "http://localhost:4566/_localstack/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch {}
    try { $kb = (docker exec aap_kb_postgres pg_isready -U postgres -d knowledge_base 2>$null) -match "accepting" } catch {}
    try { $pg = (docker exec (docker ps -qf "ancestor=postgres:16" | Select-Object -First 1) pg_isready -U postgres 2>$null) -match "accepting" } catch { $pg = $true }
    if ($ls -and $kb) { break }
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)
Write-Host "  LocalStack healthy: $ls"
Write-Host "  KB Postgres ready:  $kb"

Write-Host "==> 4) Ensure knowledge_base schema applied"
docker exec -i aap_kb_postgres psql -U postgres -d knowledge_base -c "SELECT COUNT(*) AS tables FROM information_schema.tables WHERE table_schema='public';" 2>&1 | Out-Host
# Re-apply schema idempotently
Get-Content (Join-Path $Root "ingestion\schema.sql") -Raw | docker exec -i aap_kb_postgres psql -U postgres -d knowledge_base 2>&1 | Select-Object -Last 5

Write-Host "==> 5) Point ingestion/.env at local Postgres"
$envFile = Join-Path $Root "ingestion\.env"
if (Test-Path $envFile) {
    $text = Get-Content $envFile -Raw
    $text = $text -replace '(?m)^PG_HOST=.*', 'PG_HOST=127.0.0.1'
    $text = $text -replace '(?m)^PG_PORT=.*', 'PG_PORT=5432'
    $text = $text -replace '(?m)^PG_DATABASE=.*', 'PG_DATABASE=knowledge_base'
    $text = $text -replace '(?m)^PG_USER=.*', 'PG_USER=postgres'
    $text = $text -replace '(?m)^PG_PASSWORD=.*', 'PG_PASSWORD=postgres'
    if ($text -notmatch '(?m)^PG_HOST=') { $text += "`nPG_HOST=127.0.0.1`n" }
    Set-Content -Path $envFile -Value $text -NoNewline
    Write-Host "  updated PG_* in ingestion\.env"
}

Write-Host "==> 6) Install host tools (awscli, uv, web deps)"
$Pip = Join-Path $Root ".venv\Scripts\pip.exe"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $Pip) {
    & $Pip install "awscli>=1.32" "uvicorn[standard]" fastapi pyyaml python-multipart pandas 2>&1 | Select-Object -Last 8
} else {
    Write-Warning "Root .venv missing - run setup_platform.ps1 first"
}

# uv (optional, for sandbox backend)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  installing uv..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Warning "uv install skipped: $_"
    }
}

Write-Host "==> 7) Sandbox web UI npm install"
$UiDir = Join-Path $Root "sandbox\sandbox\web_app\ui"
if (Test-Path (Join-Path $UiDir "package.json")) {
    Push-Location $UiDir
    npm install 2>&1 | Select-Object -Last 15
    Pop-Location
}

Write-Host "==> 8) Sandbox backend pip install"
$BeDir = Join-Path $Root "sandbox\sandbox\web_app\backend"
if (Test-Path $Py) {
    & $Py -m pip install -e $BeDir 2>&1 | Select-Object -Last 15
}

Write-Host ""
Write-Host "==================== LOCAL STACK READY ===================="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | Select-String -Pattern "aap_|localstack|microcks|postgres|NAMES"
Write-Host ""
Write-Host "Endpoints:"
Write-Host "  LocalStack   http://localhost:4566"
Write-Host "  Microcks     http://localhost:8080"
Write-Host "  Sandbox PG   localhost:5433 / aap_sandbox (postgres/postgres)"
Write-Host "  KB Postgres  localhost:5432 / knowledge_base (postgres/postgres)"
Write-Host ""
Write-Host "Next:"
Write-Host "  . .\setup_env.ps1"
Write-Host "  # optional seeder (WSL): wsl bash sandbox/sandbox/core/profiles/default/seeder.sh"
Write-Host "  # sandbox UI backend:  cd sandbox\sandbox\web_app\backend; ..\..\..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765"
Write-Host "  # sandbox UI front:    cd sandbox\sandbox\web_app\ui; npm run dev"
Write-Host "==========================================================="
