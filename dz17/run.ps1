param(
    [Parameter(Mandatory=$false)][string]$Fw = "2.1.0",
    [string]$Markers = "",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [string]$WifiSsid,
    [securestring]$WifiPassword,
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
        $Markers = "interactive or not interactive"
    } elseif ($Interactive) {
        $markerParts = @("interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    } else {
        $markerParts = @("not interactive")
        if (-not $Persistent) {
            $markerParts += "not persistent"
        }
        $Markers = $markerParts -join " and "
    }
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\all\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest"
)

if ($Interactive -or $All) {
    $pytestArgs += "-s"
}

$pytestArgs += @(
    "-c", "pytest.ini",
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$date-full.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$date-junit.xml",
    "-rA"
)

if ($Markers) {
    $pytestArgs += @("-m", $Markers)
}
if ($PSBoundParameters.ContainsKey("WifiSsid")) {
    $pytestArgs += @("--wifi-ssid", $WifiSsid)
}
if ($PSBoundParameters.ContainsKey("WifiPassword")) {
    $wifiPasswordPlain = [System.Net.NetworkCredential]::new("", $WifiPassword).Password
    $pytestArgs += @("--wifi-password", $wifiPasswordPlain)
}

Write-Host "Running DZ17 tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
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
