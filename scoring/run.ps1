# Launch scoring — reads scoring/scoring/.env (paths + PYTHONPATH / SCORING_ROOT)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py @Args
    } else {
        & python @Args
    }
}

Invoke-Py (Join-Path $Root "run.py") @args
exit $LASTEXITCODE
