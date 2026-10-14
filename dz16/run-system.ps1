param(
    [Parameter(Mandatory=$false)][string]$Fw = "1.4.0",
    [string]$Markers = "",
    [string]$Port = "COM4",
    [switch]$Interactive,
    [switch]$All,
    [switch]$Persistent
)

Set-Location $PSScriptRoot

$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
}

# Construct markers if user didn't override explicitly
if (-not $Markers) {
    if ($All) {
        $markerParts = @("system")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    } elseif ($Interactive) {
        $markerParts = @("system and interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    } else {
        $markerParts = @("system and not interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\system\$Fw"
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
    "--log-file=$dir\run-$date-system.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-system-junit.xml",
    "-rA",
    "tests\test_system.py"
)

Write-Host "Running System & Peripheral tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
& $python @pytestArgs
