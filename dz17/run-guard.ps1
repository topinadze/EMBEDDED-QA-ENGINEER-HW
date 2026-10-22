param(
    [string]$Fw = "2.3.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [switch]$Interactive,
    [switch]$All,
    [switch]$Persistent
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if (-not $Markers) {
    $markerParts = @("guard")
    if ($All) {
        # Explicitly include all Guard tests.
    } elseif ($Interactive) {
        $markerParts += "interactive"
    } elseif ($Persistent) {
        $markerParts += @("persistent", "not interactive")
    } else {
        $markerParts += @("not persistent", "not interactive")
    }
    $Markers = $markerParts -join " and "
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\guard\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest",
    "-s",
    "-c", "pytest.ini",
    "-m", $Markers,
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-guard.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-guard-junit.xml",
    "-rA",
    "tests\test_guard.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Host "Running Guard tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
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
