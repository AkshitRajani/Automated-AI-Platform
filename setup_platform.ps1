# One-time / refresh setup for the full Automated AI Platform monorepo on Windows.
# Creates root .venv, installs module requirements, copies env templates,
# and smoke-checks CLI entrypoints.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PyArgs)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 @PyArgs
        if ($LASTEXITCODE -ne 0) { & py @PyArgs }
    } else {
        & python @PyArgs
    }
}

Write-Host "==> Creating / refreshing root .venv"
if (-not (Test-Path ".venv")) {
    Invoke-Py -m venv .venv
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Pip = Join-Path $Root ".venv\Scripts\pip.exe"
& $Py -m pip install --upgrade pip

Write-Host "==> Installing module requirements"
$reqFiles = @(
    "analyzer\requirements.txt",
    "coding_agent\requirements.txt",
    "ingestion\requirements.txt",
    "spec_agent\requirements.txt",
    "scoring\requirements.txt",
    "verification\requirements.txt",
    "checkpoints\requirements.txt"
)
foreach ($r in $reqFiles) {
    $path = Join-Path $Root $r
    if (Test-Path $path) {
        Write-Host "  pip install -r $r"
        & $Pip install -r $path
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed installing $r - continue and fix manually if needed"
        }
    }
}

Write-Host "==> Installing common extras"
& $Pip install behave sqlglot pyyaml pydantic boto3 psycopg2-binary pytest

Write-Host "==> Ensuring .env files exist (secrets not overwritten if present)"
function EnsureEnv([string]$example, [string]$dest) {
    if ((Test-Path $example) -and -not (Test-Path $dest)) {
        Copy-Item $example $dest
        Write-Host "  created $dest from example - edit credentials"
    } elseif (Test-Path $dest) {
        Write-Host "  keep existing $dest"
    }
}
EnsureEnv (Join-Path $Root "ingestion\.env.example") (Join-Path $Root "ingestion\.env")
EnsureEnv (Join-Path $Root "spec_agent\.env.example") (Join-Path $Root "spec_agent\.env")
EnsureEnv (Join-Path $Root "scoring\scoring\.env.example") (Join-Path $Root "scoring\scoring\.env")

Write-Host "==> Loading PYTHONPATH via setup_env.ps1"
. .\setup_env.ps1

Write-Host "==> Smoke-checking CLI modules"
$ErrorActionPreference = "Continue"
$mods = @("analyzer", "coding_agent", "ingestion", "eval", "validator", "core", "scoring", "spec_agent")
foreach ($m in $mods) {
    $null = & $Py -m $m --help 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK  python -m $m"
    } else {
        $null = & $Py -m $m -h 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK  python -m $m"
        } else {
            Write-Host "  WARN python -m $m (exit $LASTEXITCODE) - may need args or .env"
        }
    }
}
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  . .\setup_env.ps1"
Write-Host "  See RUN_PLATFORM.md for commands"
