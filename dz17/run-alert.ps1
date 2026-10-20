param(
    [string]$Fw = "2.3.0",
    [string]$Markers = "",
    [string]$TestName = "",
    [string]$Port = "COM4",
    [switch]$Interactive,
    [switch]$All,
    [switch]$Persistent,
    [switch]$ClearHistory
)

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "DZ17 virtual environment not found. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if ($ClearHistory) {
    if ($Markers -or $TestName -or $All -or $Interactive -or $Persistent) {
        throw "-ClearHistory cannot be combined with other selectors; it runs only the explicit full-history cleanup case."
    }
    $Markers = "alert_cleanup"
    $TestName = "test_alert_clear_all_history_on_explicit_operator_approval"
    $HistoryCleanupOnly = $true
    $RunHistoryCleanup = $false
} elseif ($Markers -match "(?i)\balert_cleanup\b") {
    throw "The destructive alert_cleanup case can only run with -ClearHistory."
} elseif ($All) {
    $RunHistoryCleanup = $true
    if ($Markers) {
        $Markers = "($Markers) and not alert_cleanup"
    } else {
        $Markers = "alert and not alert_cleanup"
    }
} elseif ($Markers) {
    $RunHistoryCleanup = $true
    $Markers = "($Markers) and not alert_cleanup"
} elseif (-not $Markers) {
    $RunHistoryCleanup = $true
    $markerParts = @("alert")
    if ($Interactive) {
        $markerParts += @("interactive", "not alert_cleanup")
    } elseif ($Persistent) {
        $markerParts += @("persistent", "not interactive")
    } else {
        $markerParts += @("not persistent", "not interactive")
    }
    $Markers = $markerParts -join " and "
}

$date = Get-Date -Format "yyyyMMdd"
$dir = ".\logs\automated\alert\$Fw"
New-Item -ItemType Directory -Force $dir | Out-Null

function Invoke-AlertPytest {
    param(
        [string]$SelectedMarkers,
        [string]$SelectedTestName = "",
        [string]$RunLabel = "alert"
    )

    $pytestArgs = @(
        "-m", "pytest",
        "-s",
        "-c", "pytest.ini",
        "-m", $SelectedMarkers,
        "--port", $Port,
        "--expected-fw-version", $Fw,
        "-o", "log_cli=true",
        "-o", "log_cli_level=DEBUG",
        "--log-file=$dir\run-$date-$RunLabel.log",
        "--log-file-level=DEBUG",
        "--junitxml=$dir\run-$date-$RunLabel-junit.xml",
        "-rA",
        "tests\test_alert.py"
    )

    if ($SelectedTestName) {
        $pytestArgs += @("-k", $SelectedTestName)
    }

    & $python @pytestArgs
    return $LASTEXITCODE
}

function Get-AlertCleanupSkip {
    param([string]$RunLabel)

    $junitPath = Join-Path $dir "run-$date-$RunLabel-junit.xml"
    if (-not (Test-Path $junitPath)) {
        throw "Alert cleanup did not produce its expected JUnit report: $junitPath"
    }

    [xml]$report = Get-Content -Raw $junitPath
    $testCase = $report.SelectSingleNode(
        "//testcase[@name='test_alert_clear_all_history_on_explicit_operator_approval']"
    )
    if ($null -eq $testCase) {
        throw "Alert cleanup test is missing from its JUnit report: $junitPath"
    }

    $skipped = $testCase.SelectSingleNode("skipped")
    if ($null -eq $skipped) {
        return [pscustomobject]@{ Skipped = $false; Reason = "" }
    }
    return [pscustomobject]@{
        Skipped = $true
        Reason = $skipped.GetAttribute("message")
    }
}

if ($RunHistoryCleanup) {
    do {
        $response = Read-Host "Before the Alert pack, review and clear the entire alert history? [y/N]"
        if ([string]::IsNullOrWhiteSpace($response)) {
            $response = "n"
        }
        $response = $response.Trim().ToLowerInvariant()
        if ($response -notin @("y", "yes", "n", "no")) {
            Write-Host "Enter y or n." -ForegroundColor Yellow
        }
    } while ($response -notin @("y", "yes", "n", "no"))

    if ($response -in @("y", "yes")) {
        Write-Host "The cleanup test will show the current alert list and require final confirmation before deleting history." -ForegroundColor Yellow
        $cleanupExitCode = Invoke-AlertPytest `
            -SelectedMarkers "alert_cleanup" `
            -SelectedTestName "test_alert_clear_all_history_on_explicit_operator_approval" `
            -RunLabel "alert-clear"
        if ($cleanupExitCode -ne 0) {
            Write-Error "Alert history cleanup did not complete successfully; the Alert test pack was not started."
            exit $cleanupExitCode
        }
        $cleanupResult = Get-AlertCleanupSkip -RunLabel "alert-clear"
        $operatorDeclinedCleanup = $cleanupResult.Reason -like "*Operator declined to acknowledge all alerts and clear history*"
        if ($cleanupResult.Skipped -and -not $operatorDeclinedCleanup) {
            Write-Error "Alert history cleanup was skipped ($($cleanupResult.Reason)); the Alert test pack was not started."
            exit 1
        }
        if ($cleanupResult.Skipped) {
            Write-Host "Final cleanup approval was declined; history remains unchanged and the Alert test pack will continue." -ForegroundColor Cyan
        }
    } else {
        Write-Host "Keeping existing alert history; no alerts will be acknowledged or deleted by the launcher." -ForegroundColor Cyan
    }
}

Write-Host "Running Alert Center tests with markers: '$Markers' against FW $Fw on $Port..." -ForegroundColor Cyan
$testExitCode = Invoke-AlertPytest -SelectedMarkers $Markers -SelectedTestName $TestName
if ($HistoryCleanupOnly -and $testExitCode -eq 0) {
    $cleanupResult = Get-AlertCleanupSkip -RunLabel "alert"
    if ($cleanupResult.Skipped) {
        Write-Error "Alert history was not cleared because the cleanup test was skipped: $($cleanupResult.Reason)"
        exit 1
    }
}
exit $testExitCode
