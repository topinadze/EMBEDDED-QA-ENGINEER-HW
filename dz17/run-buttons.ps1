param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [switch]$All
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if ($All -and -not $Markers) {
    $Markers = "buttons"
} elseif (-not $Markers) {
    $Markers = "buttons"
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\buttons\$Fw"
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
    "--log-file=$dir\run-$date-buttons.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-buttons-junit.xml",
    "-rA",
    "tests\test_buttons.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Host "Running Buttons tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
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
