param(
    [string]$Port = "COM4",
    [string]$WifiSsid,
    [string]$WifiPassword
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$runner = Join-Path $PSScriptRoot "run-ota.ps1"
$detector = Join-Path $PSScriptRoot "detect_firmware.py"
$chainRunId = [guid]::NewGuid().ToString("N")
$script:chainRunId = $chainRunId
$script:chainHadCheckFailures = $false
$script:WifiSsidSpecified = $PSBoundParameters.ContainsKey("WifiSsid")
$script:WifiPasswordSpecified = $PSBoundParameters.ContainsKey("WifiPassword")
$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
}
$versions = @("1.3.0", "1.4.0", "1.5.0")

function Get-RunningFirmware {
    Write-Host "Detecting firmware on $Port..." -ForegroundColor Cyan
    $output = & $python $detector --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Could not detect firmware on $Port. Resolve the UART/firmware issue before running the OTA chain."
    }

    $match = [regex]::Match(($output -join "`n"), "DETECTED_FIRMWARE=(1\.3\.0|1\.4\.0|1\.5\.0)")
    if (-not $match.Success) {
        throw "Firmware detector returned no supported version. Output: $($output -join ' ')"
    }
    return $match.Groups[1].Value
}

function Invoke-OtaBatch {
    param(
        [Parameter(Mandatory=$true)][string]$Firmware,
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][string[]]$Tests,
        [switch]$ContinueOnFailure
    )

    $actualFirmware = Get-RunningFirmware
    if ($actualFirmware -ne $Firmware) {
        throw "Expected firmware $Firmware before phase '$Label', but UART reports $actualFirmware. Stopping chain."
    }

    Write-Host "`n=== OTA phase '$Label' (detected firmware $actualFirmware) ===" -ForegroundColor Cyan
    $artifactLabel = "$Label-$script:chainRunId"
    $runnerArgs = @{
        Fw = $Firmware
        Port = $Port
        All = $true
        RunLabel = $artifactLabel
        TestName = $Tests
    }
    if (-not $ContinueOnFailure) {
        $runnerArgs.StopOnFailure = $true
    }
    if ($script:WifiSsidSpecified) {
        $runnerArgs.WifiSsid = $WifiSsid
    }
    if ($script:WifiPasswordSpecified) {
        $runnerArgs.WifiPassword = $WifiPassword
    }
    & $runner @runnerArgs
    $phaseExitCode = $LASTEXITCODE
    if ($phaseExitCode -ne 0 -and -not $ContinueOnFailure) {
        throw "OTA phase '$Label' failed with exit code $LASTEXITCODE. Stopping before the next firmware transition."
    }
    if ($phaseExitCode -ne 0) {
        $script:chainHadCheckFailures = $true
        Write-Warning "OTA check phase '$Label' had failures; preserving its report and continuing with the remaining independent checks."
    }

    $junitDirectory = Join-Path $PSScriptRoot "logs\automated\ota\$Firmware"
    $junitArtifact = Get-ChildItem -Path $junitDirectory -Filter "run-*$artifactLabel-junit.xml" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $junitArtifact) {
        throw "OTA phase '$Label' produced no JUnit report; stopping the chain."
    }

    [xml]$junit = Get-Content -LiteralPath $junitArtifact.FullName -Raw
    foreach ($testCase in $junit.SelectNodes("//testcase[skipped]")) {
        $skip = $testCase.SelectSingleNode("skipped")
        $reason = [string]$skip.GetAttribute("message")
        $skipType = [string]$skip.GetAttribute("type")
        $testName = [string]$testCase.GetAttribute("name")
        if (
            $testName -ne "test_interrupted_download_can_be_retried" -or
            $skipType -ne "pytest.xfail" -or
            $reason -notmatch "BUG-06"
        ) {
            if ($ContinueOnFailure) {
                $script:chainHadCheckFailures = $true
                Write-Warning "OTA check phase '$Label' skipped '$testName' ($skipType): $reason. Continuing with remaining chain checks."
                continue
            }
            throw "OTA phase '$Label' skipped '$testName' ($skipType): $reason. Stopping the chain."
        }
    }
}

