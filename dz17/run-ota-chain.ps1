param(
    [string]$Port = "COM4",
    [ValidateSet("console", "telegram")][string]$InteractionMode = "console",
    [switch]$All
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

if (-not $All) {
    throw "The OTA chain changes firmware and includes interactive/persistent tests. Re-run with -All to explicitly opt in."
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$detector = Join-Path $PSScriptRoot "detect_firmware.py"
$runner = Join-Path $PSScriptRoot "run-ota.ps1"
$supportedVersions = @("2.1.0", "2.3.0")
$runId = [guid]::NewGuid().ToString("N")
$script:chainFailures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

function Get-RunningFirmware {
    param([Parameter(Mandatory=$true)][string]$Phase)

    $lastOutput = ""
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $output = & $python $detector --port $Port 2>&1
        $exitCode = $LASTEXITCODE
        $lastOutput = $output -join "`n"
        if ($exitCode -eq 0) {
            $match = [regex]::Match(
                $lastOutput,
                "(?m)^DETECTED_FIRMWARE=(\d+\.\d+\.\d+)$"
            )
            if (-not $match.Success) {
                throw "Firmware detection after '$Phase' returned no version. Output: $lastOutput"
            }
            $version = $match.Groups[1].Value
            if ($supportedVersions -notcontains $version) {
                throw "Unsupported firmware $version detected after '$Phase'."
            }
            return $version
        }

        if ($lastOutput -match "Unsupported firmware version") {
            throw "Unsupported firmware detected after '$Phase'. Output: $lastOutput"
        }
        if ($attempt -lt 5) {
            Write-Warning "Firmware UART is not ready after '$Phase' (attempt $attempt/5); retrying detection."
            Start-Sleep -Seconds 3
        }
    }

    throw "Could not detect firmware after '$Phase'. Resolve the UART/reboot issue before continuing. Last output: $lastOutput"
}

function Invoke-OtaBatch {
    param(
        [Parameter(Mandatory=$true)][string]$Firmware,
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][string]$TestFilter,
        [Parameter(Mandatory=$true)][string]$ExpectedFirmwareAfter
    )

    $actualBefore = Get-RunningFirmware -Phase "before $Label"
    if ($actualBefore -ne $Firmware) {
        throw "Expected firmware $Firmware before '$Label', but UART reports $actualBefore. Stopping chain."
    }

    $artifactLabel = "$Label-$runId"
    $runnerArgs = @{
        Fw = $Firmware
        Port = $Port
        All = $true
        InteractionMode = $InteractionMode
        RunLabel = $artifactLabel
        FromChain = $true
        TestName = $TestFilter
    }

    Write-Host "`n=== OTA phase: $Label (firmware $actualBefore) ===" -ForegroundColor Cyan
    & $runner @runnerArgs
    $runnerExitCode = $LASTEXITCODE

    $junitDirectory = Join-Path $PSScriptRoot "logs\automated\ota\$Firmware"
    $junitArtifact = Get-ChildItem -Path $junitDirectory -Filter "run-*$artifactLabel-junit.xml" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $junitArtifact) {
        throw "OTA phase '$Label' produced no JUnit report in $junitDirectory."
    }

    $junitPath = $junitArtifact.FullName
    [xml]$junit = Get-Content -LiteralPath $junitPath -Raw
    $suite = $junit.SelectSingleNode("/testsuites/testsuite")
    if ($null -eq $suite) {
        throw "OTA phase '$Label' produced an invalid JUnit report: $junitPath."
    }
    $testCount = [int]$suite.GetAttribute("tests")
    $failureCount = [int]$suite.GetAttribute("failures")
    $errorCount = [int]$suite.GetAttribute("errors")
    $skippedCount = [int]$suite.GetAttribute("skipped")
    if ($testCount -le 0) {
        throw "OTA phase '$Label' selected no tests according to $junitPath."
    }

    Write-Host "Phase result: tests=$testCount, failures=$failureCount, errors=$errorCount, skipped=$skippedCount." -ForegroundColor DarkGray
    if ($runnerExitCode -ne 0 -or $failureCount -gt 0 -or $errorCount -gt 0) {
        $script:chainFailures.Add("${Label}: $failureCount failure(s), $errorCount error(s); see $junitPath.")
        Write-Warning "OTA phase '$Label' had test failures; checking device firmware before deciding whether the chain can continue."
    }

    $actualAfter = Get-RunningFirmware -Phase "after $Label"
    if ($actualAfter -ne $ExpectedFirmwareAfter) {
        throw "After '$Label', expected firmware $ExpectedFirmwareAfter but UART reports $actualAfter. Stopping chain."
    }
    Write-Host "Verified firmware after '$Label': $actualAfter." -ForegroundColor Green
}

