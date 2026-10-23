param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [switch]$Interactive,
    [switch]$All,
    [switch]$Persistent,
    [switch]$LongRangeOnly
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if ($All -and ($Markers -or $LongRangeOnly)) {
    throw "Do not combine -All with -Markers or -LongRangeOnly; -All selects every test in tests\test_distance.py."
}

if ($LongRangeOnly) {
    if ($Markers) {
        throw "Do not combine -LongRangeOnly with -Markers; select the long-range case using one option."
    }
    $Markers = "distance and long_range"
} elseif ($All) {
    # Select the whole module below without a pytest marker expression.
} elseif (-not $Markers) {
    if ($Interactive) {
        $markerParts = @("distance and interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $markerParts += "not long_range"
        $Markers = $markerParts -join " and "
    } else {
        $markerParts = @("distance and not interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $markerParts += "not long_range"
        $Markers = $markerParts -join " and "
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\distance\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest"
)

if ($Interactive -or $All -or $LongRangeOnly) {
    $pytestArgs += "-s"
}

$pytestArgs += @(
    "-c", "pytest.ini",
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-distance.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-distance-junit.xml",
    "-rA",
    "tests\test_distance.py"
)

if ($All) {
    $pytestArgs += @("-o", "addopts=-v --tb=short --alluredir=allure-results")
} else {
    $pytestArgs += @("-m", $Markers)
}

if ($All) {
    Write-Host "Running all Sonar Distance tests against FW $Fw on $Port..." -ForegroundColor Cyan
} else {
    Write-Host "Running Sonar Distance tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
}
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