function Invoke-VersionChecks {
    param(
        [Parameter(Mandatory=$true)][string]$Firmware,
        [Parameter(Mandatory=$true)][string]$RunLabel
    )

    $tests = @(
        "tests\test_ota.py::test_usable_ipv4_guard",
        "test_version_reports_active_partition",
        "test_ota_check_reports_channel_versions",
        "test_ota_update_without_wifi_is_rejected",
        "test_ota_test_server_does_not_change_firmware"
    )

    if ($Firmware -eq "1.4.0") {
        $tests += @(
            "test_current_channel_is_not_reinstalled[stable-already-current]",
            "test_downgrade_without_force_is_blocked[from-1.4]"
        )
    } elseif ($Firmware -eq "1.5.0") {
        $tests += @(
            "test_current_channel_is_not_reinstalled[beta-already-current]",
            "test_downgrade_without_force_is_blocked[from-1.5]",
            "test_interrupted_download_can_be_retried"
        )
    }

    Invoke-OtaBatch `
        -Firmware $Firmware `
        -Label $RunLabel `
        -Tests $tests `
        -ContinueOnFailure
    Invoke-OtaBatch `
        -Firmware $Firmware `
        -Label "$RunLabel-wifi-recovery" `
        -Tests @("test_wifi_connection_can_be_established")
}

function Invoke-FirmwareTransition {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Target
    )

    $node = $null
    if ($Source -eq "1.3.0" -and $Target -eq "1.4.0") {
        $node = "test_available_update_completes_self_check[stable-1.3-to-1.4]"
    } elseif ($Source -eq "1.4.0" -and $Target -eq "1.5.0") {
        $node = "test_available_update_completes_self_check[beta-1.4-to-1.5]"
    } elseif ($Source -eq "1.5.0" -and $Target -eq "1.4.0") {
        $node = "test_forced_downgrade_completes_self_check[from-1.5-to-1.4]"
    } elseif ($Source -eq "1.4.0" -and $Target -eq "1.3.0") {
        $node = "test_forced_downgrade_completes_self_check[from-1.4-to-1.3]"
    } else {
        throw "Unsupported OTA chain transition: $Source -> $Target."
    }

    $label = "chain-" + ($Source -replace "\.", "-") + "-to-" + ($Target -replace "\.", "-")
    Invoke-OtaBatch -Firmware $Source -Label $label -Tests @($node)
}

$initialFirmware = Get-RunningFirmware
if ($versions -notcontains $initialFirmware) {
    throw "Detected unsupported starting firmware: $initialFirmware."
}
if ($script:WifiSsidSpecified -and [string]::IsNullOrWhiteSpace($WifiSsid)) {
    throw "The per-run Wi-Fi SSID override cannot be empty."
}
if (
    $script:WifiPasswordSpecified -and
    ([string]::IsNullOrWhiteSpace($WifiPassword) -or $WifiPassword.Length -lt 8)
) {
    throw "The per-run Wi-Fi password override must contain at least 8 characters."
}

$originalSsid = $env:HW16_WIFI_SSID
$originalPassword = $env:HW16_WIFI_PASSWORD
if ($script:WifiSsidSpecified) {
    $env:HW16_WIFI_SSID = $WifiSsid
}
if ($script:WifiPasswordSpecified) {
    $env:HW16_WIFI_PASSWORD = $WifiPassword
}
$credentialStatus = & $python -c "from config.test_config import resolve_wifi_credentials; ssid, password = resolve_wifi_credentials(); print('WIFI_CREDENTIALS_READY=' + str(bool(ssid and password and len(password) >= 8)))"
$env:HW16_WIFI_SSID = $originalSsid
$env:HW16_WIFI_PASSWORD = $originalPassword
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve Wi-Fi credentials from local defaults/environment. Resolve the configuration error before running the OTA chain."
}
if (($credentialStatus -join "`n") -notmatch "(?m)^WIFI_CREDENTIALS_READY=True$") {
    throw "The OTA chain needs a Wi-Fi SSID and a password of at least 8 characters. Configure config/wifi_secrets.py, set HW16_WIFI_SSID and HW16_WIFI_PASSWORD (or the TEST_WIFI_* aliases), or pass -WifiSsid/-WifiPassword; values are not displayed."
}
Write-Host "Wi-Fi credentials are configured; their values are hidden." -ForegroundColor DarkGray