function Invoke-VersionChecks {
    param([Parameter(Mandatory=$true)][string]$Firmware, [Parameter(Mandatory=$true)][string]$Label)

    Invoke-OtaBatch `
        -Firmware $Firmware `
        -Label $Label `
        -TestFilter "not test_available_update_completes_self_check and not test_forced_downgrade_completes_self_check" `
        -ExpectedFirmwareAfter $Firmware
}

function Invoke-FirmwareTransition {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Target
    )

    if ($Source -eq "2.1.0" -and $Target -eq "2.3.0") {
        $testFilter = "test_available_update_completes_self_check"
    } elseif ($Source -eq "2.3.0" -and $Target -eq "2.1.0") {
        $testFilter = "test_forced_downgrade_completes_self_check"
    } else {
        throw "Unsupported OTA chain transition: $Source -> $Target."
    }

    $label = "chain-$($Source.Replace('.', '-'))-to-$($Target.Replace('.', '-'))"
    Invoke-OtaBatch `
        -Firmware $Source `
        -Label $label `
        -TestFilter $testFilter `
        -ExpectedFirmwareAfter $Target
}

$initialFirmware = Get-RunningFirmware -Phase "initial preflight"
if ($initialFirmware -eq "2.1.0") {
    $planned = "2.1.0 checks -> upgrade to 2.3.0 -> 2.3.0 checks -> downgrade to 2.1.0"
} else {
    $planned = "2.3.0 checks -> downgrade to 2.1.0 -> 2.1.0 checks -> upgrade to 2.3.0"
}

Write-Host "Detected starting firmware: $initialFirmware." -ForegroundColor Green
Write-Host "OTA chain: $planned." -ForegroundColor Yellow
Write-Host "Interaction mode: $InteractionMode. Run ID: $runId" -ForegroundColor DarkGray
Write-Host "This -All run includes interactive Wi-Fi interruption and persistent firmware changes. Keep the board powered and follow each operator prompt." -ForegroundColor Yellow
$confirmation = Read-Host "Type OTA-CHAIN to continue"
if ($confirmation -cne "OTA-CHAIN") {
    Write-Host "OTA chain cancelled; no tests were run." -ForegroundColor Yellow
    exit 1
}

if ($initialFirmware -eq "2.1.0") {
    Invoke-VersionChecks -Firmware "2.1.0" -Label "chain-stage-01-2-1-0-checks"
    Invoke-FirmwareTransition -Source "2.1.0" -Target "2.3.0"
    Invoke-VersionChecks -Firmware "2.3.0" -Label "chain-stage-02-2-3-0-checks"
    Invoke-FirmwareTransition -Source "2.3.0" -Target "2.1.0"
} else {
    Invoke-VersionChecks -Firmware "2.3.0" -Label "chain-stage-01-2-3-0-checks"
    Invoke-FirmwareTransition -Source "2.3.0" -Target "2.1.0"
    Invoke-VersionChecks -Firmware "2.1.0" -Label "chain-stage-02-2-1-0-checks"
    Invoke-FirmwareTransition -Source "2.1.0" -Target "2.3.0"
}

$finalFirmware = Get-RunningFirmware -Phase "final verification"
if ($finalFirmware -ne $initialFirmware) {
    throw "OTA chain ended on firmware $finalFirmware instead of its starting firmware $initialFirmware."
}

if ($script:chainFailures.Count -gt 0) {
    Write-Error "OTA chain returned to $initialFirmware, but one or more test phases failed:`n - $($script:chainFailures -join "`n - ")"
    exit 1
}

Write-Host "`nOTA chain completed; the board is back on starting firmware $initialFirmware." -ForegroundColor Green
