param(
    [string]$Fw = "2.3.0",
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

if ($All) {
    if ($Markers -or $Interactive -or $Persistent) {
        throw "-All cannot be combined with -Markers, -Interactive, or -Persistent. Use -TestName to select a case from the full relay suite."
    }
    $Markers = "relay"
} else {
    if (-not $Persistent -and -not $Interactive) {
        throw "Relay tests are marked persistent and actuate the relay. Opt in with -Persistent for non-interactive tests, -Interactive for interactive tests, or -All for the complete suite."
    }

    $markerParts = @("relay", "persistent")
    if ($Markers) {
        $markerParts += "($Markers)"
    }
    if ($Interactive) {
        $markerParts += "interactive"
    } else {
        $markerParts += "not interactive"
    }
    $Markers = $markerParts -join " and "
}

$runManualChecks = $Interactive -or $All
$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\relay\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest",
    "-s"
)

if ($runManualChecks) {
    $pytestArgs += "--manual-checks"
}

$pytestArgs += @(
    "-c", "pytest.ini",
    "-m", $Markers,
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-relay.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-relay-junit.xml",
    "-rA",
    "tests\test_relay.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

Write-Warning "Relay switching increments persistent NVS state. The sonar alarm test also changes the stored threshold to 30 cm and leaves the alarm off; it cannot restore the unreadable previous threshold."
if ($runManualChecks) {
    Write-Warning "This selection includes operator interaction. Prepare to observe the relay and/or GPIO4 indicator and respond to the test prompts."
}
Write-Host "Running Relay tests with markers: '$Markers' against FW $Fw on $Port (manual checks: $runManualChecks)..." -ForegroundColor Cyan
& $python @pytestArgs
exit $LASTEXITCODE