$planned = switch ($initialFirmware) {
    "1.3.0" { "1.3.0 checks -> 1.4.0 checks -> 1.5.0 checks -> 1.4.0 -> 1.3.0 (end)"; break }
    "1.4.0" { "1.4.0 checks -> 1.5.0 checks -> 1.4.0 -> 1.3.0 checks -> 1.4.0 (end)"; break }
    "1.5.0" { "1.5.0 checks -> 1.4.0 checks -> 1.3.0 checks -> 1.4.0 -> 1.5.0 (end)"; break }
}

Write-Host "Detected starting firmware: $initialFirmware." -ForegroundColor Green
Write-Host "OTA chain: $planned." -ForegroundColor Yellow
Write-Host "Run ID: $chainRunId" -ForegroundColor DarkGray
Write-Host "The chain includes Wi-Fi interruption/retry testing on 1.5.0 and changes firmware. Configured Wi-Fi credentials are used if saved credentials were erased."
$confirmation = Read-Host "Type OTA-CHAIN to continue"
if ($confirmation -cne "OTA-CHAIN") {
    Write-Host "OTA chain cancelled; no tests were run." -ForegroundColor Yellow
    exit 1
}

try {
    switch ($initialFirmware) {
        "1.3.0" {
            Invoke-VersionChecks -Firmware "1.3.0" -RunLabel "chain-stage-01-1-3-0-checks"
            Invoke-FirmwareTransition -Source "1.3.0" -Target "1.4.0"
            Invoke-VersionChecks -Firmware "1.4.0" -RunLabel "chain-stage-02-1-4-0-checks"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.5.0"
            Invoke-VersionChecks -Firmware "1.5.0" -RunLabel "chain-stage-03-1-5-0-checks"
            Invoke-FirmwareTransition -Source "1.5.0" -Target "1.4.0"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.3.0"
        }
        "1.4.0" {
            Invoke-VersionChecks -Firmware "1.4.0" -RunLabel "chain-stage-01-1-4-0-checks"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.5.0"
            Invoke-VersionChecks -Firmware "1.5.0" -RunLabel "chain-stage-02-1-5-0-checks"
            Invoke-FirmwareTransition -Source "1.5.0" -Target "1.4.0"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.3.0"
            Invoke-VersionChecks -Firmware "1.3.0" -RunLabel "chain-stage-03-1-3-0-checks"
            Invoke-FirmwareTransition -Source "1.3.0" -Target "1.4.0"
        }
        "1.5.0" {
            Invoke-VersionChecks -Firmware "1.5.0" -RunLabel "chain-stage-01-1-5-0-checks"
            Invoke-FirmwareTransition -Source "1.5.0" -Target "1.4.0"
            Invoke-VersionChecks -Firmware "1.4.0" -RunLabel "chain-stage-02-1-4-0-checks"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.3.0"
            Invoke-VersionChecks -Firmware "1.3.0" -RunLabel "chain-stage-03-1-3-0-checks"
            Invoke-FirmwareTransition -Source "1.3.0" -Target "1.4.0"
            Invoke-FirmwareTransition -Source "1.4.0" -Target "1.5.0"
        }
    }

    $finalFirmware = Get-RunningFirmware
    if ($finalFirmware -ne $initialFirmware) {
        throw "OTA chain ended on firmware $finalFirmware instead of the starting firmware $initialFirmware."
    }
    if ($script:chainHadCheckFailures) {
        throw "OTA chain completed all firmware transitions and returned to $initialFirmware, but one or more firmware-check tests failed. Review the phase JUnit and UART reports."
    }
} catch {
    Write-Error $_
    exit 1
}

Write-Host "`nOTA chain completed. The board is back on its starting firmware $initialFirmware." -ForegroundColor Green
