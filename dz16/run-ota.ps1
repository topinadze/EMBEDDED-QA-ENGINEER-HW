param(
    [Parameter(Mandatory=$false)][string]$Fw = "1.4.0",
    [string[]]$TestName = @(),
    [string]$Markers = "",
    [ValidatePattern("^[a-zA-Z0-9_-]+$")][string]$RunLabel = "ota",
    [string]$Port = "COM4",
    [string]$WifiSsid,
    [string]$WifiPassword,
    [switch]$Interactive,
    [switch]$StopOnFailure,
    [switch]$All
)

Set-Location $PSScriptRoot

$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
}

# Determine marker expression
if (-not $Markers) {
    if ($All) {
        $Markers = "ota"
    } elseif ($Interactive -or ($TestName -join " ") -like "*interrupted*") {
        $Markers = "ota and interactive"
    } else {
        $Markers = "ota and not interactive"
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\ota\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$targets = @()
if ($TestName.Count -eq 0 -or -not $TestName[0]) {
    $targets += "tests\test_ota.py"
} else {
    foreach ($name in $TestName) {
        if ($name -like "*test_ota.py*") {
            $targets += $name
        } else {
            $targets += "tests\test_ota.py::TestOta::$name"
        }
    }
}

$pytestArgs = @("-m", "pytest")

if ($Interactive -or $All -or ($TestName -join " ") -like "*interrupted*") {
    $pytestArgs += "-s"
}
if ($StopOnFailure) {
    $pytestArgs += "-x"
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
    "-rA"
)
if ($PSBoundParameters.ContainsKey("WifiSsid")) {
    $pytestArgs += @("--wifi-ssid", $WifiSsid)
}
if ($PSBoundParameters.ContainsKey("WifiPassword")) {
    $pytestArgs += @("--wifi-password", $WifiPassword)
}
$pytestArgs += $targets

Write-Host "Running OTA test(s): '$($targets -join ', ')' with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
& $python @pytestArgs
