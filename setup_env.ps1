# Automated AI Platform environment — run from repo root:
#   . .\setup_env.ps1
# Then: & $env:AAP_PYTHON -m analyzer --help | & $env:AAP_PYTHON -m core --help | etc.

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Root) { $Root = (Get-Location).Path }

$env:AAP_ROOT = $Root

# Nested packages need their parent folder on PYTHONPATH.
$pathParts = @(
    $Root,                            # analyzer, analyzer_agent, coding_agent, ingestion, eval, validator, spec_agent, …
    (Join-Path $Root "core"),         # python -m core
    (Join-Path $Root "scoring"),      # python -m scoring
    (Join-Path $Root "verification"), # verification helpers
    (Join-Path $Root "sandbox")       # sandbox package if used
)
$env:PYTHONPATH = ($pathParts -join ";")

# Prefer repo venv when present
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$scoringPy = Join-Path $Root "scoring\.venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $env:AAP_PYTHON = $venvPy
    & (Join-Path $Root ".venv\Scripts\Activate.ps1")
} elseif (Test-Path $scoringPy) {
    $env:AAP_PYTHON = $scoringPy
    Write-Host "Using scoring\.venv (create root .venv with .\setup_platform.ps1 for full stack)"
} else {
    $env:AAP_PYTHON = "py"
}

Write-Host "AAP_ROOT = $env:AAP_ROOT"
Write-Host "PYTHONPATH  = $env:PYTHONPATH"
Write-Host "Python      = $env:AAP_PYTHON"
