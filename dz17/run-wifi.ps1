param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
    [string]$WifiSsid,
    [string]$WifiPassword,
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
        $Markers = "wifi"
    } elseif ($Interactive) {
        $markerParts = @("wifi and interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    } else {
        $markerParts = @("wifi and not interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\wifi\$Fw"
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
    "--log-file=$dir\run-$date-wifi.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-wifi-junit.xml",
    "-rA",
    "tests\test_wifi.py"
)

if ($TestName) {
    $pytestArgs += @("-k", $TestName)
}

if ($PSBoundParameters.ContainsKey("WifiSsid")) {
    $pytestArgs += @("--wifi-ssid", $WifiSsid)
}
if ($PSBoundParameters.ContainsKey("WifiPassword")) {
    $pytestArgs += @("--wifi-password", $WifiPassword)
}

Write-Host "Running Wi-Fi tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
& $python @pytestArgs
