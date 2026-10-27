param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [ValidatePattern("^[a-zA-Z0-9_-]+$")][string]$RunLabel = "ota",
    [switch]$FromChain,
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
        $Markers = "ota"
    } elseif ($ManualChecks) {
        if ($Persistent) {
            $Markers = "ota and interactive"
        } else {
            $Markers = "ota and interactive and not persistent"
        }
    } elseif ($Persistent) {
        $Markers = "ota and persistent and not interactive"
    } else {
        $Markers = "ota and not interactive and not persistent"
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\ota\$Fw"
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
    "--log-file=$dir\run-$date-$RunLabel.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-$RunLabel-junit.xml",
    "-rA",
    "tests\test_ota.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Host "Running OTA tests with markers: '$Markers' against FW $Fw on $Port (manual checks: $($ManualChecks -or $All))..." -ForegroundColor Cyan
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
if ($FromChain) {
    $global:LASTEXITCODE = $pytestExitCode
    return
}
exit $pytestExitCode
