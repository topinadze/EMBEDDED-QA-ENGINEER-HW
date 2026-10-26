param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [Alias("Interactive")][switch]$ManualChecks,
    [switch]$Persistent,
    [switch]$All
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if (-not $Markers) {
    if ($All) {
        $Markers = "auth"
    } elseif ($ManualChecks) {
        if ($Persistent) {
            $Markers = "auth and interactive"
        } else {
            $Markers = "auth and interactive and not persistent"
        }
    } elseif ($Persistent) {
        $Markers = "auth and persistent and not interactive"
    } else {
        $Markers = "auth and not interactive and not persistent"
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\auth\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest"
)

if ($ManualChecks -or $All) {
    $pytestArgs += "-s"
    $pytestArgs += "--manual-checks"
}

$pytestArgs += @(
    "-c", "pytest.ini",
    "-m", $Markers,
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-auth.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-auth-junit.xml",
    "-rA",
    "tests\test_auth.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Host "Running Auth tests with markers: '$Markers' against FW $Fw on $Port (manual checks: $($ManualChecks -or $All))..." -ForegroundColor Cyan
$previousInteractionMode = [Environment]::GetEnvironmentVariable("INTERACTION_MODE", "Process")
try {
    $env:INTERACTION_MODE = $InteractionMode
    & $python @pytestArgs
    $pytestExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $previousInteractionMode) {
        Remove-Item Env:INTERACTION_MODE -ErrorAction SilentlyContinue
    } else {
        $env:INTERACTION_MODE = $previousInteractionMode
    }
}
exit $pytestExitCode
