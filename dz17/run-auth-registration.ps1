param(
    [ValidateSet("2.1.0", "2.3.0")][string]$Fw = "2.3.0",
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console"
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$dir = ".\logs\automated\auth-registration\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

$pytestArgs = @(
    "-m", "pytest",
    "-s",
    "--manual-checks",
    "-c", "pytest.ini",
    "-m", "auth_registration and auth and interactive and persistent",
    "--port", $Port,
    "--expected-fw-version", $Fw,
    "-o", "log_cli=true",
    "-o", "log_cli_level=DEBUG",
    "--log-file=$dir\run-$runId-auth-registration.log",
    "--log-file-level=DEBUG",
    "--junitxml=$dir\run-$runId-auth-registration-junit.xml",
    "-rA",
    "tests\test_auth_registration.py"
)

Write-Host "Running the AU-1 registration pack against FW $Fw on $Port." -ForegroundColor Yellow
Write-Host "The pack verifies firmware, then requests exact operator consent and erases NVS once at 0x9000 (length 0x6000)." -ForegroundColor Yellow
Write-Host "This removes the saved account, Wi-Fi profile, and NVS settings; it does not flash firmware. Declining consent performs no erase." -ForegroundColor Yellow
Write-Host "Negative registration cases run first without registering; the final test creates the configured profile." -ForegroundColor Yellow
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
