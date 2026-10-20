param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
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
    if ($All) {
        $Markers = "lamp"
    } elseif ($Interactive) {
        $markerParts = @("lamp and interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    } else {
        $markerParts = @("lamp and not interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\lamp\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest"
)

if ($Interactive -or $All) {
    $pytestArgs += "-s"
}

$pytestArgs += @(
    "-c", "pytest.ini",
    "-m", $Markers,
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-lamp.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-lamp-junit.xml",
    "-rA",
    "tests\test_lamp.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Host "Running Lamp tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
& $python @pytestArgs
